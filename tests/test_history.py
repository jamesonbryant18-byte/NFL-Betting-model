"""
Tests for history.py — the archive, the results and the tracker joined.

The grading rules are pinned to review_week.py's, which is the only other
grader in the repo; if the two ever disagree the archive stops being
evidence. The fixture is one synthetic week with a right pick, a wrong
pick, a tie and an unplayed game, plus a tracker with one row that matches
by week and one that only matches by date.

Run: .venv/bin/python -W ignore -m pytest tests/test_history.py -q
"""
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pandas as pd
import pytest

import nflmodel.archive as A
from nflmodel.history import (HISTORY_COLUMNS, build_history, grade_lean,
                              grade_pick, load_all_archives, match_bets,
                              summarize_history)
from nflmodel.betlog import parse_row


# ── fixture: one archived week ──────────────────────────────────

PICKS = pd.DataFrame([
    # rank, winner, loser, matchup, at_home, win_prob, proj_margin, moneyline, market_favorite, confidence
    dict(rank=1, winner="KC", loser="DEN", matchup="DEN @ KC", at_home=True,
         win_prob=0.70, proj_margin=6.0, moneyline=-250.0, market_favorite=True,
         confidence="strong", consistent=True),
    dict(rank=2, winner="DAL", loser="NYG", matchup="DAL @ NYG", at_home=False,
         win_prob=0.60, proj_margin=3.0, moneyline=-150.0, market_favorite=True,
         confidence="lean", consistent=True),
    dict(rank=3, winner="LV", loser="MIA", matchup="MIA @ LV", at_home=True,
         win_prob=0.55, proj_margin=1.5, moneyline=-120.0, market_favorite=True,
         confidence="slight", consistent=True),
    dict(rank=4, winner="SEA", loser="NE", matchup="NE @ SEA", at_home=True,
         win_prob=0.52, proj_margin=0.5, moneyline=-105.0, market_favorite=False,
         confidence="coin flip", consistent=False),
])

LEANS = pd.DataFrame([
    # spread lean on the home dog NYG +3.0, published at spread_line -3.0
    dict(game_id="2026_01_DAL_NYG", home_team="NYG", away_team="DAL",
         spread_line=-3.0, projected_margin=-3.0, fair_spread=-3.0,
         spread_edge_pts=0.0, home_win_prob=0.40, home_ml=130.0, away_ml=-150.0,
         ml_edge_home=0.0, ml_edge_away=0.0, recommendation="LEAN NYG +3.0",
         bet_market="SPREAD", bet_side="NYG +3.0", bet_odds=-110.0,
         confidence="Medium"),
    # moneyline lean on the away dog DEN
    dict(game_id="2026_01_DEN_KC", home_team="KC", away_team="DEN",
         spread_line=6.5, projected_margin=6.0, fair_spread=6.0,
         spread_edge_pts=-0.5, home_win_prob=0.70, home_ml=-250.0, away_ml=210.0,
         ml_edge_home=-0.02, ml_edge_away=0.02, recommendation="LEAN DEN +210",
         bet_market="MONEYLINE", bet_side="DEN +210", bet_odds=210.0,
         confidence="Medium"),
])

META = {"season": 2026, "week": 1, "generated_utc": "2026-09-09T14:13:54+00:00",
        "n_games": 4, "n_leans": 2, "starters": {}, "starter_source": {},
        "locked": True}

GAMES = pd.DataFrame([
    # KC picked, KC won 27-20: correct. DEN ML lean loses.
    dict(season=2026, week=1, gameday=pd.Timestamp("2026-09-14"), home_team="KC",
         away_team="DEN", home_score=27.0, away_score=20.0, result=7.0),
    # DAL picked, NYG won 24-21: wrong. NYG +3.0 lean wins (margin 3 > -3).
    dict(season=2026, week=1, gameday=pd.Timestamp("2026-09-13"), home_team="NYG",
         away_team="DAL", home_score=24.0, away_score=21.0, result=3.0),
    # tie: played, ungraded
    dict(season=2026, week=1, gameday=pd.Timestamp("2026-09-13"), home_team="LV",
         away_team="MIA", home_score=17.0, away_score=17.0, result=0.0),
    # unplayed
    dict(season=2026, week=1, gameday=pd.Timestamp("2026-09-15"), home_team="SEA",
         away_team="NE", home_score=float("nan"), away_score=float("nan"),
         result=float("nan")),
    # a different week — must not be matched to anything above
    dict(season=2026, week=2, gameday=pd.Timestamp("2026-09-21"), home_team="KC",
         away_team="DEN", home_score=10.0, away_score=30.0, result=-20.0),
])
GAMES["played"] = GAMES["result"].notna()

