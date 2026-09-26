"""
weather.py — game-day conditions, forecast and historical.

Two jobs:

  forecast_slate()   Kickoff-window forecast for every game on an upcoming
                     slate, from Open-Meteo (free, no API key): temperature,
                     sustained wind, gusts, chance and amount of rain or snow.
                     Shown next to every pick and archived with it, so the
                     record says what the weather was expected to be when the
                     pick was made.

  gamebook()         What the weather actually was for played games, from the
                     NFL gamebook line nflverse carries in play-by-play
                     ("Rain Temp: 45° F, Humidity: 90%, Wind: NW 12 mph").
                     The schedule file has temperature and wind but no rain or
                     snow; this is the only free historical precipitation
                     record. Feeds the trend checker (trends.py).

How weather reaches the picks: through the trend checker, not a hand-set
number. The betting line already moves for weather, and a flat weather
adjustment measured at zero against it (config.Adjustments). So weather is
one of the conditions trends.py tests every week -- if the model keeps
missing in wind, rain, snow or cold, and the pattern holds on past seasons,
the correction is applied automatically.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from .config import CACHE_DIR, CURRENT_SEASON

# nflverse stadium_id -> (lat, lon). Approximate to ~1 km, which is far finer
# than a weather grid cell.
STADIUMS = {
    "ATL97": (33.755, -84.401), "BAL00": (39.278, -76.623),
    "BOS00": (42.091, -71.264), "BUF00": (42.774, -78.787),
    "BUF01": (42.774, -78.787), "CAR00": (35.226, -80.853),
    "CHI98": (41.862, -87.617), "CIN00": (39.095, -84.516),
    "CLE00": (41.506, -81.700), "DAL00": (32.748, -97.093),
    "DEN00": (39.744, -105.020), "DET00": (42.340, -83.046),
    "GNB00": (44.501, -88.062), "HOU00": (29.685, -95.411),
    "IND00": (39.760, -86.164), "JAX00": (30.324, -81.637),
    "KAN00": (39.049, -94.484), "LAX01": (33.953, -118.339),
    "MIA00": (25.958, -80.239), "MIN01": (44.974, -93.258),
    "NOR00": (29.951, -90.081), "NYC01": (40.814, -74.074),
    "PHI00": (39.901, -75.168), "PHO00": (33.528, -112.263),
    "PIT00": (40.447, -80.016), "SEA00": (47.595, -122.332),
    "SFO01": (37.403, -121.970), "TAM00": (27.976, -82.503),
    "NAS00": (36.166, -86.771), "WAS00": (38.908, -76.864),
    "VEG00": (36.091, -115.184),
    # international / neutral
    "LON00": (51.556, -0.280), "LON01": (51.456, -0.342),
    "LON02": (51.604, -0.066), "GER00": (48.219, 11.625),
    "MUN00": (48.219, 11.625), "MUN01": (48.219, 11.625),
    "FRA00": (50.069, 8.645), "MEX00": (19.303, -99.150),
    "SAO00": (-23.545, -46.474), "RIO00": (-22.912, -43.230),
    "MAD01": (40.453, -3.688), "PAR00": (48.924, 2.360),
    "MEL00": (-37.820, 144.983), "DUB00": (53.361, -6.251),
    "BER00": (52.515, 13.239),
}

# Fixed roofs: weather cannot reach the field.
DOMES = {"DET00", "MIN01", "NOR00", "VEG00", "LAX01"}
# Retractable: nflverse lists these as None until the team decides. Teams
# close them for bad weather, so for modeling they count as indoors.
RETRACTABLE = {"ATL97", "DAL00", "HOU00", "IND00", "PHO00", "MAD01"}
# Open-air fields that nflverse labels 'dome' (the roof covers the stands, or
# nothing at all). Checked BEFORE the nflverse roof value (audit 2026-09-26:
# Paris, Munich and Melbourne were getting no forecast).
OPEN_AIR = {"MEL00", "PAR00", "MUN01", "GER00"}

PRECIP_WORDS = r"rain|shower|drizzle|snow|sleet|flurr|storm|thunder|wintry"
# Pre-game forecast wording in the gamebook line is not observed rain.
FORECAST_WORDS = r"chance|change of|threat|likely|possib|forecast|expected|later|\d+\s*%"
FORECAST_WORDS = FORECAST_WORDS  # (no capture groups: str.contains warns on them)
SNOW_CODES = {71, 73, 75, 77, 85, 86}

# Flag thresholds. Kept equal between forecast and gamebook so a condition
# means the same thing in the history the trend checker learns from and in the
# upcoming slate it is applied to.
WINDY_MPH = 15.0
COLD_F = 32.0
RAIN_PROB = 50.0          # forecast: max hourly precipitation probability, %
RAIN_INCHES = 0.04        # forecast: total over the game window


def venue_kind(stadium_id: str, roof) -> str:
    """'outdoor', 'dome' or 'retractable' for a venue."""
    r = str(roof).lower() if roof is not None and not pd.isna(roof) else ""
    if stadium_id in OPEN_AIR:
        return "outdoor"
    if stadium_id in DOMES or r == "dome":
        return "dome"
    if stadium_id in RETRACTABLE or r == "closed":
        return "retractable"
    return "outdoor"


# ── forecast ────────────────────────────────────────────────────────────

def _open_meteo(lat: float, lon: float, day: str) -> dict:
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "hourly": ("temperature_2m,precipitation_probability,precipitation,"
                   "wind_speed_10m,wind_gusts_10m,weather_code"),
        "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
        "precipitation_unit": "inch", "timezone": "America/New_York",
        "start_date": day, "end_date": day,
    })
    req = urllib.request.Request(f"https://api.open-meteo.com/v1/forecast?{q}",
                                 headers={"User-Agent": "nflmodel/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def summarize_hours(h: dict, kickoff_et: datetime, hours: int = 4) -> dict:
    """Collapse hourly forecast rows to one line for the game window."""
    times = pd.to_datetime(h["time"])
    lo = pd.Timestamp(kickoff_et.replace(minute=0))
    sel = (times >= lo) & (times < lo + pd.Timedelta(hours=hours))
    if not sel.any():
        return {}
    pick = lambda k: np.array(h[k], dtype=float)[sel]
    temp = pick("temperature_2m")
    wind = pick("wind_speed_10m")
    gust = pick("wind_gusts_10m")
    pp = pick("precipitation_probability")
    pr = pick("precipitation")
    codes = {int(c) for c in pick("weather_code") if not np.isnan(c)}
    out = dict(temp_f=float(np.nanmean(temp)), wind_mph=float(np.nanmax(wind)),
               gust_mph=float(np.nanmax(gust)),
               precip_prob=float(np.nanmax(pp)) if len(pp) else float("nan"),
               precip_in=float(np.nansum(pr)),
               snow=bool(codes & SNOW_CODES),
               # The kickoff-hour reading. Flags use THIS, because the history
               # the trend checker learns from is one gamebook reading at
               # kickoff; the window max/mean above are for display only.
               kick_temp_f=float(temp[0]), kick_wind_mph=float(wind[0]))
    return out


def _flags(temp, wind, precip: bool, snow: bool) -> dict:
    return dict(windy=bool(wind is not None and not pd.isna(wind) and wind >= WINDY_MPH),
                precip=bool(precip or snow), snow=bool(snow),
                cold=bool(temp is not None and not pd.isna(temp) and temp <= COLD_F))


def label(w: dict) -> str:
    """'61°F, wind 12 mph, 60% rain' -- or 'dome'."""
    if w.get("kind") == "dome":
        return "dome"
    if "temp_f" not in w:
        return "forecast unavailable"
    parts = [f"{w['temp_f']:.0f}°F", f"wind {w['wind_mph']:.0f} mph"]
    if w.get("gust_mph", 0) >= w.get("wind_mph", 0) + 10:
        parts[-1] += f" (gusts {w['gust_mph']:.0f})"
    pp = w.get("precip_prob")
    if pp is not None and not pd.isna(pp) and pp >= 20:
        parts.append(f"{pp:.0f}% {'snow' if w.get('snow') else 'rain'}")
    s = ", ".join(parts)
    if w.get("kind") == "retractable":
        s += " (retractable roof)"
    return s


def forecast_slate(slate_games: pd.DataFrame, verbose: bool = True) -> dict:
    """
    game_id -> forecast dict for every game on the slate. Never raises: a
    dead weather feed degrades to 'forecast unavailable' and the week goes on.
    """
    out = {}
    for _, g in slate_games.iterrows():
        sid = g.get("stadium_id")
        kind = venue_kind(sid, g.get("roof"))
        w = {"kind": kind, "stadium": g.get("stadium")}
        if kind != "dome" and sid in STADIUMS:
            try:
                # gameday arrives as a Timestamp from load_games() and as a
                # string from a raw parquet read; normalize both.
                day = pd.Timestamp(g.gameday).strftime("%Y-%m-%d")
                kick = datetime.strptime(f"{day} {str(g.gametime)[:5]}", "%Y-%m-%d %H:%M")
                lat, lon = STADIUMS[sid]
                w.update(summarize_hours(_open_meteo(lat, lon, day)["hourly"], kick))
            except Exception as ex:                     # noqa: BLE001 - never fatal
                w["error"] = f"{type(ex).__name__}: {ex}"
        elif kind != "dome":
            w["error"] = f"no coordinates for stadium {sid}"
        if "temp_f" in w:
            rain = (w["precip_prob"] >= RAIN_PROB and w["precip_in"] >= RAIN_INCHES)
            fl = _flags(w["kick_temp_f"], w["kick_wind_mph"], rain, w["snow"] and rain)
            # A retractable roof closes for exactly these conditions, so the
            # flags only count outdoors. The forecast is still shown.
            if kind != "outdoor":
                fl = {k: False for k in fl}
            w.update(fl)
        else:
            w.update(windy=False, precip=False, snow=False, cold=False)
        w["label"] = label(w)
        out[g.game_id] = w
    if verbose:
        bad = [k for k, v in out.items() if "error" in v]
        n_ok = sum(1 for v in out.values() if "temp_f" in v)
        print(f"  weather: forecast for {n_ok} game(s), "
              f"{sum(1 for v in out.values() if v['kind'] == 'dome')} dome"
              + (f", {len(bad)} unavailable" if bad else ""))
    return out


def forecast_columns(slate: pd.DataFrame, fc: dict) -> pd.DataFrame:
    """Attach forecast columns (wx_*) to a slate by game_id."""
    s = slate.copy()
    get = lambda gid, k, d=None: fc.get(gid, {}).get(k, d)
    s["wx_label"] = [get(g, "label", "") for g in s.game_id]
    for k in ("temp_f", "wind_mph", "precip_prob"):
        s[f"wx_{k}"] = [get(g, k, np.nan) for g in s.game_id]
    for k in ("windy", "precip", "cold"):
        s[f"wx_{k}"] = [bool(get(g, k, False)) for g in s.game_id]
    return s


# ── gamebook (what actually happened) ───────────────────────────────────

def _gamebook_path(season: int):
    return CACHE_DIR / f"weather_{season}.parquet"


def gamebook(seasons, refresh: bool = False) -> pd.DataFrame:
    """
    Per-game weather text for played games, one row per game_id, with
    parsed flags (outdoor, precip, snow). Cached per season; the current
    season refreshes daily.
    """
    from .data import PBP_URL
    combined = CACHE_DIR / "weather_2016_2025.parquet"
    frames = []
    for s in seasons:
        path = _gamebook_path(s)
        stale = (not path.exists()) or (
            s >= CURRENT_SEASON and
            datetime.now().timestamp() - path.stat().st_mtime > 12 * 3600)
        if refresh and s >= CURRENT_SEASON:
            stale = True
        if stale and combined.exists() and s < CURRENT_SEASON:
            c = pd.read_parquet(combined)
            if (c.season == s).any():
                c[c.season == s].to_parquet(path, index=False)
                stale = False
        if stale:
            try:
                df = pd.read_parquet(PBP_URL.format(season=s),
                                     columns=["game_id", "weather", "roof", "temp", "wind"])
                g = df.groupby("game_id").first().reset_index()
                g["season"] = s
                g.to_parquet(path, index=False)
            except Exception as ex:                     # noqa: BLE001
                print(f"  [weather] gamebook {s} unavailable ({type(ex).__name__})")
                continue
        frames.append(pd.read_parquet(path))
    if not frames:
        return pd.DataFrame(columns=["game_id", "weather", "precip", "snow"])
    w = pd.concat(frames, ignore_index=True)
    text = w.weather.fillna("").str.lower()
    cond = text.str.split("temp").str[0]
    forecast_only = cond.str.contains(FORECAST_WORDS) & ~cond.str.contains(
        r"^\s*(?:light |heavy )?(?:rain|showers|drizzle|snow)")
    w["precip"] = cond.str.contains(PRECIP_WORDS) & ~forecast_only
    w["snow"] = cond.str.contains(r"snow|flurr|sleet|wintry") & ~forecast_only
    # The schedule file is missing wind/temp for some outdoor games (46% of
    # 2022); the gamebook line has them. Parsed here to fill those gaps.
    w["gb_temp"] = pd.to_numeric(text.str.extract(r"temp:\s*(-?\d+)")[0], errors="coerce")
    w["gb_wind"] = pd.to_numeric(text.str.extract(r"wind:\D*?(\d+)\s*mph")[0], errors="coerce")
    w.loc[text.str.contains(r"wind:\s*calm"), "gb_wind"] = 0.0
    return w[["game_id", "weather", "precip", "snow", "gb_temp", "gb_wind"]]
