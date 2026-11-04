"""
"Bet Range" on This Week's Bets (Jameson, 2026-11-04): the range of lines the
model still calls a bet, worked out per bet from the line, not a flat limit.
Each end is checked by re-running project() at the printed line and just past it.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from nflmodel.model import NFLModel, _american_at, _price_step


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


def _rungs(text):
    return [(float(n), float(p)) for n, p in re.findall(r"([+-]\d+\.5) \(([+-]\d+)\)", text)]


def _is_cle_spread(m, line, price):
    p = m.project(_game(spread_line=line, away_spread_odds=price))
    return p.bet_market == "SPREAD" and p.bet_side.startswith("CLE")


def _one_cent_worse(price):
    return _american_at(_price_step(price) - 1)


def test_price_scale_crosses_even_money():
    assert _price_step(100) == 0 and _american_at(0) == 100
    assert _price_step(-101) == -1 and _american_at(-1) == -101
    assert _american_at(_price_step(-150) - 1) == -151
    assert _american_at(_price_step(120) - 1) == 119


def test_spread_range_holds_each_number_to_the_cent():
    m = _model()
    rungs = _rungs(m.bet_range(_game(), "CLE +9.5", "SPREAD"))
    assert rungs, "no range"
    numbers = [n for n, _ in rungs]
    assert 9.5 in numbers
    assert max(numbers) == 11.5                   # two points better than the bet's own number
    for number, price in rungs:
        assert number % 1 == 0.5                  # the half-point rule
    # the worst number and the price limits at it are exact
    low, low_price = rungs[0]
    assert _is_cle_spread(m, low, low_price)
    assert not _is_cle_spread(m, low, _one_cent_worse(low_price))
    assert not _is_cle_spread(m, low - 1.0, 100.0)


def test_worst_number_matches_still_a_bet_at():
    m = _model()
    at = m.still_qualifies(_game(), "CLE +9.5", "SPREAD")
    assert _rungs(m.bet_range(_game(), "CLE +9.5", "SPREAD"))[0][0] == float(at.split("+")[1])


def test_a_better_number_never_has_a_tighter_price():
    m = _model()

    def pull(line):                               # the 3-pt switch can tighten a better number
        gap = 6.5 - line
        return 0.0 if abs(gap) < 3 else (1.5 if gap < 0 else -1.5)

    steps = [_price_step(p) for _, p in _rungs(m.bet_range(_game(), "CLE +9.5", "SPREAD", trend_at=pull))]
    assert steps == sorted(steps, reverse=True)


def test_range_puts_the_trend_pull_back():
    m = _model()
    m.game_adjust = {"x": 1.5}
    m.bet_range(_game(), "CLE +9.5", "SPREAD", trend_at=lambda line: 0.0)
    assert m.game_adjust == {"x": 1.5}
    m = _model()
    m.bet_range(_game(), "CLE +9.5", "SPREAD", trend_at=lambda line: 0.0)
    assert m.game_adjust == {}


def test_home_favorite_spread_numbers_read_as_the_ticket():
    m = NFLModel()
    m.team_ratings = {"TB": 6.0, "CLE": -2.0}
    m.hfa = 1.5                                   # TB by 9.5 at home
    g = _game(spread_line=6.5)
    p = m.project(g)
    assert p.bet_market == "SPREAD" and p.bet_side == "TB -6.5"
    numbers = [n for n, _ in _rungs(m.bet_range(g, "TB -6.5", "SPREAD"))]
    assert -6.5 in numbers
    assert numbers == sorted(numbers)             # worst (most points laid) first
    assert numbers[-1] == -4.5


def test_favorite_moneyline_is_a_limit_or_better():
    m = _model()
    g = _game(spread_line=6.0, home_moneyline=-150, away_moneyline=130)
    text = m.bet_range(g, "TB -150", "MONEYLINE")
    assert re.fullmatch(r"TB -\d+ or better", text)
    assert text.split(" or")[0] == m.still_qualifies(g, "TB -150", "MONEYLINE")


def test_underdog_moneyline_runs_up_to_the_longshot_cap():
    m = NFLModel()
    m.team_ratings = {"TB": 0.5, "CLE": 2.0}
    m.hfa = 1.5                                   # a coin flip at TB
    g = _game(spread_line=5.0, home_moneyline=-180, away_moneyline=150)
    p = m.project(g)
    assert p.bet_market == "MONEYLINE" and p.bet_side == "CLE +150"
    low, high = m.bet_range(g, "CLE +150", "MONEYLINE").split(" to ")
    assert high == f"+{m.thresholds.ml_max_underdog}"
    assert low.startswith("CLE ") and float(low.split()[1]) < 150


def test_no_range_when_it_is_not_a_bet_at_its_own_number():
    m = _model()
    assert m.bet_range(_game(spread_line=6.5), "CLE +6.5", "SPREAD") == ""
    assert m.game_adjust == {}


def test_first_sheet_shows_the_range_and_the_qb_rule():
    import pandas as pd
    from openpyxl import Workbook
    from nflmodel.excel import BETS_HEADERS, _sheet_bets
    from nflmodel.model import WITH_PICK
    assert BETS_HEADERS.index("Bet Range") == BETS_HEADERS.index("Still a Bet At") + 1
    long_range = "TB +5.5 (-136) | +6.5 (-158) | +7.5 (-164) | +8.5 (-184) | +9.5 (-200) | +10.5 (-220)"
    slate = pd.DataFrame([dict(home_team="CHI", away_team="TB", home_win_prob=0.4, weekday="Sunday",
                               gametime="20:20", recommendation="BET TB +6.5", bet_type=WITH_PICK,
                               bet_side="TB +6.5", bet_market="SPREAD", bet_odds=-110.0, stake=5.0,
                               bet_chance=0.6, still_bet_at="TB +5.5", bet_range=long_range,
                               bet_why="Model: CHI by 3.2.")])
    wb = Workbook()
    _sheet_bets(wb, slate, 2026, 9, dict(advisory=False, qb_rule=["PHI: Tanner McKee (5 career starts, 3 this season)"]))
    ws = wb["This Week's Bets"]
    cells = {c.value: c for row in ws.iter_rows() for c in row if c.value is not None}
    header = cells["Bet Range"]
    assert header.column_letter == "J" and cells["Why"].column_letter == "K"
    assert cells[long_range].column_letter == "J"
    assert ws.column_dimensions["J"].width >= len(long_range)
    assert cells["Model: CHI by 3.2."].column_letter == "K"
    note = next(v for v in cells if isinstance(v, str) and v.startswith("QB rule"))
    assert "Tanner McKee" in note and cells[note].alignment.wrap_text