# Raw tracker rows, as read_tracker_rows / read_csv_rows would hand them over.
BET_BY_WEEK = ["9/10/2026", 1, "DAL @ NYG", "SPREAD", "NYG +3.0", 3.5, -110, 50,
               "W", 2.5, -110, 1.5]
BET_BY_DATE = ["9/13/2026", "", "MIA @ LV", "SPREAD", "MIA +3.5", 3.5, -110, 50,
               "Push", "", "", ""]
BET_SECOND_ON_SAME_GAME = ["9/11/2026", 1, "DAL@NYG", "MONEYLINE", "NYG +130",
                           "", 130, 20, "L", "", 120, ""]
BET_OTHER_SEASON = ["9/12/2025", 1, "DEN @ KC", "MONEYLINE", "DEN +200", "", 200,
                    10, "L", "", "", ""]
TRACKER = [BET_BY_WEEK, BET_BY_DATE, BET_SECOND_ON_SAME_GAME, BET_OTHER_SEASON]

PTS = [(2.5, 0.03), (3.5, 0.081)]


@pytest.fixture
def archive_dir(tmp_path, monkeypatch):
    """Point archive.ARCHIVE_DIR at a synthetic archive for the test."""
    d = tmp_path / "picks" / "2026"
    d.mkdir(parents=True)
    PICKS.to_csv(d / "week01_picks.csv", index=False)
    LEANS.to_csv(d / "week01_leans.csv", index=False)
    (d / "week01_meta.json").write_text(json.dumps(META))
    (tmp_path / "picks" / ".DS_Store").write_bytes(b"")
    monkeypatch.setattr(A, "ARCHIVE_DIR", tmp_path / "picks")
    return tmp_path / "picks"


# ── archive loading ─────────────────────────────────────────────

def test_load_all_archives_reads_archive_dir_at_call_time(archive_dir, tmp_path):
    arcs = load_all_archives()
    assert [(a["season"], a["week"]) for a in arcs] == [(2026, 1)]
    assert len(arcs[0]["picks"]) == 4 and len(arcs[0]["leans"]) == 2
    assert arcs[0]["meta"]["locked"] is True

    # A second week with no leans file and no meta still loads, and the
    # result is sorted by (season, week) regardless of directory order.
    d25 = tmp_path / "picks" / "2025"
    d25.mkdir()
    PICKS.to_csv(d25 / "week17_picks.csv", index=False)
    PICKS.to_csv(archive_dir / "2026" / "week03_picks.csv", index=False)
    arcs = load_all_archives()
    assert [(a["season"], a["week"]) for a in arcs] == [(2025, 17), (2026, 1), (2026, 3)]
    assert arcs[0]["leans"].empty and arcs[0]["meta"] == {}
    assert load_all_archives(tmp_path / "does-not-exist") == []


# ── grading ─────────────────────────────────────────────────────

def test_grade_pick_matches_review_week():
    g = GAMES.iloc[0]
    right = grade_pick(PICKS.iloc[0], g)
    assert right == dict(played=True, actual_winner="KC", home_score=27,
                         away_score=20, result=7.0, correct="Y")
    wrong = grade_pick(PICKS.iloc[1], GAMES.iloc[1])
    assert wrong["correct"] == "N" and wrong["actual_winner"] == "NYG"
    tie = grade_pick(PICKS.iloc[2], GAMES.iloc[2])
    assert tie["played"] is True and tie["correct"] == "" and tie["actual_winner"] == "TIE"
    unplayed = grade_pick(PICKS.iloc[3], GAMES.iloc[3])
    assert unplayed == dict(played=False, actual_winner="", home_score=None,
                            away_score=None, result=None, correct="")
    assert grade_pick(PICKS.iloc[0], None)["played"] is False


def test_grade_lean_matches_review_week():
    # Spread: NYG +3.0 at spread_line -3.0; NYG won by 3 -> margin 3 > -3.
    assert grade_lean(LEANS.iloc[0], GAMES.iloc[1]) == "WIN"
    # Moneyline on DEN, KC won.
    assert grade_lean(LEANS.iloc[1], GAMES.iloc[0]) == "LOSS"
    # Ungradeable.
    assert grade_lean(LEANS.iloc[0], GAMES.iloc[3]) == ""
    assert grade_lean(LEANS.iloc[0], None) == ""

    # Exact landing is a push; a road favorite laying points is judged from
    # its own side (line flipped).
    lean = dict(bet_market="SPREAD", bet_side="DAL -3.0", spread_line=-3.0)
    assert grade_lean(lean, dict(home_team="NYG", away_team="DAL", result=-3.0)) == "PUSH"
    assert grade_lean(lean, dict(home_team="NYG", away_team="DAL", result=-4.0)) == "WIN"
    assert grade_lean(lean, dict(home_team="NYG", away_team="DAL", result=-2.0)) == "LOSS"
    # Home favorite: KC -6.5, KC by 7 covers.
    lean = dict(bet_market="SPREAD", bet_side="KC -6.5", spread_line=6.5)
    assert grade_lean(lean, GAMES.iloc[0]) == "WIN"
    # Moneyline on a tie is a push.
    lean = dict(bet_market="MONEYLINE", bet_side="LV -120", spread_line=1.5)
    assert grade_lean(lean, GAMES.iloc[2]) == "PUSH"


