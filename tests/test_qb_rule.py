"""
Jameson's QB rule (2026-11-04): no bets ON a team whose starter has under 8
career starts AND under 5 starts this season. Either count clears him.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pandas as pd

from nflmodel.config import THRESHOLDS
from nflmodel.model import NFLModel
from nflmodel.qb_rule import counts_before, describe, game_blocks, is_blocked, played_log


def test_either_count_clears_him():
    assert THRESHOLDS.qb_min_career_starts == 8 and THRESHOLDS.qb_min_season_starts == 5
    assert is_blocked(0, 0)                       # first career start
    assert is_blocked(7, 4)
    assert not is_blocked(8, 0)                   # a veteran's first start this year
    assert not is_blocked(5, 5)                   # the rookie: 5 this season, under 8 career
    assert not is_blocked(7, 5)
    assert not is_blocked(30, 8)


def _played(season, day, home, away, hq, aq, result=3.0):
    return dict(game_id=f"{day}_{home}", season=season, gameday=day, home_team=home,
                away_team=away, home_qb_name=hq, away_qb_name=aq, result=result)


def test_counts_only_earlier_played_games_across_teams_and_name_spellings():
    games = pd.DataFrame([
        _played(2025, "2025-10-05", "PHI", "DAL", "Tanner McKee", "Dak Prescott"),
        _played(2026, "2026-10-04", "NYG", "PHI", "Jaxson Dart", "Tanner McKee"),
        _played(2026, "2026-10-11", "PHI", "WAS", "Tanner McKee Jr.", "Jayden Daniels"),
        _played(2026, "2026-10-18", "PHI", "CAR", "Tanner McKee", "Bryce Young", result=float("nan")),
    ])
    log = played_log(games)
    assert counts_before(log, "Tanner McKee", 2026, "2026-10-18") == (3, 2)
    assert counts_before(log, "Tanner McKee", 2026, "2026-10-11") == (2, 1)   # not the game itself
    assert counts_before(log, "Nobody Here", 2026, "2026-10-18") == (0, 0)


def test_game_blocks_names_only_the_unproven_side():
    history = [_played(2026, f"2026-{m:02d}-{d:02d}", "KC", "DEN", "Patrick Mahomes", "Bo Nix")
               for m, d in ((9, 6), (9, 13), (9, 20), (9, 27), (10, 4), (10, 11), (10, 18), (10, 25))]
    slate = pd.DataFrame([dict(game_id="g1", season=2026, gameday="2026-11-05", home_team="BAL",
                               away_team="KC", home_qb_name="Joe Fagnano",
                               away_qb_name="Patrick Mahomes", result=float("nan")),
                          dict(game_id="g2", season=2026, gameday="2026-11-05", home_team="DEN",
                               away_team="SF", home_qb_name="Bo Nix",
                               away_qb_name=None, result=float("nan"))])
    blocks, rows = game_blocks(slate, pd.DataFrame(history))
    assert blocks == {"g1": {"BAL"}}              # an unknown QB is not blocked
    assert describe(rows[0]) == "BAL: Joe Fagnano (0 career starts, 0 this season)"


def _model():
    m = NFLModel()
    m.team_ratings = {"TB": 3.0, "CLE": -2.0}
    m.hfa = 1.5                                   # TB by 6.5 at home
    return m


def _game(**kw):
    g = dict(game_id="x", week=8, home_team="TB", away_team="CLE", spread_line=9.5,
             home_moneyline=-450, away_moneyline=340, home_spread_odds=-110,
             away_spread_odds=-110, home_qb_name=None, away_qb_name=None)
    g.update(kw)
    return g


def test_no_bet_on_the_blocked_team():
    m = _model()
    assert m.project(_game()).bet_side == "CLE +9.5"
    m.no_bet_teams = {"x": {"CLE"}}
    p = m.project(_game())
    assert p.bet_side == "" and p.recommendation == "NO BET"


def test_a_bet_against_the_blocked_team_is_still_allowed():
    m = _model()
    m.no_bet_teams = {"x": {"TB"}}
    assert m.project(_game()).bet_side == "CLE +9.5"


def test_the_rule_only_touches_its_own_game():
    m = _model()
    m.no_bet_teams = {"another game": {"CLE"}}
    assert m.project(_game()).bet_side == "CLE +9.5"


def test_filler_cannot_use_a_blocked_team():
    m = _model()
    # model and line a point apart: no real bet, CLE +7.5 is the near miss
    game = _game(spread_line=7.5, home_moneyline=None, away_moneyline=None)
    row = m.project(game).as_row()
    assert m._near_miss(row, (-110, -110))["team"] == "CLE"
    m.no_bet_teams = {"x": {"CLE"}}
    assert m._near_miss(row, (-110, -110)) is None


def test_the_card_refills_past_a_blocked_team():
    m = _model()
    m.team_ratings = {"TB": 3.0, "CLE": -2.0, "NE": 3.0, "BUF": -2.0}
    games = pd.DataFrame([_game(), _game(game_id="y", home_team="NE", away_team="BUF")])
    m.no_bet_teams = {"x": {"CLE"}}
    sides = set(m.project_slate(games, advisory=False).bet_side)
    assert "BUF +9.5" in sides and "CLE +9.5" not in sides
