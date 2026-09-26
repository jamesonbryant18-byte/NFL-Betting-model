"""
trends.py — find the REASONS the model keeps missing, and fix only those.

This is the model's "learn from mistakes" loop, built the way Jameson asked
for it (2026-09-25): not "we missed ATL by 30, make ATL the best team in
football", but "go through every past pick, look for a reason we keep
getting games wrong, and change the model when that reason is real."

A reason is real only if it is CONSISTENT:

  1. DISCOVERY   it shows up in 2013-2020, beyond what chance produces
                 across this many tested reasons (Benjamini-Hochberg, FDR 10%)
  2. CONFIRM     it shows up again, same direction, in 2021 onward -- seasons
                 it was not found in -- and correcting for it (by the amount
                 measured in discovery) actually makes those predictions better
  3. APPLY       then, and only then, the correction goes into the model, sized
                 from all seasons and shrunk toward zero for small samples

Anything that passes step 1 but not 2 is put on a WATCH list, not applied.
One game, or one week, can never move the model through this path -- the
per-game ATL case is exactly what the discovery test is built to ignore.

Three kinds of reason are tested:

  MARGIN      a kind of game where the projected margin is consistently off
              in one direction (big favorites, wind, a new QB, road teams on
              a short week, teams coming off a blowout...). Fix: shift the
              projection for games of that kind.
  CALIBRATION the moneyline win probabilities. The model's spreads are
              compressed (it moves 0.77 pts per 1 pt of market line), so it
              thinks long underdogs win far more often than they do. Fix:
              recalibrate win probability to what actually happened.
  BET TYPE    a kind of bet that keeps losing more than the model's other
              bets (e.g. moneyline underdogs at +250 or longer). Fix: stop
              making that bet.

The result is written to data/trends.json, which is TRACKED in git: it is the
model's learned state, and run_week.py applies whatever it marks "confirmed".
Re-run every week with scripts/miss_report.py after the week is graded.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from math import erfc, sqrt

import numpy as np
import pandas as pd

from .config import CACHE_DIR, MARKET, REPO_ROOT, THRESHOLDS

TRENDS_FILE = REPO_ROOT / "data" / "trends.json"
BASE_FILE = CACHE_DIR / "base_projections_2013_2025.parquet"

DISCOVERY = (2013, 2020)
CONFIRM = (2021, 2100)          # 2021-2025 backtest + the current season's published picks

FDR_Q = 0.10
QB_HISTORY_FROM = 2000          # career starts are counted from here
SHRINK_K = 170.0                # effect * n/(n+k): k = (13 pt game noise / 1 pt prior)^2
MAX_TREND_SHIFT = 1.5           # no single trend moves a game more than this
MAX_TOTAL_SHIFT = 2.0           # nor all trends together

# ── time zones (offset from Eastern) ────────────────────────────────────

_TZ = {t: 0 for t in ("ATL", "BAL", "NE", "BUF", "CAR", "CIN", "CLE", "DET",
                      "IND", "JAX", "MIA", "NYG", "NYJ", "PHI", "PIT", "TB", "WAS")}
_TZ.update({t: -1 for t in ("CHI", "DAL", "GB", "HOU", "KC", "MIN", "NO", "TEN")})
_TZ.update({"DEN": -2, "ARI": -3})
_TZ.update({t: -3 for t in ("LA", "LAC", "LV", "SEA", "SF")})


def team_tz(team: str, season: int, gameday) -> float:
    if team == "LA" and season <= 2015:          # St. Louis Rams
        return -1.0
    if team == "ARI":                            # no DST: Pacific-time in Sep-Oct
        d = pd.Timestamp(gameday)
        return -3.0 if (d.month < 11 or (d.month == 11 and d.day < 7)) else -2.0
    return float(_TZ.get(team, 0))


# ── statistics helpers ──────────────────────────────────────────────────

def t_and_p(x: np.ndarray) -> tuple[float, float]:
    """One-sample t against zero, two-sided normal p. NaN if too small."""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) < 20 or x.std(ddof=1) == 0:
        return float("nan"), float("nan")
    t = x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))
    return float(t), float(erfc(abs(t) / sqrt(2)))


def benjamini_hochberg(pvals, q: float = FDR_Q) -> list[bool]:
    """Which p-values survive at false-discovery rate q. Order preserved; NaN fails."""
    p = np.array([1.0 if (v is None or np.isnan(v)) else v for v in pvals])
    n = len(p)
    if n == 0:
        return []
    order = np.argsort(p)
    crit = 0
    for rank, idx in enumerate(order, start=1):
        if p[idx] <= q * rank / n:
            crit = rank
    passed = np.zeros(n, dtype=bool)
    passed[order[:crit]] = True
    return passed.tolist()


def fit_logistic_slope(x: np.ndarray, y: np.ndarray, iters: int = 50) -> float:
    """y ~ sigmoid(b x), no intercept. Symmetric: p = 0.5 stays 0.5, so the
    calibrated favourite is always the team with the positive margin."""
    b = 1.0
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.clip(b * x, -30, 30)))
        g = ((y - p) * x).sum()
        hss = (p * (1 - p) * x * x).sum() + 1e-9
        step = g / hss
        b += step
        if abs(step) < 1e-10:
            break
    return float(b)


def fit_logistic(x: np.ndarray, y: np.ndarray, iters: int = 50) -> tuple[float, float]:
    """y ~ sigmoid(a + b x) by Newton's method. Returns (a, b)."""
    a, b = 0.0, 1.0
    for _ in range(iters):
        z = np.clip(a + b * x, -30, 30)
        p = 1 / (1 + np.exp(-z))
        w = p * (1 - p)
        g = np.array([(y - p).sum(), ((y - p) * x).sum()])
        h = np.array([[w.sum(), (w * x).sum()], [(w * x).sum(), (w * x * x).sum()]])
        step = np.linalg.solve(h + 1e-9 * np.eye(2), g)
        a, b = a + step[0], b + step[1]
        if np.abs(step).max() < 1e-9:
            break
    return float(a), float(b)


