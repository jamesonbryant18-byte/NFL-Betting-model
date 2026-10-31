"""
Jameson's half-point rule (2026-10-31): a spread at a whole number (3, 7, ...)
is never a bet; Jameson can't place them. The game's moneyline is still considered.
"""
import os
import sys
from dataclasses import replace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pandas as pd

from nflmodel.config import THRESHOLDS
from nflmodel.model import NFLModel


def _model(**rule):
    m = NFLModel(thresholds=replace(THRESHOLDS, **rule))
    m.team_ratings = {"TB": 3.0, "CLE": -2.0}
    m.hfa = 1.5                                   # TB by 6.5 at home
    return m


def _game(**kw):
    g = dict(game_id="x", week=8, home_team="TB", away_team="CLE", spread_line=10.0,
             home_moneyline=-450, away_moneyline=340, home_spread_odds=-110,
             away_spread_odds=-110, home_qb_name=None, away_qb_name=None)
    g.update(kw)
    return g


def test_the_rule_is_on_in_config():
    assert THRESHOLDS.spread_half_points_only is True


def test_a_whole_number_spread_is_never_a_bet():
    assert _model().project(_game()).bet_market != "SPREAD"            # CLE +10, 3.5 pts of edge
    assert _model().project(_game(spread_line=10.5)).bet_side == "CLE +10.5"
    off = _model(spread_half_points_only=False).project(_game())
    assert off.bet_side == "CLE +10.0"            # the rule kept it off, not the edge


def test_a_whole_number_game_can_still_be_a_moneyline_bet():
    g = _game(spread_line=3.0, home_moneyline=-150, away_moneyline=130)   # TB -3, model TB by 6.5
    p = _model().project(g)
    assert (p.bet_market, p.bet_side) == ("MONEYLINE", "TB -150")
    off = _model(spread_half_points_only=False).project(g)
    assert (off.bet_market, off.bet_side) == ("SPREAD", "TB -3.0")


def test_still_a_bet_at_steps_over_whole_numbers():
    m = _model()
    assert m.still_qualifies(_game(spread_line=10.5), "CLE +10.5", "SPREAD") == "CLE +8.5"
    assert m.still_qualifies(_game(), "CLE +10.0", "SPREAD") == ""      # not a bet at all


def test_filler_is_never_a_whole_number_spread():
    m = _model()
    for line, want in ((6.0, None), (5.5, "TB -5.5")):
        row = pd.Series(m.project(_game(spread_line=line, home_moneyline=None,
                                         away_moneyline=None)).as_row())
        assert row.bet_side == ""                 # under the 1.5-pt bar: not a bet
        miss = m._near_miss(row, (-110.0, -110.0))
        assert (miss or {}).get("side") == want
