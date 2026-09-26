"""Kickoff forecast parsing and venue handling."""
import sys
sys.path.insert(0, 'src')

from datetime import datetime

import pandas as pd

from nflmodel import weather


def _hours(wind, pp, pr, code=3):
    t = pd.date_range("2026-09-27 10:00", periods=10, freq="h").strftime("%Y-%m-%dT%H:%M")
    return dict(time=list(t), temperature_2m=[60.0] * 10,
                precipitation_probability=[pp] * 10, precipitation=[pr] * 10,
                wind_speed_10m=[wind] * 10, wind_gusts_10m=[wind + 5] * 10,
                weather_code=[code] * 10)


def test_summary_covers_the_game_window_only():
    h = _hours(5.0, 0.0, 0.0)
    h["wind_speed_10m"][3] = 22.0                      # 13:00, kickoff hour
    h["wind_speed_10m"][9] = 40.0                      # 19:00, long after the game
    w = weather.summarize_hours(h, datetime(2026, 9, 27, 13, 0))
    assert w["wind_mph"] == 22.0


def test_forecast_flags_and_roofs(monkeypatch):
    monkeypatch.setattr(weather, "_open_meteo",
                        lambda lat, lon, day: {"hourly": _hours(18.0, 80.0, 0.05)})
    slate = pd.DataFrame([
        dict(game_id="out", stadium_id="NYC01", roof="outdoors", stadium="MetLife",
             gameday="2026-09-27", gametime="13:00"),
        dict(game_id="dome", stadium_id="DET00", roof="dome", stadium="Ford Field",
             gameday="2026-09-27", gametime="13:00"),
        dict(game_id="retract", stadium_id="IND00", roof=None, stadium="Lucas Oil",
             gameday="2026-09-27", gametime="13:00"),
    ])
    fc = weather.forecast_slate(slate, verbose=False)
    assert fc["out"]["windy"] and fc["out"]["precip"] and not fc["out"]["cold"]
    assert fc["dome"]["label"] == "dome" and not fc["dome"]["windy"]
    # a retractable roof closes for bad weather: shown, but not flagged
    assert "retractable" in fc["retract"]["label"] and not fc["retract"]["windy"]


def test_dead_feed_never_raises(monkeypatch):
    def boom(*a, **k):
        raise OSError("down")
    monkeypatch.setattr(weather, "_open_meteo", boom)
    slate = pd.DataFrame([dict(game_id="g", stadium_id="BUF00", roof="outdoors",
                               stadium="Highmark", gameday="2026-09-27", gametime="13:00")])
    fc = weather.forecast_slate(slate, verbose=False)
    assert fc["g"]["label"] == "forecast unavailable" and not fc["g"]["windy"]


def test_every_current_stadium_has_coordinates():
    games = pd.read_parquet("data/cache/games.parquet") if \
        __import__("pathlib").Path("data/cache/games.parquet").exists() else None
    if games is None:
        return
    ids = set(games[games.season >= 2024].stadium_id.dropna())
    assert ids <= set(weather.STADIUMS), sorted(ids - set(weather.STADIUMS))


def test_gameday_as_timestamp(monkeypatch):
    seen = {}
    def fake(lat, lon, day):
        seen["day"] = day
        return {"hourly": _hours(5.0, 0.0, 0.0)}
    monkeypatch.setattr(weather, "_open_meteo", fake)
    slate = pd.DataFrame([dict(game_id="g", stadium_id="BUF00", roof="outdoors", stadium="x",
                               gameday=pd.Timestamp("2026-09-27"), gametime="13:00")])
    fc = weather.forecast_slate(slate, verbose=False)
    assert seen["day"] == "2026-09-27" and "temp_f" in fc["g"]


def test_open_air_international_venues_get_weather():
    for sid in ("PAR00", "MUN01", "MEL00"):
        assert weather.venue_kind(sid, "dome") == "outdoor"
    assert weather.venue_kind("MAD01", None) == "retractable"
    assert weather.venue_kind("DET00", "dome") == "dome"


def test_flags_use_the_kickoff_hour_like_the_history(monkeypatch):
    h = _hours(10.0, 0.0, 0.0)
    h["wind_speed_10m"][5] = 25.0                      # 15:00, mid-game gust of wind
    monkeypatch.setattr(weather, "_open_meteo", lambda lat, lon, day: {"hourly": h})
    slate = pd.DataFrame([dict(game_id="g", stadium_id="BUF00", roof="outdoors", stadium="x",
                               gameday="2026-09-27", gametime="13:00")])
    w = weather.forecast_slate(slate, verbose=False)["g"]
    assert w["wind_mph"] == 25.0 and not w["windy"]    # shown, but kickoff was 10 mph


def test_gamebook_forecast_wording_is_not_rain(monkeypatch, tmp_path):
    df = pd.DataFrame(dict(game_id=["a", "b", "c", "d"], season=[2019] * 4,
                           weather=["Rain Temp: 45° F, Humidity: 90%, Wind: NW 12 mph",
                                    "Cloudy, chance of rain Temp: 61° F, Wind: SSW 9 mph",
                                    "30% Chance of Rain Temp: 88° F, Wind: NE 10 mph",
                                    "Light Snow Temp: 28° F, Wind: calm"],
                           roof=["outdoors"] * 4, temp=[None] * 4, wind=[None] * 4))
    monkeypatch.setattr(weather, "CACHE_DIR", tmp_path)
    df.to_parquet(tmp_path / "weather_2019.parquet", index=False)
    g = weather.gamebook([2019]).set_index("game_id")
    assert g.precip.to_dict() == {"a": True, "b": False, "c": False, "d": True}
    assert g.loc["a", "gb_wind"] == 12 and g.loc["d", "gb_wind"] == 0 and g.loc["d", "gb_temp"] == 28