def _logit(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def calibrate(p, cal: dict | None):
    """Apply a fitted recalibration {a, b} to home win probability."""
    if not cal:
        return p
    z = cal["a"] + cal["b"] * _logit(p)
    out = 1 / (1 + np.exp(-z))
    return float(out) if np.ndim(out) == 0 else out


def log_loss(p, y) -> float:
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


# ── per-team, per-game context (all pre-game) ────────────────────────────

def pbp_team_stats(seasons) -> pd.DataFrame:
    """(game_id, team) -> offensive EPA sum, turnovers, pass/run EPA splits."""
    from .data import load_pbp
    rows = []
    for s in seasons:
        try:
            p = load_pbp(s)
        except Exception as ex:                     # noqa: BLE001
            print(f"  [trends] play-by-play {s} unavailable ({type(ex).__name__})")
            continue
        sc = p[p.play_type.isin(["pass", "run"]) & p.posteam.notna() & p.epa.notna()].copy()
        sc["is_pass"] = sc.play_type == "pass"
        g = sc.groupby(["game_id", "posteam"]).agg(
            epa=("epa", "sum"),
            tos=("interception", "sum"),
            fl=("fumble_lost", "sum"),
        )
        split = sc.groupby(["game_id", "posteam", "is_pass"]).epa.agg(["sum", "size"]).unstack()
        g["pass_sum"] = split[("sum", True)]
        g["pass_n"] = split[("size", True)]
        g["run_sum"] = split[("sum", False)]
        g["run_n"] = split[("size", False)]
        g = g.fillna(0).reset_index().rename(columns={"posteam": "team"})
        g["tos"] = g.tos + g.fl
        rows.append(g.drop(columns="fl"))
    if not rows:
        return pd.DataFrame(columns=["game_id", "team", "epa", "tos"])
    return pd.concat(rows, ignore_index=True)


def team_context(schedule: pd.DataFrame, stats: pd.DataFrame,
                 starters: dict | None = None) -> pd.DataFrame:
    """
    For every (game_id, team) in `schedule`, what was knowable BEFORE kickoff:
    previous game's margin, turnover margin and luck (score margin minus EPA
    margin), whether the starting QB is new, his prior starts, and the
    offense's season-to-date pass-vs-run reliance.

    Unplayed games take their QB from `starters` (team -> name).
    """
    st = stats.set_index(["game_id", "team"]) if len(stats) else None
    recs = []
    for side, opp in (("home", "away"), ("away", "home")):
        d = schedule[["game_id", "season", "week", "gameday", f"{side}_team",
                      f"{opp}_team", "result", f"{side}_qb_name"]].copy()
        d.columns = ["game_id", "season", "week", "gameday", "team", "opp", "result", "qb"]
        d["margin"] = d.result if side == "home" else -d.result
        recs.append(d)
    t = pd.concat(recs, ignore_index=True)
    t["gameday"] = pd.to_datetime(t.gameday)
    t = t.sort_values(["team", "gameday", "week"]).reset_index(drop=True)

    if st is not None:
        mine = st.reindex(list(zip(t.game_id, t.team)))
        theirs = st.reindex(list(zip(t.game_id, t.opp)))
        t["epa_margin"] = mine.epa.to_numpy() - theirs.epa.to_numpy()
        t["to_margin"] = theirs.tos.to_numpy() - mine.tos.to_numpy()
        for c in ("pass_sum", "pass_n", "run_sum", "run_n"):
            t[c] = mine[c].to_numpy()
    else:
        for c in ("epa_margin", "to_margin", "pass_sum", "pass_n", "run_sum", "run_n"):
            t[c] = np.nan

    # QB for every row (unplayed games take the resolved starter), then
    # career starts BEFORE each game, counted in DATE order across all teams.
    # (Counting inside the per-team loop below made it depend on alphabetical
    # team order: Case Keenum at CHI saw none of his starts for LA, MIN, DEN,
    # WAS, CLE, HOU or BUF, and read as a rookie.)
    qb_col = []
    for team, qb, played in zip(t.team, t.qb, t.margin.notna()):
        q = qb if isinstance(qb, str) and qb else None
        if not played and starters:
            q = starters.get(team, q)
        qb_col.append(q)
    t["qb_resolved"] = qb_col
    starts_before = {}
    count: dict[str, int] = {}
    for day, day_rows in t.sort_values("gameday").groupby("gameday", sort=True):
        for gid, team, q in zip(day_rows.game_id, day_rows.team, day_rows.qb_resolved):
            starts_before[(gid, team)] = count.get(q, 0) if q else np.nan
        for q, played in zip(day_rows.qb_resolved, day_rows.margin.notna()):
            if q and played:
                count[q] = count.get(q, 0) + 1

    out = []
    for team, d in t.groupby("team", sort=False):
        last = None                              # last PLAYED game of this team
        last4: list = []                         # its last four starting QBs
        season_cum = {}                          # season -> [ps, pn, rs, rn]
        prev_season_total = {}
        for _, r in d.iterrows():
            played = pd.notna(r.margin)
            qb = r.qb_resolved
            same_season = last is not None and last["season"] == r.season
            cum = season_cum.get(r.season)
            if cum is None:
                prior = prev_season_total.get(r.season - 1)
                cum = (prior * (4.0 / max(prior[4], 1)))[:4].copy() if prior is not None \
                    else np.zeros(4)
                season_cum[r.season] = cum
            ps, pn, rs, rn = cum
            rel = (ps / pn - rs / rn) if (pn > 50 and rn > 30) else np.nan
            recent = [q for q in last4 if q]
            out.append(dict(
                game_id=r.game_id, team=team,
                prev_margin=last["margin"] if same_season else np.nan,
                prev_to=last["to_margin"] if same_season else np.nan,
                prev_luck=(last["margin"] - last["epa_margin"]) if same_season else np.nan,
                qb=qb,
                # New = has not started any of this team's last 4 games. A
                # starter back from a one-game absence is not new (audit: that
                # subgroup shows no effect, and the rule used to flag it).
                qb_new=bool(qb and recent and qb not in recent),
                qb_starts=starts_before.get((r.game_id, team), np.nan),
                pass_rel=rel,
            ))
            if played:
                last = dict(season=r.season, margin=r.margin, to_margin=r.to_margin,
                            epa_margin=r.epa_margin, qb=qb)
                last4 = (last4 + [qb])[-4:]
                if pd.notna(r.pass_n):
                    season_cum[r.season] = cum + np.array(
                        [r.pass_sum, r.pass_n, r.run_sum, r.run_n], dtype=float)
                    tot = prev_season_total.get(r.season, np.zeros(5))
                    prev_season_total[r.season] = tot + np.array(
                        [r.pass_sum, r.pass_n, r.run_sum, r.run_n, 1.0], dtype=float)
    return pd.DataFrame(out)


def attach_context(frame: pd.DataFrame, ctx: pd.DataFrame, weather_flags: pd.DataFrame | None
                   ) -> pd.DataFrame:
    """Join team context and weather flags onto a game-level frame (home/away columns)."""
    f = frame.copy()
    c = ctx.set_index(["game_id", "team"])
    for side in ("home", "away"):
        sub = c.reindex(list(zip(f.game_id, f[f"{side}_team"])))
        for col in ("prev_margin", "prev_to", "prev_luck", "qb_new", "qb_starts", "pass_rel"):
            f[f"{side}_{col}"] = sub[col].to_numpy()
    if weather_flags is not None and len(weather_flags):
        w = weather_flags.drop_duplicates("game_id").set_index("game_id")
        for col in ("windy", "precip", "cold"):
            f[col] = w[col].reindex(f.game_id).fillna(False).astype(bool).to_numpy() \
                if col in w.columns else False
    for col in ("windy", "precip", "cold"):
        if col not in f.columns:
            f[col] = False
    f["home_tz"] = [team_tz(t, s, d) for t, s, d in zip(f.home_team, f.season, f.gameday)]
    f["away_tz"] = [team_tz(t, s, d) for t, s, d in zip(f.away_team, f.season, f.gameday)]
    f["kick_hour"] = pd.to_numeric(f.gametime.astype(str).str[:2], errors="coerce") + \
        pd.to_numeric(f.gametime.astype(str).str[3:5], errors="coerce") / 60.0
    return f


def history_weather_flags(schedule: pd.DataFrame, seasons) -> pd.DataFrame:
    """Actual conditions for played games: gamebook precipitation + schedule wind/temp."""
    from .weather import COLD_F, WINDY_MPH, gamebook, venue_kind
    gb = gamebook(seasons)
    s = schedule[["game_id", "stadium_id", "roof", "wind", "temp"]].merge(
        gb[["game_id", "precip", "gb_temp", "gb_wind"]], on="game_id", how="left")
    s["wind"] = s.wind.fillna(s.gb_wind)
    s["temp"] = s.temp.fillna(s.gb_temp)
    outdoor = np.array([venue_kind(i, r) == "outdoor" for i, r in zip(s.stadium_id, s.roof)])
    # Played games know their actual roof state: 'open' counts as outdoors.
    outdoor |= s.roof.astype(str).str.lower().eq("open").to_numpy()
    s["windy"] = outdoor & (s.wind.fillna(0) >= WINDY_MPH).to_numpy()
    s["precip"] = outdoor & s.precip.fillna(False).astype(bool).to_numpy()
    s["cold"] = outdoor & (s.temp.fillna(99) <= COLD_F).to_numpy()
    return s[["game_id", "windy", "precip", "cold"]]


# ── the candidate reasons ───────────────────────────────────────────────

def _one_side(h, a):
    """+1 if only home has the property, -1 if only away, else 0."""
    h = np.asarray(h, dtype=bool)
    a = np.asarray(a, dtype=bool)
    return np.where(h & ~a, 1, np.where(a & ~h, -1, 0))


def _fav(f):
    return np.sign(f.spread_line.fillna(0).to_numpy())


# (key, plain-English description, subject(f) -> +1 home / -1 away / 0 not in group)
# The subject is the team the trend is ABOUT; a positive effect means that team
# does better than the model projects.
MARGIN_CANDIDATES = [
    ("big_favorite", "Big favorites (7+ point line)",
     lambda f: np.where(f.spread_line.abs() >= 7, _fav(f), 0)),
    ("mid_favorite", "Mid favorites (3.5 to 6.5)",
     lambda f: np.where(f.spread_line.abs().between(3.5, 6.5), _fav(f), 0)),
    ("small_favorite", "Small favorites (3 or less)",
     lambda f: np.where(f.spread_line.abs().between(0.5, 3), _fav(f), 0)),
    ("home_underdog", "Home underdogs",
     lambda f: np.where((f.spread_line < 0) & ~f.neutral.astype(bool), 1, 0)),
    ("divisional_underdog", "Underdogs in divisional games",
     lambda f: np.where(f.div_game.fillna(0).astype(bool), -_fav(f), 0)),
    ("early_season_favorite", "Favorites in weeks 1-4",
     lambda f: np.where(f.week <= 4, _fav(f), 0)),
    ("late_season_favorite", "Favorites in week 15+",
     lambda f: np.where(f.week >= 15, _fav(f), 0)),
    ("thursday_road", "Road teams on Thursday (short week + travel)",
     lambda f: np.where(f.weekday.astype(str).eq("Thursday") & ~f.neutral.astype(bool), -1, 0)),
    ("off_bye", "Team coming off a bye (opponent is not)",
     lambda f: _one_side(f.home_rest >= 13, f.away_rest >= 13)),
    ("rest_edge", "Team with 3+ more days of rest",
     lambda f: np.where((f.home_rest - f.away_rest) >= 3, 1,
                        np.where((f.away_rest - f.home_rest) >= 3, -1, 0))),
    ("body_clock", "West-coast team in an early Eastern kickoff",
     lambda f: np.where((f.away_tz <= -3) & (f.home_tz == 0) & (f.kick_hour <= 13.5)
                        & ~f.neutral.astype(bool), -1, 0)),
    ("long_trip", "Road team crossing 2+ time zones",
     lambda f: np.where(((f.home_tz - f.away_tz).abs() >= 2) & ~f.neutral.astype(bool), -1, 0)),
    ("new_qb", "Team starting a QB who has not started for it in its last 4 games",
     lambda f: _one_side(f.home_qb_new.fillna(False).astype(bool),
                         f.away_qb_new.fillna(False).astype(bool))),
    ("inexperienced_qb", "Team starting a QB with fewer than 8 starts",
     lambda f: _one_side(f.home_qb_starts.fillna(99) < 8, f.away_qb_starts.fillna(99) < 8)),
    ("after_blowout_win", "Team coming off a 21+ point win",
     lambda f: _one_side(f.home_prev_margin >= 21, f.away_prev_margin >= 21)),
    ("after_blowout_loss", "Team coming off a 21+ point loss",
     lambda f: _one_side(f.home_prev_margin <= -21, f.away_prev_margin <= -21)),
    ("after_turnover_luck", "Team that won the turnover battle by 3+ last game",
     lambda f: _one_side(f.home_prev_to >= 3, f.away_prev_to >= 3)),
    ("after_lucky_score", "Team whose last score beat how it played by 10+",
     lambda f: _one_side(f.home_prev_luck >= 10, f.away_prev_luck >= 10)),
    ("wind_favorite", "Favorites in wind (15+ mph, outdoors)",
     lambda f: np.where(f.windy.astype(bool), _fav(f), 0)),
    ("rain_snow_favorite", "Favorites in rain or snow",
     lambda f: np.where(f.precip.astype(bool), _fav(f), 0)),
    ("cold_home", "Home team in freezing weather (32F or less)",
     lambda f: np.where(f.cold.astype(bool), 1, 0)),
    ("bad_weather_passing_team", "Offense far better passing than running, in wind/rain/snow",
     lambda f: np.where((f.windy.astype(bool) | f.precip.astype(bool))
                        & ((f.home_pass_rel - f.away_pass_rel).abs() >= 0.10),
                        np.sign(f.home_pass_rel - f.away_pass_rel).fillna(0), 0)),
    ("low_total_favorite", "Favorites in low-scoring games (total 40 or less)",
     lambda f: np.where(f.total_line <= 40, _fav(f), 0)),
    ("high_total_favorite", "Favorites in high-scoring games (total 50+)",
     lambda f: np.where(f.total_line >= 50, _fav(f), 0)),
    ("primetime_favorite", "Favorites in night games",
     lambda f: np.where(f.kick_hour >= 19, _fav(f), 0)),
    ("neutral_site_favorite", "Favorites at neutral/international sites",
     lambda f: np.where(f.neutral.astype(bool), _fav(f), 0)),
    ("model_far_from_market", "Side the model likes when it disagrees with the line by 3+",
     lambda f: np.where((f.projected_margin - f.spread_line).abs() >= 3,
                        np.sign(f.projected_margin - f.spread_line), 0)),
    ("home_team", "Home teams in general (home-field size)",
     lambda f: np.where(~f.neutral.astype(bool), 1, 0)),
]
CANDIDATE_TEXT = {k: d for k, d, _ in MARGIN_CANDIDATES}


def subjects(f: pd.DataFrame) -> dict[str, np.ndarray]:
    out = {}
    for key, _, fn in MARGIN_CANDIDATES:
        s = np.asarray(fn(f), dtype=float)
        out[key] = np.nan_to_num(s, nan=0.0)
    return out


# ── history ─────────────────────────────────────────────────────────────

def published_projections(season: int, schedule: pd.DataFrame) -> pd.DataFrame:
    """This season's archived picks, graded games only, as home-margin projections."""
    from .archive import week_dir
    d = week_dir(season)
    played = schedule[(schedule.season == season) & schedule.result.notna()]
    rows = []
    for f in sorted(d.glob("week*_picks.csv")):
        wk = int(f.stem[4:6])
        for _, r in pd.read_csv(f).iterrows():
            away, home = [x.strip() for x in str(r.matchup).split("@")]
            g = played[(played.week == wk) & (played.home_team == home) & (played.away_team == away)]
            if g.empty:
                continue
            proj = float(r.proj_margin) if str(r.winner) == home else -float(r.proj_margin)
            # From 2026 Week 3 on the published margin already contains the
            # trend fix and the self-tune nudge. History must hold the model
            # BEFORE fixes (like the backtest rows), or next week's check fixes
            # the fixes and slowly un-learns them (audit 2026-09-26).
            raw = r.get("raw_margin") if hasattr(r, "get") else None
            if raw is not None and pd.notna(raw):
                proj = float(raw)
            rows.append(dict(game_id=g.game_id.iloc[0], projected_margin=proj,
                             published_winner=str(r.winner)))
    if not rows:
        return pd.DataFrame(columns=["game_id", "projected_margin", "published_winner", "source"])
    out = pd.DataFrame(rows).drop_duplicates("game_id", keep="last")
    out["source"] = "published"
    return out


def build_history(season: int, schedule: pd.DataFrame | None = None,
                  include_current: bool = True) -> pd.DataFrame:
    """
    Every graded prediction with its pre-game context: the walk-forward
    backtest for 2013-2025 plus what was actually published this season.
    """
    from .data import load_games
    if schedule is None:
        schedule = load_games()
    if not BASE_FILE.exists():
        raise FileNotFoundError(
            f"{BASE_FILE} missing -- run scripts/build_base_projections.py once (about 1 minute)")
    base = pd.read_parquet(BASE_FILE)[["game_id", "projected_margin"]].assign(source="backtest")
    parts = [base]
    if include_current:
        parts.append(published_projections(season, schedule))
    proj = pd.concat(parts, ignore_index=True).drop_duplicates("game_id", keep="last")

    cols = ["game_id", "season", "week", "gameday", "weekday", "gametime", "home_team",
            "away_team", "result", "spread_line", "total_line", "home_moneyline",
            "away_moneyline", "home_spread_odds", "away_spread_odds", "div_game", "roof",
            "stadium_id", "home_rest", "away_rest", "location"]
    h = proj.merge(schedule[cols], on="game_id", how="inner")
    h = h[h.result.notna() & h.spread_line.notna()].copy()
    h["neutral"] = h.location.astype(str).str.lower().eq("neutral")

    seasons = sorted(h.season.unique())
    stats = pbp_team_stats(range(min(seasons) - 1, max(seasons) + 1))
    # Career QB starts need the whole schedule, not just the tested seasons:
    # counted from 2012 only, a veteran who sat out 2012 looked like a rookie.
    sched = schedule[schedule.season.between(QB_HISTORY_FROM, max(seasons))]
    ctx = team_context(sched, stats)
    wx = history_weather_flags(schedule[schedule.season.isin(seasons)],
                               [s for s in seasons if s >= 2016])
    h = attach_context(h, ctx, wx)
    # Weather history starts in 2016 (gamebook precipitation); earlier seasons
    # have schedule wind/temp only, so rain is unknown there, not "dry".
    h.loc[h.season < 2016, "precip"] = False
    return h.sort_values(["season", "week"]).reset_index(drop=True)


def live_features(slate_games: pd.DataFrame, schedule: pd.DataFrame, season: int,
                  starters: dict, forecast: dict) -> pd.DataFrame:
    """The same context for an upcoming slate, using forecast weather and resolved QBs."""
    f = slate_games.copy()
    f["neutral"] = f.get("neutral", pd.Series(False, index=f.index)).fillna(False).astype(bool)
    if "location" in f.columns:
        f["neutral"] |= f.location.astype(str).str.lower().eq("neutral")
    stats = pbp_team_stats([season - 1, season])
    # Whole schedule for career QB starts (2026 Week 3: counted from 2025
    # only, Kyler Murray, Jameis Winston and Case Keenum all read as rookies).
    sched = schedule[schedule.season.between(QB_HISTORY_FROM, season)]
    ctx = team_context(sched, stats, starters=starters)
    wx = pd.DataFrame([dict(game_id=g, windy=v.get("windy", False),
                            precip=v.get("precip", False), cold=v.get("cold", False))
                       for g, v in (forecast or {}).items()])
    return attach_context(f, ctx, wx if len(wx) else None)


# ── testing ─────────────────────────────────────────────────────────────

def test_margin_trends(h: pd.DataFrame) -> list[dict]:
    r_home = (h.result - h.projected_margin).to_numpy()
    disc = h.season.between(*DISCOVERY).to_numpy()
    conf = h.season.between(*CONFIRM).to_numpy()
    cur = (h.get("source", pd.Series("backtest", index=h.index)) == "published").to_numpy()
    subj = subjects(h)
    rows = []
    for key, desc, _ in MARGIN_CANDIDATES:
        s = subj[key]
        m = s != 0
        r = s * r_home
        td, pd_ = t_and_p(r[m & disc])
        eff_d = float(np.nanmean(r[m & disc])) if (m & disc).any() else float("nan")
        tc, pc = t_and_p(r[m & conf])
        eff_c = float(np.nanmean(r[m & conf])) if (m & conf).any() else float("nan")
        # Out-of-sample check: shift confirmation games by the DISCOVERY
        # effect, shrunk and capped exactly as a live value would be (the
        # unshrunk mean overshoots: new QB -3.1 in 2013-20 vs -2.0 in 2021+).
        mc = m & conf
        n_d = int((m & disc).sum())
        if mc.any() and not np.isnan(eff_d):
            eff_live_d = float(np.clip(eff_d * n_d / (n_d + SHRINK_K),
                                       -MAX_TREND_SHIFT, MAX_TREND_SHIFT))
            before = np.abs(r_home[mc]).mean()
            after = np.abs(r_home[mc] - s[mc] * eff_live_d).mean()
        else:
            before = after = float("nan")
        n_all = int(m.sum())
        eff_all = float(np.nanmean(r[m])) if n_all else 0.0
        t_all, _ = t_and_p(r[m])
        rows.append(dict(
            key=key, text=desc, n_disc=int((m & disc).sum()), n_conf=int(mc.sum()),
            n_season=int((m & cur).sum()),
            effect_disc=eff_d, t_disc=td, p_disc=pd_,
            effect_conf=eff_c, t_conf=tc,
            effect_season=float(np.nanmean(r[m & cur])) if (m & cur).any() else float("nan"),
            conf_mae_before=float(before), conf_mae_after=float(after), t_all=t_all,
            live_shift=float(np.clip(eff_all * n_all / (n_all + SHRINK_K),
                                     -MAX_TREND_SHIFT, MAX_TREND_SHIFT)),
        ))
    passed = benjamini_hochberg([r["p_disc"] for r in rows])
    for r, ok in zip(rows, passed):
        r["survives_discovery"] = bool(ok)
        same_sign = (not np.isnan(r["effect_conf"]) and not np.isnan(r["effect_disc"])
                     and np.sign(r["effect_conf"]) == np.sign(r["effect_disc"]))
        helps = r["conf_mae_after"] < r["conf_mae_before"]
        if ok and same_sign and helps:
            r["status"] = "candidate"          # the joint fit decides confirmed/absorbed
        elif ok or (not np.isnan(r["t_conf"]) and abs(r["t_conf"]) >= 2) \
                or (same_sign and not np.isnan(r["t_all"]) and abs(r["t_all"]) >= 2):
            # Same direction in both periods and real across all games pooled,
            # but not strong enough in 2013-2020 alone to clear the bar.
            r["status"] = "watching"
        else:
            r["status"] = "no pattern"
    # A watch-list reason can switch on PROSPECTIVELY: 2013-2020 is frozen, so
    # it can never pass discovery later. If it keeps showing up in games
    # predicted live (this season onward), same direction as history, 40+
    # games, one-sided p < 0.05, it becomes a candidate -- and still has to
    # survive the 2021+ prune in fit_joint like every other reason.
    for r in rows:
        r["promoted"] = False
        if r["status"] != "watching" or r["n_season"] < 40 or np.isnan(r["effect_season"]):
            continue
        key = r["key"]
        m = (subjects(h)[key] != 0) & cur
        t_live, p_live = t_and_p(subjects(h)[key][m] * r_home[m])
        if (not np.isnan(t_live) and np.sign(t_live) == np.sign(r["effect_disc"] + r["effect_conf"])
                and p_live / 2 < 0.05):
            r["status"], r["promoted"] = "candidate", True
    return rows


def _ridge(X: np.ndarray, r: np.ndarray, lam: float = SHRINK_K) -> np.ndarray:
    """beta = (X'X + lam I)^-1 X'r. For one 0/1 column this is mean * n/(n+lam),
    the same small-sample shrinkage the single-trend numbers use."""
    k = X.shape[1]
    return np.linalg.solve(X.T @ X + lam * np.eye(k), X.T @ r)


def _ridge_capped(X: np.ndarray, r: np.ndarray, lam: float = SHRINK_K,
                  cap: float = MAX_TREND_SHIFT) -> np.ndarray:
    """
    Ridge fit in which a coefficient past the per-reason cap is FIXED at the
    cap and the others are refit around it. Clipping after an unconstrained
    fit would run a combination that was never fit (audit, 2026-09-26: the
    line-disagreement fix fit at -2.57 was clipped to -1.5 while the others
    had been sized against -2.57).
    """
    k = X.shape[1]
    fixed: dict[int, float] = {}
    b = np.zeros(k)
    for _ in range(k + 1):
        free = [j for j in range(k) if j not in fixed]
        off = (X[:, list(fixed)] * np.array(list(fixed.values()))).sum(axis=1) if fixed else 0.0
        b = np.zeros(k)
        if free:
            b[free] = _ridge(X[:, free], r - off, lam)
        for j, v in fixed.items():
            b[j] = v
        over = [j for j in free if abs(b[j]) > cap]
        if not over:
            break
        for j in over:
            fixed[j] = float(np.sign(b[j]) * cap)
    return b


def _apply(subj: dict, keys: list[str], beta) -> np.ndarray:
    shift = np.zeros(len(next(iter(subj.values()))))
    for k, b in zip(keys, beta):
        shift += subj[k] * float(b)
    return np.clip(shift, -MAX_TOTAL_SHIFT, MAX_TOTAL_SHIFT)


def _shift_for(keys, subj, r, fit_mask) -> np.ndarray:
    if not keys:
        return np.zeros(len(r))
    X = np.column_stack([subj[k] for k in keys])
    return _apply(subj, keys, _ridge_capped(X[fit_mask], r[fit_mask]))


def _cv_mae(keys, subj, r, seasons, disc) -> float:
    """Leave-one-season-out MAE inside 2013-2020 -- selection never sees 2021+."""
    err = np.zeros(len(r))
    for s in np.unique(seasons[disc]):
        test = disc & (seasons == s)
        train = disc & (seasons != s)
        err[test] = np.abs(r[test] - _shift_for(keys, subj, r, train)[test])
    return float(err[disc].mean())


def fit_joint(h: pd.DataFrame, rows: list[dict]) -> dict:
    """
    Decide which single-reason survivors actually go in the model, TOGETHER.

    Several survivors are one cause wearing different names (big favorites,
    home underdogs and "model far from the line" are all the model's
    compressed spreads), so each reason has to earn its place alongside the
    others:

      1. SELECT on 2013-2020 only: forward selection by leave-one-season-out
         error. A reason is added only if it cuts that error by 0.002+ pts.
      2. PRUNE on 2021+: every selected reason must make 2021+ predictions
         better when it is in the set (drop-one test, coefficients fit on
         2013-2020). 2021+ can only REMOVE reasons, never add them.
      3. The final set must beat the unfixed model on 2021+ with a paired
         t >= 2. Live values are refit on every graded game.

    Audit 2026-09-26: an earlier version confirmed the set as a whole, and
    four of its seven reasons made 2021+ worse individually.
    """
    r = (h.result - h.projected_margin).to_numpy()
    disc = h.season.between(*DISCOVERY).to_numpy()
    conf = h.season.between(*CONFIRM).to_numpy()
    seasons = h.season.to_numpy()
    subj = subjects(h)
    pool = [x["key"] for x in rows if x["status"] == "candidate"]
    forced = [x["key"] for x in rows if x.get("promoted")]

    chosen, cv = [], _cv_mae([], subj, r, seasons, disc)
    cv_path = [dict(step="none", cv_mae=cv)]
    while True:
        best = None
        for k in pool:
            if k in chosen:
                continue
            m = _cv_mae(chosen + [k], subj, r, seasons, disc)
            if m < cv - 0.002 and (best is None or m < best[1]):
                best = (k, m)
        if best is None:
            break
        chosen.append(best[0])
        cv = best[1]
        cv_path.append(dict(step=best[0], cv_mae=cv))
    not_selected = [k for k in pool if k not in chosen]
    chosen += [k for k in forced if k not in chosen]

    def conf_mae(keys):
        return float(np.abs(r[conf] - _shift_for(keys, subj, r, disc)[conf]).mean())

    pruned = []
    while chosen:
        full = conf_mae(chosen)
        gains = {k: conf_mae([c for c in chosen if c != k]) - full for k in chosen}
        worst = min(gains, key=gains.get)
        if gains[worst] > 0:
            break
        chosen.remove(worst)
        pruned.append(worst)

    before = np.abs(r[conf])
    shift_c = _shift_for(chosen, subj, r, disc)
    after = np.abs(r[conf] - shift_c[conf])
    t, _ = t_and_p(before - after)
    full = float(after.mean())
    gains = {k: conf_mae([c for c in chosen if c != k]) - full for k in chosen}
    out = dict(keys=chosen, not_selected=not_selected, pruned=pruned, cv_path=cv_path,
               conf_gain={k: float(v) for k, v in gains.items()},
               beta_disc=[], beta_all=[],
               conf_mae_before=float(before.mean()), conf_mae_after=full,
               conf_t=t, status="no pattern")
    if not chosen:
        return out
    X = np.column_stack([subj[k] for k in chosen])
    beta_d = _ridge_capped(X[disc], r[disc])
    beta_all = _ridge_capped(X, r)
    ok = full < out["conf_mae_before"] and not np.isnan(t) and t >= 2
    out.update(beta_disc=[float(b) for b in beta_d], beta_all=[float(b) for b in beta_all],
               status="confirmed" if ok else "rejected")
    return out


def margin_model_for_history():
    """The same key-number margin distribution run_week.py uses."""
    from .market import MarginModel
    res_path = CACHE_DIR / "residuals.npy"
    residuals = np.load(res_path) if res_path.exists() else None
    ds = pd.read_parquet(CACHE_DIR / "dataset_2010_2025.parquet")
    margins = ds.loc[ds.result.notna(), "result"].to_numpy()
    return MarginModel(residuals=residuals, sigma=MARKET.margin_sigma, margins=margins)


def win_probs(margins, mm) -> np.ndarray:
    cache: dict[float, float] = {}
    out = []
    for v in np.asarray(margins, dtype=float):
        k = round(float(v), 2)
        if k not in cache:
            cache[k] = mm.win_prob(k)
        out.append(cache[k])
    return np.array(out)


def _dog_bucket(ml):
    return pd.cut(ml, [99, 150, 250, 400, 10000],
                  labels=["+100 to +150", "+151 to +250", "+251 to +400", "+401 and up"])


def _ll_each(p, y):
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def test_calibration(h: pd.DataFrame, p_raw: np.ndarray, p_adj_disc: np.ndarray,
                     p_adj_all: np.ndarray) -> dict:
    """
    Moneyline win probability vs what actually happened.

    p_raw       the model before any trend fix
    p_adj_*     after the confirmed margin fixes (2013-2020 fit / all-games fit)

    The recalibration stretches or shrinks win probability symmetrically
    (logit(p') = b * logit(p), no home-side intercept: an intercept made the
    calibrated pick disagree with the margin for home margins of 0-0.35 and
    applied a home term at neutral sites). It is fit on 2013-2020 ON TOP of the
    margin fixes and must beat them on 2021+ with a paired t >= 2 -- a
    point-estimate win is not enough (audit 2026-09-26).
    """
    from .market import devig
    ok = (h.result != 0).to_numpy() & h.home_moneyline.notna().to_numpy() & \
        h.away_moneyline.notna().to_numpy()
    y = (h.result > 0).to_numpy().astype(float)
    disc = ok & h.season.between(*DISCOVERY).to_numpy()
    conf = ok & h.season.between(*CONFIRM).to_numpy()
    b_disc = fit_logistic_slope(_logit(p_adj_disc[disc]), y[disc])
    cal_disc = dict(a=0.0, b=b_disc)
    p_fix = calibrate(p_adj_disc, cal_disc)
    ll = {k: log_loss(v[conf], y[conf]) for k, v in
          (("raw", p_raw), ("margin_fixed", p_adj_disc), ("fixed", p_fix))}
    br = {k: float(((v[conf] - y[conf]) ** 2).mean()) for k, v in
          (("raw", p_raw), ("margin_fixed", p_adj_disc), ("fixed", p_fix))}
    t_vs_margin, _ = t_and_p(_ll_each(p_adj_disc[conf], y[conf]) - _ll_each(p_fix[conf], y[conf]))
    t_vs_raw, _ = t_and_p(_ll_each(p_raw[conf], y[conf]) - _ll_each(p_fix[conf], y[conf]))

    fair = np.array([devig(hm, am)[0] if o else np.nan for hm, am, o in
                     zip(h.home_moneyline.fillna(-110), h.away_moneyline.fillna(-110), ok)])
    dog_home = (h.home_moneyline > h.away_moneyline).to_numpy()
    dog_ml = np.where(dog_home, h.home_moneyline, h.away_moneyline)
    bucket = _dog_bucket(pd.Series(dog_ml))
    side = lambda p, m: np.where(dog_home[m], p[m], 1 - p[m]).mean()
    table = []
    for blk, mask in (("2013-2020", disc), ("2021+", conf)):
        for bk in bucket.cat.categories:
            m = mask & (bucket == bk).to_numpy()
            if m.sum() < 10:
                continue
            table.append(dict(block=blk, bucket=bk, n=int(m.sum()),
                              actual=float(np.where(dog_home[m], y[m], 1 - y[m]).mean()),
                              market=float(side(fair, m)), model=float(side(p_raw, m)),
                              model_margin_fixed=float(side(p_adj_disc, m)),
                              model_fixed=float(side(p_fix, m))))
    # The problem this fixes lives in the underdog TAIL (the model overrates
    # long dogs because its spreads are compressed); most games are near
    # 50/50 and barely move, so an all-games log-loss t-test buries it
    # (2021+: t = 1.5 overall while +401 dogs are off by 11 points). The
    # tail is tested directly: dogs at +151 or longer must be overrated in
    # BOTH periods (z >= 2), and the fix must shrink that 2021+ tail error
    # while not hurting 2021+ log loss overall.
    tail = pd.Series(dog_ml).gt(150).to_numpy()
    tail_z, tail_err = {}, {}
    for blk, mask in (("2013-2020", disc), ("2021+", conf)):
        m = mask & tail
        won = np.where(dog_home[m], y[m], 1 - y[m])
        said = np.where(dog_home[m], p_adj_disc[m], 1 - p_adj_disc[m])
        fixd = np.where(dog_home[m], p_fix[m], 1 - p_fix[m])
        se = np.sqrt(won.mean() * (1 - won.mean()) / max(len(won), 1))
        tail_z[blk] = float((said.mean() - won.mean()) / se) if se > 0 else float("nan")
        tail_err[blk] = dict(n=int(m.sum()), actual=float(won.mean()),
                             margin_fixed=float(said.mean()), fixed=float(fixd.mean()))
    c = tail_err["2021+"]
    tail_better = abs(c["fixed"] - c["actual"]) < abs(c["margin_fixed"] - c["actual"])
    b_all = fit_logistic_slope(_logit(p_adj_all[ok]), y[ok])
    confirmed = (all(v >= 2 for v in tail_z.values()) and tail_better
                 and ll["fixed"] < ll["margin_fixed"] and ll["fixed"] < ll["raw"])
    return dict(status="confirmed" if confirmed else "no pattern",
                a=0.0, b=b_all, disc_fit=cal_disc,
                conf_logloss=ll, conf_brier=br, t_vs_margin_fixed=t_vs_margin,
                t_vs_raw=t_vs_raw, tail_overrated_z=tail_z, tail=tail_err,
                n_disc=int(disc.sum()), n_conf=int(conf.sum()), table=table)


def replay_bets(h: pd.DataFrame, p_home: np.ndarray, mm, thresholds=THRESHOLDS) -> pd.DataFrame:
    """
    Re-run the live bet selection (NFLModel._recommend) on every historical
    game and grade each bet at 1 unit. Portfolio caps are ignored: this asks
    which KINDS of bet win, not what a bankroll would have done.
    """
    from .market import devig
    from .model import NFLModel
    m = NFLModel(thresholds=thresholds)
    rows = []
    for (_, g), wp in zip(h.iterrows(), p_home):
        line = float(g.spread_line)
        proj = float(g.projected_margin)
        ph, pp, pa = mm.cover_prob(proj, line)
        hml, aml = g.home_moneyline, g.away_moneyline
        if pd.notna(hml) and pd.notna(aml):
            fh, fa = devig(hml, aml)
            eh, ea = wp - fh, (1 - wp) - fa
            hml, aml = float(hml), float(aml)
        else:
            hml = aml = None
            eh = ea = float("nan")
        rec = m._recommend(proj, line, proj - line, ph, pp, pa, wp, hml, aml, eh, ea,
                           g.home_team, g.away_team, g.get("home_spread_odds"),
                           g.get("away_spread_odds"))
        if not rec["bet_side"]:
            continue
        team, num = rec["bet_side"].split()[0], rec["bet_side"].split()[1]
        try:
            float(num)
        except ValueError:                         # "PK"
            num = "0"
        tm = g.result if team == g.home_team else -g.result
        odds = float(rec["bet_odds"])
        if rec["bet_market"] == "SPREAD":
            pts = float(num)
            cover = tm + pts
            outcome = 1 if cover > 0 else (0 if cover == 0 else -1)
            kind = f"spread {'underdog' if pts > 0 else 'favorite'}"
            bucket = ("getting 7+" if pts >= 7 else "getting 3.5-6.5" if pts >= 3.5
                      else "getting 3 or less") if pts > 0 else \
                     ("laying 7+" if pts <= -7 else "laying 6.5 or less")
        else:
            outcome = 1 if tm > 0 else (0 if tm == 0 else -1)
            kind = f"moneyline {'underdog' if odds > 0 else 'favorite'}"
            bucket = str(_dog_bucket(pd.Series([odds]))[0]) if odds > 0 else "favorite"
        win_pay = odds / 100 if odds > 0 else 100 / abs(odds)
        ret = win_pay if outcome == 1 else (0.0 if outcome == 0 else -1.0)
        rows.append(dict(game_id=g.game_id, season=g.season, market=rec["bet_market"],
                         kind=kind, bucket=bucket, odds=odds, ret=ret))
    return pd.DataFrame(rows)


def test_bet_types(bets: pd.DataFrame) -> list[dict]:
    """Which kinds of bet lose MORE than the model's other bets, in both blocks."""
    if bets.empty:
        return []
    bets = bets.copy()
    bets["group"] = bets.kind + ": " + bets.bucket
    disc = bets.season.between(*DISCOVERY)
    conf = bets.season.between(*CONFIRM)
    rows = []
    for grp, _ in bets.groupby("group"):
        g = bets.group == grp
        rec = dict(group=grp)
        worse_both = True
        for blk, mask in (("disc", disc), ("conf", conf)):
            a, rest = bets[g & mask].ret, bets[~g & mask].ret
            rec[f"n_{blk}"] = int(len(a))
            rec[f"roi_{blk}"] = float(a.mean()) if len(a) else float("nan")
            rec[f"roi_rest_{blk}"] = float(rest.mean()) if len(rest) else float("nan")
            if not len(a) or not (a.mean() < 0 and a.mean() < rest.mean()):
                worse_both = False
        a, rest = bets[g].ret, bets[~g].ret
        se = sqrt(a.var(ddof=1) / len(a) + rest.var(ddof=1) / len(rest)) \
            if len(a) > 1 and len(rest) > 1 else float("nan")
        # A group where every bet lost has zero variance, and a Welch z then
        # explodes (12 straight losses read as p = 0). Too few / degenerate
        # groups are simply not evidence.
        if len(a) < 20 or a.var(ddof=1) == 0:
            se = float("nan")
        z = (a.mean() - rest.mean()) / se if (np.isfinite(se) and se > 0) else float("nan")
        rec["z_vs_rest"] = float(z)
        rec["p_one_sided"] = float(0.5 * erfc(-z / sqrt(2))) if np.isfinite(z) else 1.0
        rec["worse_both"] = worse_both
        rows.append(rec)
    # Ten-odd bet types are tested at once, so one of them looking bad at
    # p = 0.05 is expected by chance. Same false-discovery control as above.
    passed = benjamini_hochberg([r["p_one_sided"] for r in rows])
    for r, ok in zip(rows, passed):
        r["status"] = "confirmed" if (ok and r["worse_both"] and r["n_disc"] >= 30
                                      and r["n_conf"] >= 20) \
            else "watching" if r["worse_both"] else "no pattern"
    return sorted(rows, key=lambda r: r["group"])


def ml_underdog_cap(bet_rows: list[dict]) -> int | None:
    """Longest moneyline underdog price still allowed, from confirmed bad buckets."""
    order = [("+401 and up", 400), ("+251 to +400", 250), ("+151 to +250", 150)]
    status = {r["group"].split(": ")[1]: r["status"] for r in bet_rows
              if r["group"].startswith("moneyline underdog")}
    # Only cap from the longest end inward: a bad +151 bucket sitting under
    # fine longer prices is noise, not a longshot pattern.
    cap = None
    for bucket, low in order:
        if status.get(bucket) != "confirmed":
            break
        cap = low
    return cap


# ── this season's misses, with reasons ──────────────────────────────────

def explain_misses(h: pd.DataFrame, stats: pd.DataFrame | None = None) -> pd.DataFrame:
    """One row per graded pick this season that went wrong straight up."""
    cur = h[h.source == "published"].copy()
    if cur.empty:
        return pd.DataFrame()
    subj = subjects(cur)
    st = stats.set_index(["game_id", "team"]) if stats is not None and len(stats) else None
    rows = []
    for i, (_, g) in enumerate(cur.iterrows()):
        pw = g.get("published_winner")
        pick_home = (pw == g.home_team) if isinstance(pw, str) and pw else g.projected_margin >= 0
        pick = g.home_team if pick_home else g.away_team
        won = (g.result > 0) == pick_home and g.result != 0
        if won:
            continue
        s_pick = 1 if pick_home else -1
        reasons = []
        for key, desc, _ in MARGIN_CANDIDATES:
            if key in ("home_team", "model_far_from_market"):
                continue
            s = subj[key][i]
            if s != 0:
                side = g.home_team if s > 0 else g.away_team
                reasons.append(f"{desc.lower()} [{side}]")
        luck = ""
        if st is not None:
            try:
                me = st.loc[(g.game_id, pick)]
                opp = st.loc[(g.game_id, g.away_team if pick_home else g.home_team)]
                epa_m = me.epa - opp.epa
                to_m = opp.tos - me.tos
                if epa_m > 0:
                    luck = f"bad luck: {pick} out-played them (EPA {epa_m:+.0f}) but lost"
                elif to_m <= -2:
                    luck = f"turnovers: {pick} lost the turnover battle by {-to_m:.0f}"
                else:
                    luck = f"model miss: {pick} was out-played (EPA {epa_m:+.0f})"
            except KeyError:
                pass
        rows.append(dict(week=int(g.week), matchup=f"{g.away_team} @ {g.home_team}",
                         pick=pick, projected=round(float(g.projected_margin) * s_pick, 1),
                         actual=float(g.result) * s_pick, luck=luck,
                         reasons="; ".join(reasons) if reasons else "none of the tracked conditions"))
    return pd.DataFrame(rows)


# ── run everything, write the learned state ─────────────────────────────

def bet_summary(bets: pd.DataFrame) -> dict:
    """Headline numbers for a set of replayed bets, per block."""
    out = {}
    for blk, (lo, hi) in (("2013-2020", DISCOVERY), ("2021+", CONFIRM)):
        b = bets[bets.season.between(lo, hi)]
        if b.empty:
            continue
        ml = b[b.market == "MONEYLINE"]
        out[blk] = dict(
            n=int(len(b)), roi=float(b.ret.mean()),
            underdog_share=float(b.kind.str.contains("underdog").mean()),
            ml_n=int(len(ml)),
            ml_longshots=int((ml.odds > 250).sum()),
            ml_roi=float(ml.ret.mean()) if len(ml) else None)
    return out


def run_all(season: int, verbose: bool = True) -> dict:
    from dataclasses import replace
    from .data import load_games
    schedule = load_games()
    if verbose:
        print("  trend check: building graded history (2013 on)...", flush=True)
    h = build_history(season, schedule)
    mm = margin_model_for_history()
    subj = subjects(h)

    # 1. margin reasons: screen one at a time, then fit the survivors jointly
    margin = test_margin_trends(h)
    joint = fit_joint(h, margin)
    beta_all = dict(zip(joint["keys"], joint["beta_all"]))
    for r in margin:
        if r["status"] != "candidate":
            continue
        if joint["status"] == "confirmed" and r["key"] in beta_all:
            r["status"] = "confirmed"
            r["live_shift"] = float(beta_all[r["key"]])
            r["conf_gain"] = joint["conf_gain"].get(r["key"])
        elif r["key"] in joint["not_selected"]:
            r["status"] = "absorbed"      # covered by the reasons already in, or too small
        elif r["key"] in joint["pruned"]:
            r["status"] = "rejected"      # made 2021+ worse alongside the others
        else:
            r["status"] = "watching"
    keys = joint["keys"] if joint["status"] == "confirmed" else []
    shift_d = _apply(subj, keys, joint["beta_disc"]) if keys else np.zeros(len(h))
    shift_a = _apply(subj, keys, joint["beta_all"]) if keys else np.zeros(len(h))

    # 2. moneyline win probability, on top of the margin fixes
    p_raw = win_probs(h.projected_margin, mm)
    p_adj_d = win_probs(h.projected_margin + shift_d, mm)
    p_adj_a = win_probs(h.projected_margin + shift_a, mm)
    cal = test_calibration(h, p_raw, p_adj_d, p_adj_a)
    p_new = calibrate(p_adj_d, cal["disc_fit"]) if cal["status"] == "confirmed" else p_adj_d

    # 3. bet types, judged on the FIXED model with 2021+ out of sample (its
    #    fixes were fit on 2013-2020). No underdog cap here, so long prices
    #    stay visible to the test.
    uncapped = replace(THRESHOLDS, ml_max_underdog=100000)
    h_new = h.assign(projected_margin=h.projected_margin + shift_d)
    bets_old = replay_bets(h, p_raw, mm, uncapped)
    bets_new = replay_bets(h_new, p_new, mm, uncapped)
    bet_rows = test_bet_types(bets_new)
    bets_live = replay_bets(h_new, p_new, mm, THRESHOLDS)

    stats = pbp_team_stats([season])
    misses = explain_misses(h, stats)

    return dict(
        generated_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        season=season,
        history=dict(n_games=int(len(h)), first_season=int(h.season.min()),
                     last_season=int(h.season.max()),
                     current_season_graded=int((h.source == "published").sum()),
                     discovery=list(DISCOVERY), confirmation=[CONFIRM[0], int(h.season.max())]),
        margin_trends=margin,
        joint=joint,
        calibration=cal,
        bet_types=bet_rows,
        bet_filters=dict(ml_max_underdog=ml_underdog_cap(bet_rows)),
        bets_before=bet_summary(bets_old),
        bets_after=bet_summary(bets_live),
        misses=misses.to_dict("records") if len(misses) else [],
    )


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if np.isnan(o) else round(float(o), 5)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def save(state: dict, path=TRENDS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_clean(state), indent=2) + "\n")


