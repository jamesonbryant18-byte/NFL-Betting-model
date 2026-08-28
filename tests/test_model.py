"""
Invariant tests. Run: .venv/bin/python -m pytest tests/ -q

The leakage test is the important one. Everything else in this repo is
worthless if the model can see the games it is being scored on.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import numpy as np
import pandas as pd
import pytest

from nflmodel.market import (american_to_prob, prob_to_american, devig,
                             kelly_stake, MarginModel, vig_pct)
from nflmodel.ratings import fit_ratings_qb, _time_index
from nflmodel.config import RATINGS, CACHE_DIR
from nflmodel.adjustments import total_adjustment


# ── odds conversion ──────────────────────────────────────────────

def test_american_prob_roundtrip():
    for odds in (-350, -180, -110, 100, 145, 400):
        assert prob_to_american(american_to_prob(odds)) == pytest.approx(odds, abs=1e-6)


def test_favorite_more_likely_than_dog():
    assert american_to_prob(-200) > 0.5 > american_to_prob(150)


# ── de-vigging ───────────────────────────────────────────────────

@pytest.mark.parametrize('method', ['multiplicative', 'power', 'shin'])
def test_devig_sums_to_one(method):
    for a, b in ((-110, -110), (-400, 320), (-150, 130), (200, -240)):
        p, q = devig(a, b, method)
        assert p + q == pytest.approx(1.0, abs=1e-9)
        assert 0 < p < 1 and 0 < q < 1


def test_devig_symmetric_market_is_coinflip():
    p, q = devig(-110, -110)
    assert p == pytest.approx(0.5) and q == pytest.approx(0.5)


def test_raw_odds_overstate_probability():
    """The whole reason de-vigging exists."""
    raw = american_to_prob(-110) * 2
    assert raw > 1.0
    assert vig_pct(-110, -110) == pytest.approx(4.76, abs=0.01)


# ── staking ──────────────────────────────────────────────────────

def test_kelly_refuses_losing_bet():
    # -110 breaks even at 52.38%; 52% must not be staked.
    stake, full = kelly_stake(0.52, -110, 1000.0)
    assert stake == 0.0 and full < 0


def test_kelly_respects_cap():
    stake, full = kelly_stake(0.95, -110, 1000.0)
    assert full > 0.5              # Kelly wants an enormous bet
    assert stake <= 1000.0 * 0.025 # the cap must bind


def test_kelly_scales_with_bankroll():
    a, _ = kelly_stake(0.60, -110, 1000.0)
    b, _ = kelly_stake(0.60, -110, 2000.0)
    assert b == pytest.approx(2 * a, rel=0.02)


def test_push_does_not_dilute_stake():
    """A push returns the stake, so it must not be treated as a partial loss."""
    no_push, _ = kelly_stake(0.55, -110, 1000.0, push_prob=0.0)
    with_push, _ = kelly_stake(0.55 * 0.97, -110, 1000.0, push_prob=0.03)
    assert with_push >= no_push * 0.98


# ── margin model ─────────────────────────────────────────────────

def test_cover_probs_sum_to_one():
    mm = MarginModel(residuals=np.random.default_rng(0).normal(0, 13.2, 5000))
    for line in (-7, -3.5, 0, 2.5, 3, 10):
        h, p, a = mm.cover_prob(1.5, line)
        assert h + p + a == pytest.approx(1.0, abs=1e-9)


def test_whole_number_line_has_push_mass():
    mm = MarginModel(residuals=np.random.default_rng(0).normal(0, 13.2, 20000))
    _, push_int, _ = mm.cover_prob(2.0, 3.0)
    _, push_half, _ = mm.cover_prob(2.0, 3.5)
    assert push_int > 0.01     # integer lines really do push
    assert push_half == 0.0    # half-point lines cannot


def test_bigger_projection_means_higher_cover():
    mm = MarginModel(residuals=np.random.default_rng(0).normal(0, 13.2, 5000))
    assert mm.cover_prob(7.0, 3.0)[0] > mm.cover_prob(1.0, 3.0)[0]


def test_win_prob_monotonic_and_centered():
    mm = MarginModel(residuals=np.random.default_rng(0).normal(0, 13.2, 20000))
    assert mm.win_prob(0.0) == pytest.approx(0.5, abs=0.02)
    assert mm.win_prob(10.0) > mm.win_prob(3.0) > mm.win_prob(-3.0)


# ── adjustments ──────────────────────────────────────────────────

def test_adjustments_ship_at_zero():
    """They were measured and rejected; a nonzero default is a regression."""
    game = dict(home_team='SEA', away_team='MIA', home_rest=13, away_rest=4,
                wind=30, roof='outdoors', week=17)
    assert total_adjustment(game) == 0.0


# ── the one that matters ─────────────────────────────────────────

@pytest.mark.skipif(not (CACHE_DIR / 'dataset_2010_2025.parquet').exists(),
                    reason='dataset not built')
def test_no_future_leakage():
    """
    Ratings fit as of a given week must be bit-identical whether or not the
    future exists in the input frame. If deleting every later game changes the
    answer, the model is reading the future and every backtest number is fake.
    """
    df = pd.read_parquet(CACHE_DIR / 'dataset_2010_2025.parquet')

    full = fit_ratings_qb(df, 2022, 10, RATINGS)
    cutoff = 2022 * RATINGS.offseason_weeks_equiv + 10
    truncated_df = df[_time_index(df.season, df.week, RATINGS) < cutoff]
    truncated = fit_ratings_qb(truncated_df, 2022, 10, RATINGS)

    assert full[2] == pytest.approx(truncated[2], abs=1e-9)   # HFA
    for team in full[0]:
        assert full[0][team] == pytest.approx(truncated[0][team], abs=1e-9)


@pytest.mark.skipif(not (CACHE_DIR / 'dataset_2010_2025.parquet').exists(),
                    reason='dataset not built')
def test_ratings_are_centered_and_bounded():
    df = pd.read_parquet(CACHE_DIR / 'dataset_2010_2025.parquet')
    teams, qbs, hfa = fit_ratings_qb(df, 2025, 10, RATINGS)
    vals = np.array(list(teams.values()))
    assert abs(vals.mean()) < 1e-9          # centered on league average
    assert vals.max() < 20 and vals.min() > -20
    assert 0 < hfa < 5                       # a sane home field number
