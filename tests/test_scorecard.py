"""The honest scorecard (scorecard.py, closing._fair_move) — added 2026-10-29."""
import sys
sys.path.insert(0, "src")

import pandas as pd
import pytest


@pytest.fixture(scope="module")
def mm():
    from nflmodel.trends import margin_model_for_history
    return margin_model_for_history()


def _close(spread=0.0, h_odds=-110.0, a_odds=-110.0, h_ml=-110.0, a_ml=-110.0):
    return pd.Series(dict(home_team="KC", away_team="DEN", close_spread=spread,
                          close_home_spread_odds=h_odds, close_away_spread_odds=a_odds,
                          close_home_ml=h_ml, close_away_ml=a_ml, close_source="fanduel"))


def test_value_at_price_moneyline_is_ev_at_the_fair_close(mm):
    from nflmodel.scorecard import value_at_price
    ev, p = value_at_price(mm, "MONEYLINE", True, None, 100.0, _close())
    assert p == pytest.approx(0.5) and ev == pytest.approx(0.0)
    ev, _ = value_at_price(mm, "MONEYLINE", True, None, -110.0, _close())
    assert ev == pytest.approx(0.5 * 100 / 110 - 0.5)          # paying the cut


def test_value_at_price_spread_counts_the_number(mm):
    """Getting 3 on a game that closed pick'em is worth a lot; the same number is worth the cut."""
    from nflmodel.scorecard import value_at_price
    same, p = value_at_price(mm, "SPREAD", True, 0.0, -110.0, _close())
    assert p == pytest.approx(0.5, abs=1e-6) and same < 0
    plus3, p3 = value_at_price(mm, "SPREAD", True, 3.0, -110.0, _close())
    assert p3 > 0.55 and plus3 > 0.05
    # from the away side: +3 for DEN is the same bet mirrored (the empirical
    # margin distribution is not perfectly symmetric, so close, not equal)
    away3, _ = value_at_price(mm, "SPREAD", False, 3.0, -110.0, _close())
    assert away3 == pytest.approx(plus3, abs=0.01)


def test_value_at_price_needs_a_close(mm):
    from nflmodel.scorecard import value_at_price
    assert value_at_price(mm, "MONEYLINE", True, None, 120.0, None) == (None, None)


def test_moneyline_clv_is_devigged_at_both_ends():
    from nflmodel.closing import _fair_move
    close = _close(h_ml=-150.0, a_ml=130.0)
    move = _fair_move(True, -110.0, -110.0, close)
    fair_close = (150 / 250) / (150 / 250 + 100 / 230)
    assert move == pytest.approx(fair_close - 0.5)
    assert _fair_move(False, -110.0, -110.0, close) == pytest.approx(-(fair_close - 0.5))
    assert _fair_move(True, None, -110.0, close) is None


def test_close_favorite_uses_moneyline_on_a_pickem():
    from nflmodel.scorecard import _close_favorite
    assert _close_favorite(_close(spread=3.0), "KC", "DEN") == "KC"
    assert _close_favorite(_close(spread=-2.5), "KC", "DEN") == "DEN"
    assert _close_favorite(_close(spread=0.0, h_ml=-115.0, a_ml=-105.0), "KC", "DEN") == "KC"
    assert _close_favorite(None, "KC", "DEN") is None


def test_bet_slices_cover_every_bet_once_per_group():
    from nflmodel.scorecard import slice_bets
    b = pd.DataFrame(dict(
        market=["SPREAD", "SPREAD", "MONEYLINE", "MONEYLINE"],
        odds=[-110.0, -105.0, -170.0, 205.0], line=[-3.0, 4.5, None, None],
        edge=[1.8, 3.6, 0.04, 0.09], favorite=[True, False, True, False],
        out=["W", "L", "W", "P"], units=[100 / 110, -1.0, 100 / 170, 0.0],
        value_at_close=[-0.02, 0.01, -0.03, None]))
    sl = slice_bets(b)
    for group in ("market", "side", "price", "edge"):
        assert sl[sl.group == group].n.sum() == len(b)
    sp = sl[(sl.group == "market") & (sl.slice == "spreads")].iloc[0]
    assert (sp.won, sp.lost, sp.push) == (1, 1, 0)
    assert set(sl[sl.group == "edge"].slice) == {"spread edge 1.5-2.5", "spread edge 3.5+",
                                                 "ML edge 3-5%", "ML edge 8%+"}


def test_ledger_lists_every_bet_and_leaves_unplayed_ones_blank(tmp_path, monkeypatch):
    """The graded ledger (expert review round 2): settled and pending bets, $5 P&L."""
    import pandas as pd
    from nflmodel import archive, scorecard
    from nflmodel.market import MarginModel
    leans = pd.DataFrame([
        dict(game_id="g1", home_team="KC", away_team="DEN", spread_line=3.0,
             projected_margin=6.0, home_win_prob=0.7, home_ml=-170, away_ml=145,
             ml_edge_home=0.02, ml_edge_away=-0.02, spread_edge_pts=3.0,
             bet_market="SPREAD", bet_side="KC -3.0", bet_odds=-110, confidence="High",
             stake=5.0, home_spread_odds=-110, away_spread_odds=-110, still_bet_at="KC -4.5"),
        dict(game_id="g2", home_team="NYG", away_team="WAS", spread_line=-1.0,
             projected_margin=1.0, home_win_prob=0.55, home_ml=105, away_ml=-125,
             ml_edge_home=0.06, ml_edge_away=-0.06, spread_edge_pts=2.0,
             bet_market="MONEYLINE", bet_side="NYG +105", bet_odds=105, confidence="High"),
    ])
    games = pd.DataFrame([
        dict(season=2026, week=9, home_team="KC", away_team="DEN", result=7.0),
        dict(season=2026, week=9, home_team="NYG", away_team="WAS", result=None),
    ])
    monkeypatch.setattr(archive, "load_archived", lambda s, w: (None, leans))
    monkeypatch.setattr(scorecard, "load_closing", lambda *a, **k: None)
    led = scorecard.bet_ledger(2026, [9], games, MarginModel(sigma=13.2))
    assert list(led.columns) == scorecard.LEDGER_COLS
    kc, nyg = led.iloc[0], led.iloc[1]
    assert (kc.out, kc.pnl_at_5, kc.stake, kc.still_bet_at) == ("W", 4.55, 5.0, "KC -4.5")
    assert kc.line == -3.0 and kc.home_spread_odds == -110
    assert nyg.out == "" and pd.isna(nyg.pnl_at_5) and pd.isna(nyg.stake)
    assert abs(nyg.p_model - 0.55) < 1e-9