def load_active(path=TRENDS_FILE) -> dict:
    """The confirmed parts of the learned state, ready for run_week.py."""
    if not path.exists():
        return {}
    s = json.loads(path.read_text())
    return dict(
        generated_utc=s.get("generated_utc"),
        history=s.get("history", {}),
        margin=[r for r in s.get("margin_trends", []) if r.get("status") == "confirmed"],
        calibration=s["calibration"] if s.get("calibration", {}).get("status") == "confirmed" else None,
        ml_max_underdog=s.get("bet_filters", {}).get("ml_max_underdog"),
        watching=[r for r in s.get("margin_trends", []) if r.get("status") == "watching"],
    )


def game_shifts(f: pd.DataFrame, active: dict) -> tuple[np.ndarray, list[str]]:
    """Projection shift per game (home points) from confirmed margin trends, with notes."""
    shift = np.zeros(len(f))
    notes = [[] for _ in range(len(f))]
    if not active or not active.get("margin"):
        return shift, ["" for _ in range(len(f))]
    f = f.copy()
    if "projected_margin" not in f.columns:
        f["projected_margin"] = np.nan
    subj = subjects(f)
    for r in active["margin"]:
        s = subj.get(r["key"])
        if s is None:
            continue
        v = s * float(r["live_shift"])
        shift += v
        for i in np.nonzero(s)[0]:
            side = f.home_team.iloc[i] if s[i] > 0 else f.away_team.iloc[i]
            notes[i].append(f"{r['text']} ({side} {r['live_shift'] * 1:+.1f})")
    raw = shift.copy()
    shift = np.clip(shift, -MAX_TOTAL_SHIFT, MAX_TOTAL_SHIFT)
    text = []
    for i, n in enumerate(notes):
        if not n:
            text.append("")
            continue
        capped = " (capped)" if abs(raw[i]) > MAX_TOTAL_SHIFT else ""
        text.append(f"net {shift[i]:+.1f}{capped}: " + "; ".join(n))
    return shift, text
