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


# ── regression: the sign bug that printed the wrong side of every game ──

from nflmodel.market import format_spread


def test_ticket_sign_matches_the_real_bet():
    """
    spread_line is 'points the home team is favored by'; a ticket shows the
    negation. A 7-point home favorite must read '-7.0', never '+7.0'. This
    shipped inverted once and printed the opposite side of every game.
    """
    assert format_spread("DET", 7.0) == "DET -7.0"     # favored lays points
    assert format_spread("NO", -7.0) == "NO +7.0"      # dog takes points
    assert format_spread("IND", -3.5) == "IND +3.5"
    assert format_spread("BAL", 3.5) == "BAL -3.5"


def test_recommendation_prints_favorite_as_laying_points():
    from nflmodel.model import NFLModel
    m = NFLModel()
    m.team_ratings = {"DET": 6.0, "NO": -2.0}
    m.hfa = 2.0
    rec = m._recommend(
        projected=12.0, line=7.0, spread_edge=5.0,
        p_home=0.62, p_push=0.03, p_away=0.35,
        home_wp=0.80, h_ml=-305, a_ml=245,
        ml_edge_h=0.0, ml_edge_a=0.0, home="DET", away="NO",
    )
    # Model likes the home favorite -> the ticket must LAY the points.
    assert "DET -7.0" in rec["recommendation"], rec["recommendation"]


def test_market_ratings_respect_asof_cutoff():
    """Replaying a finished season must not see later weeks' closing lines."""
    import pandas as pd
    from nflmodel.ratings import fit_market_ratings
    from nflmodel.data import load_games
    g = load_games()
    if (g.season == 2025).sum() < 100:
        pytest.skip("2025 not loaded")
    full, _ = fit_market_ratings(g, 2025)
    early, _ = fit_market_ratings(g, 2025, asof_week=3)
    assert any(abs(full[t] - early[t]) > 1e-6 for t in full), \
        "asof_week had no effect — the leak guard is not working"


# ── key numbers ──────────────────────────────────────────────────

def test_key_numbers_are_actually_modeled():
    """
    A margin of exactly 3 is far more likely than exactly 4. An earlier
    version reported a flat ~3.3% push at every line, which is wrong by
    roughly 9x on a three-point spread.
    """
    from nflmodel.market import MarginModel
    from nflmodel.data import load_games
    g = load_games()
    hist = g[g.played & g.result.notna()]
    if len(hist) < 1000:
        pytest.skip('games not loaded')

    mm = MarginModel(margins=hist.result.values)
    push3 = mm.cover_prob(3.0, 3.0)[1]
    push4 = mm.cover_prob(3.0, 4.0)[1]
    assert push3 > 2.5 * push4, f'key number 3 not modeled: {push3:.4f} vs {push4:.4f}'

    push7 = mm.cover_prob(3.0, 7.0)[1]
    push8 = mm.cover_prob(3.0, 8.0)[1]
    assert push7 > push8

    h, p, a = mm.cover_prob(2.5, 3.0)
    assert abs(h + p + a - 1.0) < 1e-9


# ── odds / line shopping ─────────────────────────────────────────

def test_line_shopping_guard_rejects_outliers():
    """
    A single mis-signed book in a feed produced a phantom 3-point 'better
    line'. With a 1.5pt betting threshold that manufactures bets out of a
    data error, so the median guard must reject it.
    """
    import pandas as pd
    from nflmodel.odds import best_lines
    def row(book, spread, so=-110, aso=-110):
        return {'game': 'GB@MIN', 'book': book, 'spread': spread,
                'spread_odds': so, 'away_spread_odds': aso,
                'home_ml': -120, 'away_ml': 100, 'home_team': 'MIN',
                'away_team': 'GB', 'source': 'action_network'}

    df = pd.DataFrame([
        row('draftkings', 1.5), row('fanduel', 1.5, -108, -112),
        row('caesars', 2.0),
        row('betmgm', -1.5),          # sign-inverted feed row
    ])
    guarded = best_lines(df, max_dev=1.0)
    assert not guarded.empty
    best = float(guarded.iloc[0]['best_home_spread'])
    assert best >= 1.0, f'outlier not rejected: best_home_spread={best}'


def test_deployed_model_is_leak_free():
    """
    The FULL deployed path (NFLModel + market prior) must be invariant to
    whether future games exist in the input.

    This is the test that matters most in the repo. A missing as-of cutoff in
    the market prior once moved ratings by 0.8 points and produced a 56% ATS
    hold-out result that was entirely fabricated.
    """
    import pandas as pd
    from nflmodel.model import NFLModel
    from nflmodel.ratings import _time_index

    if not (CACHE_DIR / 'dataset_2010_2025.parquet').exists():
        pytest.skip('dataset not built')

    df = pd.read_parquet(CACHE_DIR / 'dataset_2010_2025.parquet') \
           .sort_values(['season', 'week']).reset_index(drop=True)
    season, week = 2023, 10

    full = NFLModel().fit(df, season, week, market_games=df)

    cut = season * RATINGS.offseason_weeks_equiv + week
    trunc = df[_time_index(df.season, df.week, RATINGS) < cut]
    truncated = NFLModel().fit(trunc, season, week, market_games=trunc)

    for team in full.team_ratings:
        assert full.team_ratings[team] == pytest.approx(
            truncated.team_ratings[team], abs=1e-9), f'{team} leaks future data'
    assert full.hfa == pytest.approx(truncated.hfa, abs=1e-9)
