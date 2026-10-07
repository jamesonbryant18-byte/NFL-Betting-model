"""
Closing lines and CLV. Jameson, 2026-10-07: track the closing lines on the
Wednesday run and score the bets on them.

Pinned here: FanDuel first, then DraftKings, then nflverse; a week's closes
are written once and only when the week is final; CLV signs (a better number
than the close is positive); and the archive keeps the FIRST published number
for each bet, so a Sunday re-run cannot erase what CLV is measured from.
"""
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pandas as pd
import pytest

from nflmodel import closing as C
from nflmodel.archive import _keep_first_published
from nflmodel.config import CURRENT_SEASON
from nflmodel.history import _with_recorded_close

S = CURRENT_SEASON


def _games(played=True):
    return pd.DataFrame({
        "season": S, "week": 4, "played": played,
        "game_id": [f"{S}_04_GB_TB", f"{S}_04_DET_CAR", f"{S}_04_IND_WAS"],
        "away_team": ["GB", "DET", "IND"], "home_team": ["TB", "CAR", "WAS"],
        "gameday": [f"{S}-10-04"] * 3,
        "spread_line": [-3.0, -4.0, -1.5],
        "home_spread_odds": [-110.0] * 3, "away_spread_odds": [-110.0] * 3,
        "home_moneyline": [130.0, 180.0, 105.0], "away_moneyline": [-150.0, -220.0, -125.0],
    })


def _an(rows):
    cols = ["game", "commence_time", "book", "spread", "spread_odds",
            "away_spread_odds", "home_ml", "away_ml"]
    return pd.DataFrame(rows, columns=cols)


AN = _an([
    ["GB@TB", f"{S}-10-04T17:00:00Z", "fanduel", -2.5, -105, -115, 126, -148],
    ["GB@TB", f"{S}-10-04T17:00:00Z", "draftkings", -3.0, -110, -110, 130, -155],
    ["DET@CAR", f"{S}-10-05T00:20:00Z", "draftkings", -4.5, -110, -110, 190, -230],
])


def test_fanduel_first_then_draftkings_then_nflverse():
    df = C.fetch_closing(S, 4, _games(), book="fanduel", fetch=lambda wk: AN)
    by = df.set_index("home_team")
    assert by.loc["TB", "close_source"] == "fanduel (action network)"
    assert by.loc["TB", "close_spread"] == -2.5 and by.loc["TB", "close_away_ml"] == -148
    assert by.loc["CAR", "close_source"] == "draftkings (action network)"
    assert by.loc["WAS", "close_source"] == "draftkings (nflverse)"
    assert by.loc["WAS", "close_spread"] == -1.5


def test_same_week_number_from_another_season_is_not_used():
    stale = AN.assign(commence_time=f"{S - 1}-10-05T17:00:00Z")
    df = C.fetch_closing(S, 4, _games(), book="fanduel", fetch=lambda wk: stale)
    assert (df.close_source == "draftkings (nflverse)").all()


def test_dead_feed_falls_back_to_nflverse():
    def boom(wk):
        raise OSError("down")
    df = C.fetch_closing(S, 4, _games(), fetch=boom)
    assert len(df) == 3 and (df.close_source == "draftkings (nflverse)").all()


def test_closes_written_once_and_only_when_the_week_is_final(tmp_path):
    assert C.record_closing(S, 4, _games(played=False), tmp_path, fetch=lambda wk: AN) is None
    assert not C.closing_path(S, 4, tmp_path).exists()
    first = C.record_closing(S, 4, _games(), tmp_path, fetch=lambda wk: AN)
    assert len(first) == 3
    moved = AN.assign(spread=-9.0)
    again = C.record_closing(S, 4, _games(), tmp_path, fetch=lambda wk: moved)
    assert again.close_spread.tolist() == first.close_spread.tolist()


def test_clv_signs_from_the_bettors_side():
    row = pd.Series({"home_team": "TB", "away_team": "GB", "close_spread": -2.5,
                     "close_home_ml": 126.0, "close_away_ml": -148.0})
    # TB closed +2.5; he took +3.5 -> one point better than the close.
    close, pts, _ = C.bet_clv("SPREAD", "TB", 3.5, -148, row)
    assert close == 2.5 and pts == pytest.approx(1.0)
    # GB closed -2.5; laying -3.5 was a point worse.
    assert C.bet_clv("SPREAD", "GB", -3.5, -110, row)[1] == pytest.approx(-1.0)
    # Moneyline: TB +140 taken vs +126 close is a better price -> positive.
    assert C.bet_clv("MONEYLINE", "TB", None, 140, row)[2] > 0
    assert C.bet_clv("MONEYLINE", "TB", None, 110, row)[2] < 0
    assert C.ticket("KC PK") == 0.0 and C.ticket("TB +3.0") == 3.0


def test_first_published_number_survives_a_sunday_rerun(tmp_path):
    p = tmp_path / "week05_first_leans.csv"
    wed = pd.DataFrame({"game_id": ["g1", "g2"], "bet_market": ["SPREAD", "MONEYLINE"],
                        "bet_side": ["TB +8.5", "SEA -162"], "bet_odds": [-110, -162]})
    _keep_first_published(wed, p)
    sun = pd.DataFrame({"game_id": ["g1", "g3"], "bet_market": ["SPREAD", "SPREAD"],
                        "bet_side": ["TB +7.5", "NYG +3.5"], "bet_odds": [-110, -110]})
    _keep_first_published(sun, p)
    got = pd.read_csv(p)
    assert got.bet_side.tolist() == ["TB +8.5", "SEA -162", "NYG +3.5"]


def test_card_clv_prefers_the_first_published_card(tmp_path):
    d = tmp_path / str(S)
    d.mkdir()
    base = {"game_id": [f"{S}_04_GB_TB"], "home_team": ["TB"], "away_team": ["GB"],
            "bet_market": ["SPREAD"], "bet_odds": [-110]}
    pd.DataFrame({**base, "bet_side": ["TB +3.0"]}).to_csv(d / "week04_leans.csv", index=False)
    C.record_closing(S, 4, _games(), tmp_path, fetch=lambda wk: AN)
    assert C.card_clv(S, 4, tmp_path).iloc[0].card_source == "final card"
    pd.DataFrame({**base, "bet_side": ["TB +3.5"]}).to_csv(d / "week04_first_leans.csv", index=False)
    r = C.card_clv(S, 4, tmp_path).iloc[0]
    assert r.card_source == "first published" and r.clv_pts == pytest.approx(1.0)


def test_typed_close_wins_over_the_recorded_one():
    row = pd.Series({"home_team": "TB", "away_team": "GB", "close_spread": -2.5,
                     "close_home_ml": 126.0, "close_away_ml": -148.0})
    blank = {"market": "SPREAD", "bet_side": "TB", "closing_line": None, "closing_odds": None}
    typed = {**blank, "closing_line": 3.0}
    assert _with_recorded_close(blank, row)["closing_line"] == 2.5
    assert _with_recorded_close(typed, row)["closing_line"] == 3.0
    assert blank["closing_line"] is None          # his row is never changed
