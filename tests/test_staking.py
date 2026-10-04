"""
Flat stakes. Jameson, 2026-09-30: "my stake is going to be the same every
single game ... Its always going to be 5 dollars."

Pinned here: every recommended bet is exactly $5; the weekly cap no longer
cuts qualifying bets; and WHICH bets qualify is unchanged -- the edge
thresholds plus the Kelly yes/no test still decide that.
"""
import os
import sys
from dataclasses import replace
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import numpy as np

from nflmodel.config import STAKING
from nflmodel.model import NFLModel


def _recommend(m, edge_pts, p_cover, p_push=0.0, odds=-110.0):
    """A home-side spread candidate with the given edge and cover chance."""
    return m._recommend(
        projected=-3.0 + edge_pts, line=-3.0, spread_edge=edge_pts,
        p_home=p_cover, p_push=p_push, p_away=1 - p_cover - p_push,
        home_wp=0.5, h_ml=None, a_ml=None, ml_edge_h=np.nan, ml_edge_a=np.nan,
        home="NYG", away="TEN", home_spread_odds=odds, away_spread_odds=odds)


def test_default_is_a_flat_five_dollars():
    assert STAKING.flat_stake == 5.0


def test_every_qualifying_bet_is_exactly_the_flat_stake():
    m = NFLModel()
    strong = _recommend(m, edge_pts=4.0, p_cover=0.70)     # Kelly would say $25
    modest = _recommend(m, edge_pts=1.6, p_cover=0.545)    # Kelly would say ~$5
    assert strong["recommendation"].startswith("BET") and strong["stake"] == 5.0
    assert modest["recommendation"].startswith("BET") and modest["stake"] == 5.0


def test_qualification_is_unchanged_by_the_flat_stake():
    flat, kelly = NFLModel(), NFLModel(staking=replace(STAKING, flat_stake=None))
    for edge, p in [(1.4, 0.70), (1.6, 0.525), (1.6, 0.53), (1.6, 0.545),
                    (2.5, 0.56), (4.0, 0.70)]:
        a, b = _recommend(flat, edge, p), _recommend(kelly, edge, p)
        assert a["recommendation"] == b["recommendation"], (edge, p)
    # Below the edge threshold, or a price that leaves too little, is no bet.
    assert _recommend(flat, 1.4, 0.70)["recommendation"] == "NO BET"
    assert _recommend(flat, 1.6, 0.525)["recommendation"] == "NO BET"


def _slate_model(staking, n_bets=25):
    m = NFLModel(staking=staking)
    rows = [{"spread_edge_pts": 5.0 - i * 0.1, "recommendation": f"BET T{i} +3.5",
             "stake": staking.flat_stake or 25.0, "bet_market": "SPREAD",
             "bet_side": f"T{i} +3.5", "bet_type": "x", "bet_why": "y",
             "bet_odds": -110.0} for i in range(n_bets)]
    it = iter(rows)
    m.project = lambda g: SimpleNamespace(as_row=lambda r=next(it): r)
    return m, [None] * n_bets


def test_weekly_cap_does_not_cut_bets_at_a_flat_stake():
    import pandas as pd
    m, games = _slate_model(STAKING)
    df = m.project_slate(pd.DataFrame({"g": games}), advisory=False)
    assert (df["stake"] == 5.0).all() and len(df) == 25
    assert df["recommendation"].str.startswith("BET").all()


def test_weekly_cap_still_binds_for_kelly_stakes():
    import pandas as pd
    m, games = _slate_model(replace(STAKING, flat_stake=None))
    df = m.project_slate(pd.DataFrame({"g": games}), advisory=False)
    assert df["stake"].sum() == STAKING.bankroll * STAKING.max_weekly_exposure_pct
    assert (df["recommendation"] == "NO BET").sum() == 21
