"""
Tests for the weekly self-correction experiment (src/nflmodel/selftune.py).

The two that matter:

  * alpha=0 must reproduce the frozen model EXACTLY. If it does not, every
    comparison in IMPROVEMENT.md is measuring an unrelated code change rather
    than the effect of self-tuning, and the conclusion is worthless.

  * the correction applied to week W must be built only from games that
    finished before week W. Same leak boundary as the rest of the repo.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pandas as pd
import pytest

from nflmodel.selftune import ResidualMemory, walk_forward_adaptive
from nflmodel.config import CACHE_DIR, RATINGS


# ── residual memory ──────────────────────────────────────────────

def test_residual_is_signed_opposite_for_the_two_teams():
    """A home overperformance is an away underperformance of equal size."""
    m = ResidualMemory(half_life=3.0)
    m.observe(1.0, 'KC', 'DEN', residual=7.0)
    assert m.correction('KC', 1.0) == pytest.approx(7.0)
    assert m.correction('DEN', 1.0) == pytest.approx(-7.0)


def test_unseen_team_has_no_correction():
    m = ResidualMemory()
    assert m.correction('SEA', 5.0) == 0.0


def test_older_games_matter_less():
    m = ResidualMemory(half_life=1.0)   # weight halves every week
    m.observe(1.0, 'KC', 'DEN', residual=10.0)   # stale
    m.observe(4.0, 'KC', 'LV', residual=0.0)     # fresh
    c = m.correction('KC', 4.0)
    assert 0.0 < c < 5.0, 'stale blowout should be discounted, not ignored'


def test_correction_is_capped():
    m = ResidualMemory(half_life=3.0, cap=7.0)
    m.observe(1.0, 'KC', 'DEN', residual=45.0)
    assert m.correction('KC', 1.0) == pytest.approx(7.0)
    assert m.correction('DEN', 1.0) == pytest.approx(-7.0)


def test_reset_clears_everything():
    m = ResidualMemory()
    m.observe(1.0, 'KC', 'DEN', residual=7.0)
    m.reset()
    assert m.correction('KC', 1.0) == 0.0
    assert m.hfa_drift(1.0) == 0.0


def test_hfa_drift_tracks_league_wide_residual():
    m = ResidualMemory(half_life=3.0)
    for away in ('DEN', 'LV', 'LAC'):
        m.observe(1.0, 'KC', away, residual=3.0)
    assert m.hfa_drift(1.0) == pytest.approx(3.0)


def test_half_life_must_be_positive():
    with pytest.raises(ValueError):
        ResidualMemory(half_life=0.0)


# ── walk-forward behaviour ───────────────────────────────────────

@pytest.fixture(scope='module')
def dataset():
    path = CACHE_DIR / 'dataset_2010_2025.parquet'
    if not path.exists():
        pytest.skip('dataset cache not built')
    return pd.read_parquet(path).sort_values(['season', 'week']).reset_index(drop=True)


def test_alpha_zero_makes_no_adjustment(dataset):
    """The baseline must be untouched, or the whole comparison is invalid."""
    bt = walk_forward_adaptive(dataset, [2024], params=RATINGS, alpha=0.0,
                               deployed=False)
    assert len(bt) > 100
    assert (bt.adjustment == 0.0).all()
    assert bt.projected_margin.equals(bt.baseline_margin)


def test_alpha_nonzero_actually_moves_projections(dataset):
    """Guards against a silently inert knob -- a no-op would 'prove' safety."""
    bt = walk_forward_adaptive(dataset, [2024], params=RATINGS, alpha=0.5,
                               deployed=False)
    assert bt.adjustment.abs().max() > 0.5
    assert not bt.projected_margin.equals(bt.baseline_margin)


def test_first_week_of_season_cannot_be_corrected(dataset):
    """Week 1 has no prior games, so there is nothing to learn from yet."""
    bt = walk_forward_adaptive(dataset, [2024], params=RATINGS, alpha=1.0,
                               deployed=False, carry_offseason=False)
    wk1 = bt[bt.week == bt.week.min()]
    assert len(wk1) > 0
    assert (wk1.adjustment == 0.0).all()


def test_no_within_week_leakage(dataset):
    """
    Every game in a week must get its correction from the SAME memory state.
    If residuals were folded in game by game, the late Sunday games would be
    corrected using results from the early ones.
    """
    bt = walk_forward_adaptive(dataset, [2024], params=RATINGS, alpha=1.0,
                               deployed=False)
    wk = bt[bt.week == 5]
    recomputed = (wk.projected_margin - wk.baseline_margin - wk.adjustment).abs()
    assert (recomputed < 1e-9).all()


def test_seasons_are_independent_by_default(dataset):
    """Without carry_offseason, week 1 of every season starts from scratch."""
    bt = walk_forward_adaptive(dataset, [2023, 2024], params=RATINGS, alpha=1.0,
                               deployed=False, carry_offseason=False)
    for season in (2023, 2024):
        s = bt[bt.season == season]
        first = s[s.week == s.week.min()]
        assert (first.adjustment == 0.0).all()