# ── tracker matching ────────────────────────────────────────────

def test_match_bets_by_week_then_by_date():
    bets = [parse_row(r) for r in TRACKER]
    by_week = match_bets(bets, 2026, 1, "DAL @ NYG", date(2026, 9, 13))
    assert [b["bet_side"] for b in by_week] == ["NYG +3.0", "NYG +130"]
    # Week typed as 1 does not attach to week 2.
    assert match_bets(bets, 2026, 2, "DAL @ NYG", date(2026, 9, 20)) == []

    by_date = match_bets(bets, 2026, 1, "mia at lv", date(2026, 9, 13))
    assert [b["bet_side"] for b in by_date] == ["MIA +3.5"]
    assert match_bets(bets, 2026, 3, "MIA @ LV", date(2026, 9, 27)) == []
    # No gameday known: the dated row matches on matchup alone.
    assert len(match_bets(bets, 2026, 1, "MIA @ LV", None)) == 1
    # A 2025 bet on DEN @ KC does not attach to the 2026 game.
    assert match_bets(bets, 2026, 1, "DEN @ KC", date(2026, 9, 14)) == []
    assert len(match_bets(bets, 2025, 1, "DEN @ KC", date(2025, 9, 12))) == 1


def test_loosely_typed_matchup_is_read_as_the_real_game():
    # 2026 Week 3, exactly as he typed it: 'TEN @ NY ' with side HOME.
    raw = [date(2026, 9, 27), 3, "TEN @ NY ", "MONEYLINE", "HOME", None, -127, 5, "W"]
    bets = [parse_row(raw)]
    got = match_bets(bets, 2026, 3, "TEN @ NYG", date(2026, 9, 27))
    assert len(got) == 1
    assert got[0]["matchup"] == "TEN @ NYG" and got[0]["bet_side"] == "NYG"
    # Reading never rewrites what he typed.
    assert bets[0]["matchup"] == "TEN @ NY" and bets[0]["bet_side"] == "NY"
    # Same week, a different NY game: TEN is not in it, so no match.
    assert match_bets(bets, 2026, 3, "NYJ @ MIA", date(2026, 9, 27)) == []
    # Another week: the typed week rules it out.
    assert match_bets(bets, 2026, 4, "TEN @ NYG", date(2026, 10, 4)) == []
    # No week and no date: too ambiguous to match loosely.
    undated = parse_row([None, None, "TEN @ NY", "MONEYLINE", "HOME", None, -127, 5])
    assert match_bets([undated], 2026, 3, "TEN @ NYG", date(2026, 9, 27)) == []


def test_sportsbook_team_codes_match_the_real_game():
    # 2026 Week 4, exactly as he typed it: 'JAC @ CIN ', side AWAY, +2.5.
    raw = [date(2026, 10, 4), 4, "JAC @ CIN ", "SPREAD", "AWAY", 2.5, -107, 5, "W"]
    bets = [parse_row(raw)]
    got = match_bets(bets, 2026, 4, "JAX @ CIN", date(2026, 10, 4))
    assert len(got) == 1
    assert got[0]["matchup"] == "JAX @ CIN" and got[0]["bet_side"] == "JAX"
    # A side typed with the alias resolves too.
    wsh = parse_row([date(2026, 10, 11), 5, "NYG @ WSH", "SPREAD", "WSH -3.5", -3.5, -110, 5])
    assert match_bets([wsh], 2026, 5, "NYG @ WAS", None)[0]["bet_side"] == "WAS -3.5"
    # The alias never stretches to a different opponent.
    assert match_bets(bets, 2026, 4, "JAX @ PIT", date(2026, 10, 4)) == []


def test_loose_match_does_not_confuse_la_and_lac():
    # Rams at SEA exactly: exact match, untouched.
    rams = parse_row([date(2026, 10, 4), 4, "LA @ SEA", "SPREAD", "LA +3.5", 3.5, -110, 5])
    assert match_bets([rams], 2026, 4, "LA @ SEA", None)[0]["bet_side"] == "LA +3.5"
    # 'LA @ SEA' in a week where SEA hosts the Chargers can only mean LAC.
    got = match_bets([rams], 2026, 4, "LAC @ SEA", None)
    assert got[0]["matchup"] == "LAC @ SEA" and got[0]["bet_side"] == "LAC +3.5"


