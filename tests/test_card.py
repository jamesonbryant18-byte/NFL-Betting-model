"""
The weekly card. Jameson, 2026-10-07: "10 bets seems absurd ... I really
only want the most confident ones ... at least 4 total a week and at the
most like 7 or 8 ... dont force a primteime bet."

Pinned here: the card keeps the card_max bets most likely to WIN (pushes left
out), cut bets are fully cleared, bets already placed on games that kicked off
use slots, and a thin week is topped up to card_min only with positive-EV
near misses, each labeled filler.
"""
import os
import sys
from dataclasses import replace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import numpy as np
import pandas as pd
import pytest

from nflmodel.config import STAKING
from nflmodel.model import NFLModel, bet_chance


def _row(i, p_cover, bet=True, edge=2.0, push=0.0, wp=0.6, hml=None, aml=None,
         e_h=np.nan, e_a=np.nan):
    """A home-side game; with bet=True, a qualifying home spread bet."""
    side = f"H{i} +3.5"
    return {
        "game_id": f"g{i}", "home_team": f"H{i}", "away_team": f"A{i}",
        "projected_margin": -3.5 + edge, "spread_line": -3.5,
        "home_cover_prob": p_cover, "push_prob": push,
        "away_cover_prob": 1 - p_cover - push, "spread_edge_pts": edge,
        "home_win_prob": wp, "home_ml": hml, "away_ml": aml,
        "ml_edge_home": e_h, "ml_edge_away": e_a,
        "recommendation": f"BET {side}" if bet else "NO BET",
        "bet_market": "SPREAD" if bet else "", "bet_side": side if bet else "",
        "bet_odds": -110.0 if bet else 0.0, "stake": 5.0 if bet else 0.0,
        "confidence": "Medium", "bet_type": "x" if bet else "", "bet_why": "y" if bet else "",
    }


def _run(rows, staking=STAKING, card_used=0):
    m = NFLModel(staking=staking)
    it = iter(rows)

    class _P:
        def __init__(self, r):
            self.r = r

        def as_row(self):
            return self.r
    m.project = lambda g: _P(next(it))
    games = pd.DataFrame({"game_id": [r["game_id"] for r in rows],
                          "home_spread_odds": -110.0, "away_spread_odds": -110.0})
    return m.project_slate(games, advisory=False, card_used=card_used)


def test_defaults_are_his_numbers():
    assert STAKING.card_max == 7 and STAKING.card_min == 4


def test_card_keeps_the_seven_most_likely_to_win():
    covers = [0.55 + 0.01 * i for i in range(10)]          # 10 qualifying bets
    df = _run([_row(i, p) for i, p in enumerate(covers)])
    on = df[df.bet_side != ""]
    assert len(on) == 7
    assert sorted(on.home_cover_prob.round(2)) == [round(0.55 + 0.01 * i, 2) for i in range(3, 10)]
    cut = df[df.card.str.startswith("cut")]
    assert len(cut) == 3
    # A cut bet is fully cleared: no side, price or stake left to act on.
    assert (cut.recommendation == "NO BET").all() and (cut.stake == 0).all()
    assert (cut.bet_market == "").all() and (cut.bet_odds == 0).all()
    assert set(cut.card) == {"cut: H0 +3.5", "cut: H1 +3.5", "cut: H2 +3.5"}


def test_bets_already_placed_use_card_slots():
    df = _run([_row(i, 0.55 + 0.01 * i) for i in range(10)], card_used=3)
    assert (df.bet_side != "").sum() == 4


def test_pushes_do_not_count_as_wins_or_losses():
    r = _row(0, 0.50, push=0.10)
    assert bet_chance(pd.Series(r)) == pytest.approx(0.50 / 0.90)
    # Moneyline: the side's win chance.
    ml = {**r, "bet_market": "MONEYLINE", "bet_side": "A0 +150", "home_win_prob": 0.62}
    assert bet_chance(pd.Series(ml)) == pytest.approx(0.38)


def test_thin_week_is_topped_up_only_with_positive_ev_near_misses():
    rows = [_row(0, 0.60), _row(1, 0.58),                  # 2 qualifying
            _row(2, 0.54, bet=False, edge=1.0),            # +EV at -110: fills
            _row(3, 0.51, bet=False, edge=1.0),            # -EV at -110: never
            _row(4, 0.40, bet=False, edge=-1.0)]           # away side 0.60: fills
    df = _run(rows)
    on = df[df.bet_side != ""]
    assert len(on) == 4
    filler = df[df.card == "filler"]
    assert set(filler.game_id) == {"g2", "g4"}
    assert (filler.confidence == "Filler").all() and (filler.stake == 5.0).all()
    assert filler.bet_why.str.contains("FILLER").all()
    assert df.loc[df.game_id == "g4", "bet_side"].item() == "A4 -3.5"
    assert df.loc[df.game_id == "g3", "bet_side"].item() == ""


def test_no_negative_ev_filler_even_if_short_of_the_minimum():
    df = _run([_row(0, 0.60), _row(1, 0.51, bet=False, edge=1.0)])
    assert (df.bet_side != "").sum() == 1


def test_card_off_keeps_every_qualifying_bet():
    df = _run([_row(i, 0.55 + 0.01 * i) for i in range(10)],
              staking=replace(STAKING, card_max=None))
    assert (df.bet_side != "").sum() == 10
