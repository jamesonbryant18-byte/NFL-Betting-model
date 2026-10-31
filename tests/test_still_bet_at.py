"""
"Still a bet at": the worst number or price at which a bet still qualifies
(expert review round 2, 2026-10-29). He checks FanDuel on game day; this is
the number he checks against.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from nflmodel.model import NFLModel


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


def _bet(m, g):
    p = m.project(g)
    return p.bet_market, p.bet_side.split()[0] if p.bet_side else ""


def test_spread_number_is_the_last_line_that_still_qualifies():
    m = _model()
    g = _game()
    assert _bet(m, g) == ("SPREAD", "CLE")        # CLE +9.5, 3 pts of edge
    at = m.still_qualifies(g, "CLE +9.5", "SPREAD")
    assert at.startswith("CLE +")
    last = float(at.split("+")[1])
    assert last < 9.5                             # fewer points is worse for a dog bettor
    assert last % 1 == 0.5                        # the half-point rule: never a whole number
    assert _bet(m, _game(spread_line=last)) == ("SPREAD", "CLE")
    assert _bet(m, _game(spread_line=last - 1.0)) != ("SPREAD", "CLE")   # the next half point


def test_spread_scan_re_decides_the_trend_pull_and_restores_it():
    m = _model()
    m.game_adjust = {"x": 1.5}                    # today's pull (gap 3+ at 9.5)

    def pull(line):                               # the 3-pt rule, toward the line
        gap = 6.5 - line
        return 0.0 if abs(gap) < 3 else (1.5 if gap < 0 else -1.5)

    fixed = m.still_qualifies(_game(), "CLE +9.5", "SPREAD")
    moving = m.still_qualifies(_game(), "CLE +9.5", "SPREAD", trend_at=pull)
    assert m.game_adjust == {"x": 1.5}            # put back as it was
    # at 8.5 (9.0 is a whole number, stepped over) the gap is 2.0, the pull
    # switches off and the edge grows: the bet survives further than a scan
    # that kept today's pull fixed
    assert float(moving.split("+")[1]) < float(fixed.split("+")[1])


def test_moneyline_price_is_the_last_price_that_still_qualifies():
    m = _model()
    g = _game(spread_line=6.0, home_moneyline=-150, away_moneyline=130)
    assert _bet(m, g) == ("MONEYLINE", "TB")       # no spread edge, big ML edge
    at = m.still_qualifies(g, "TB -150", "MONEYLINE")
    price = float(at.split()[1])
    assert at.startswith("TB -") and price < -150  # laying more is worse
    assert price >= m.thresholds.ml_max_favorite   # never past the -350 limit


def test_a_bet_that_does_not_qualify_gets_no_number():
    m = _model()
    g = _game(spread_line=6.5)                     # model and line agree
    assert m.still_qualifies(g, "CLE +6.5", "SPREAD") == ""
    assert m.game_adjust == {}