# ── the frame ───────────────────────────────────────────────────

def test_build_history_grades_and_joins(archive_dir):
    hist = build_history(GAMES, TRACKER, pts_table=PTS)
    assert list(hist.columns) == HISTORY_COLUMNS
    assert len(hist) == 4
    assert list(hist["matchup"]) == ["DEN @ KC", "DAL @ NYG", "MIA @ LV", "NE @ SEA"]
    assert list(hist["away"]) == ["DEN", "DAL", "MIA", "NE"]
    assert list(hist["home"]) == ["KC", "NYG", "LV", "SEA"]

    assert list(hist["correct"]) == ["Y", "N", "", ""]
    assert list(hist["played"]) == [True, True, True, False]
    assert list(hist["actual_winner"]) == ["KC", "NYG", "TIE", ""]
    assert hist["gameday"].iloc[0] == date(2026, 9, 14)
    assert hist["gameday"].iloc[3] == date(2026, 9, 15)

    assert list(hist["lean"]) == ["LEAN DEN +210", "LEAN NYG +3.0", "", ""]
    assert list(hist["lean_result"]) == ["LOSS", "WIN", "", ""]
    assert hist["lean_line"].iloc[1] == -3.0 and pd.isna(hist["lean_line"].iloc[2])
    assert hist["lean_market"].iloc[0] == "MONEYLINE" and hist["lean_odds"].iloc[0] == 210.0

    assert list(hist["bet"]) == ["N", "Y", "Y", "N"]
    assert list(hist["n_bets"]) == [0, 2, 1, 0]
    dal = hist.iloc[1]
    assert dal["bet_market"] == "SPREAD" and dal["bet_side"] == "NYG +3.0"
    assert dal["bet_line"] == 3.5 and dal["bet_odds"] == -110.0 and dal["bet_stake"] == 50.0
    assert dal["bet_result"] == "W" and dal["closing_line"] == 2.5
    assert dal["clv_pts"] == pytest.approx(1.0)
    assert dal["clv_prob"] == pytest.approx(0.081)
    assert dal["model_edge"] == 1.5
    mia = hist.iloc[2]
    assert mia["bet_result"] == "PUSH" and pd.isna(mia["clv_pts"])

    assert list(hist["locked"]) == [True] * 4
    assert hist["generated_utc"].iloc[0] == META["generated_utc"]
    assert list(hist["running_graded"]) == [1, 2, 2, 2]
    assert list(hist["running_correct"]) == [1, 1, 1, 1]
    assert hist["running_acc"].iloc[-1] == pytest.approx(0.5)


def test_build_history_keeps_games_missing_from_the_games_frame(archive_dir):
    hist = build_history(GAMES[GAMES.home_team != "KC"], TRACKER)
    assert len(hist) == 4
    kc = hist[hist.home == "KC"].iloc[0]
    assert kc["played"] is False or kc["played"] == False   # noqa: E712
    assert kc["correct"] == "" and kc["lean_result"] == ""
    # And an empty archive gives an empty, correctly shaped frame.
    empty = build_history(GAMES, TRACKER, archive_dir=archive_dir.parent / "nothing")
    assert list(empty.columns) == HISTORY_COLUMNS and len(empty) == 0
    assert summarize_history(empty)["overall"] == {"graded": 0, "correct": 0,
                                                    "accuracy": None}


def test_summarize_history_numbers(archive_dir):
    s = summarize_history(build_history(GAMES, TRACKER, pts_table=PTS))
    assert s["overall"] == {"graded": 2, "correct": 1, "accuracy": 0.5}

    tiers = {t["tier"]: t for t in s["by_tier"]}
    assert [t["tier"] for t in s["by_tier"]] == ["strong", "lean", "slight", "coin flip"]
    assert tiers["strong"] == dict(tier="strong", n=1, graded=1, correct=1,
                                   said=pytest.approx(0.70), actual=1.0)
    assert tiers["lean"] == dict(tier="lean", n=1, graded=1, correct=0,
                                 said=pytest.approx(0.60), actual=0.0)
    assert tiers["slight"]["graded"] == 0 and tiers["slight"]["actual"] is None

    assert s["leans"] == {"graded": 2, "wins": 1, "losses": 1, "pushes": 0}
    assert s["by_week"] == [dict(season=2026, week=1, n=4, graded=2, correct=1,
                                 accuracy=0.5, leans_graded=2, leans_won=1)]
    assert s["clv"]["n"] == 2
    assert s["clv"]["avg_clv_pts"] == pytest.approx(1.0)
    assert s["clv"]["avg_clv_prob"] == pytest.approx(0.081)
