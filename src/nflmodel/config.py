"""
NFL Betting Model — config.py

TO UPDATE: every tunable in the model lives here. Nothing else is hardcoded.

Values marked [FITTED] are set by the backtest (scripts/run_backtest.py) and
should not be hand-edited — rerun the backtest instead. Values marked [YOURS]
are personal preferences and are safe to change at any time.
"""

from dataclasses import dataclass
from pathlib import Path

# ─────────────────────────────────────────────
# PATHS — resolved relative to the repo, never absolute
# ─────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / "data" / "cache"
OUTPUT_DIR = REPO_ROOT / "output"
PARAMS_FILE = REPO_ROOT / "data" / "fitted_params.json"

# ─────────────────────────────────────────────
# SEASON
# ─────────────────────────────────────────────

CURRENT_SEASON = 2026

# Seasons used to fit and validate the model. 2010+ keeps us in the modern
# scoring era while still giving ~4,300 games.
TRAIN_SEASON_START = 2010
TRAIN_SEASON_END = 2025

# ─────────────────────────────────────────────
# BANKROLL & STAKING  [YOURS]
# ─────────────────────────────────────────────

# ADVISORY MODE — the default, and deliberately so.
#
# The hold-out backtest found no edge against closing lines (see README).
# In advisory mode the model still computes and shows everything, but it
# reports LEANs rather than BETs and stakes nothing. Flip this to False to
# stake real money; nothing else changes.
ADVISORY_MODE = True


@dataclass
class Staking:
    bankroll: float = 1000.00        # starting bankroll
    kelly_fraction: float = 0.50     # half-Kelly
    max_bet_pct: float = 0.025       # hard cap: 2.5% of bankroll, whatever Kelly says
    min_bet: float = 5.00            # don't bother below this
    round_to: float = 1.00           # round stakes to nearest dollar

    # Cap on total exposure across a single week's slate. Without this, a
    # model that likes 13 of 16 games happily risks a third of the bankroll
    # in an afternoon. Bets are taken strongest-edge-first until the cap binds.
    max_weekly_exposure_pct: float = 0.10


STAKING = Staking()

# ─────────────────────────────────────────────
# BET TRIGGERS  [YOURS]
# ─────────────────────────────────────────────

@dataclass
class Thresholds:
    # Spread bets are thresholded in POINTS of disagreement with the line,
    # which is the natural unit for a margin model.
    spread_min_edge_pts: float = 1.5
    spread_strong_edge_pts: float = 3.0

    # Moneyline bets are thresholded in probability, after de-vigging.
    ml_min_edge: float = 0.030
    ml_strong_edge: float = 0.060

    # Ignore moneylines longer than this — the model is not calibrated out
    # in the tails and the vig is punishing.
    ml_max_favorite: int = -350
    ml_max_underdog: int = 600


THRESHOLDS = Thresholds()

# ─────────────────────────────────────────────
# RATINGS ENGINE  [FITTED]
# ─────────────────────────────────────────────

@dataclass
class RatingsParams:
    # ── The four values below are FITTED. They are set to the grid-search
    # winners so this file describes the model that actually runs; the frozen
    # data/fitted_params.json should agree with them, not silently override.

    # Ridge penalty on team ratings. Higher = more shrinkage toward league
    # average, which matters enormously in the small-sample early season.
    ridge_lambda: float = 6.0

    # Exponential recency decay. Weight of a game N weeks old is decay ** N.
    recency_decay: float = 0.98

    # The regression target blends actual scoring margin with an EPA-implied
    # margin. FITTED TO ZERO: the grid search preferred pure scoring margin,
    # and accuracy degrades monotonically as this rises (10.19 -> 10.35). The
    # ridge's opponent adjustment already captures what EPA was meant to add.
    # At zero, build_dataset skips the ~14MB/season play-by-play pull entirely.
    epa_margin_weight: float = 0.0

    # Points of margin per unit of team EPA-per-play differential.
    # Fitted on 2010-2025: result = 30.6 * net_epa + 1.73
    epa_to_points: float = 30.6

    # Home-field content of the EPA-implied margin. EPA/play captures only
    # ~0.6 pts of home advantage while actual margin carries ~2.3, so the
    # EPA component must be re-centered by this intercept before blending or
    # the fitted HFA comes out about a point too low.
    epa_home_intercept: float = 1.73

    # Ridge penalty for the market-implied fit. Much smaller than the
    # performance fit: a posted spread is the market's point estimate, not a
    # noisy observation of it, so there is little to shrink away.
    market_ridge_lambda: float = 1.0

    # An offseason is worth this many weeks of recency decay. Controls how
    # much of last season carries into this one -- at decay 0.98 and 70 weeks,
    # a game from the same week last year keeps ~24% weight.
    offseason_weeks_equiv: float = 70.0

    # How much of the preseason prior comes from market-implied ratings
    # (backed out of posted spreads) vs. regressed prior-season performance.
    #
    # Set high on principle rather than fitted: in Week 1 the model has
    # literally zero information about the current season, while the market
    # has priced every trade, draft pick, retirement and depth chart. Deferring
    # to it is not timidity, it is the only defensible prior. This decays to
    # nothing as real games accumulate.
    market_prior_weight: float = 0.80

    # Games of current-season data at which the prior is fully washed out.
    prior_decay_games: float = 10.0


RATINGS = RatingsParams()

# ─────────────────────────────────────────────
# HOME FIELD  [FITTED]
# ─────────────────────────────────────────────

# League-wide home field advantage in points. Modern NFL HFA is much smaller
# than the folk-wisdom 3 points; this gets refit from the training seasons.
HFA_BASE = 1.70

# Per-team HFA deltas, added to HFA_BASE. Fitted, heavily shrunk toward zero
# because per-team home edges are mostly noise over any sample we have.
# Populated by the backtest; empty means every team gets HFA_BASE.
HFA_TEAM_DELTAS: dict = {}

# Neutral-site games (international, Super Bowl) get no home field.
NEUTRAL_HFA = 0.0

# ─────────────────────────────────────────────
# SITUATIONAL ADJUSTMENTS  [FITTED]
# ─────────────────────────────────────────────

@dataclass
class Adjustments:
    """
    Situational adjustments, all defaulting to ZERO.

    These are not zero because they were never built -- they are zero because
    they were measured against 5,431 games of closing lines and none of them
    showed mispricing at even |t| = 2. See adjustments.py for the full table
    and scripts/measure_situational.py to reproduce it.

    Set any of these nonzero only if a fresh measurement justifies it.
    """
    # ── Rest ──  measured: off-bye t=-0.44/-1.33, short week t=-0.27/-0.26
    rest_pts_per_day: float = 0.0
    rest_max_adjustment: float = 1.5
    off_bye_bonus: float = 0.0
    short_week_penalty: float = 0.0

    # ── Travel & body clock ──  measured: 2+ zone crossings t=+1.15/-1.46
    timezone_pts_per_zone: float = 0.0
    early_kickoff_west_penalty: float = 0.0
    international_travel_penalty: float = 0.0

    # ── Weather ──  measured: wind>=15 t=+0.24, wind>=20 t=-0.44, cold t=+1.33
    wind_threshold_mph: float = 15.0
    wind_margin_compression: float = 0.0
    dome_no_weather: bool = True

    # ── Late-season motivation ──  measured: wk17 t=+1.35, wk17-18 t=+1.45
    motivation_weeks: tuple = (17, 18)
    motivation_max_adjustment: float = 0.0

    # ── QB ── handled in the RATINGS fit, not here. Left for reference only.
    qb_backup_penalty: float = 0.0
    qb_max_adjustment: float = 8.0


ADJUSTMENTS = Adjustments()

# ─────────────────────────────────────────────
# MARKET / PROBABILITY  [FITTED]
# ─────────────────────────────────────────────

@dataclass
class Market:
    # Standard deviation of (actual margin - projected margin). The NFL's
    # long-run figure is ~13.2. Refit from backtest residuals.
    margin_sigma: float = 13.2

    # Use the empirical residual distribution rather than a normal curve.
    # This is what captures the spikes at 3 and 7 that a normal misses.
    use_empirical_residuals: bool = True

    # De-vig method for converting two-way odds into fair probabilities.
    # "multiplicative" (normalize to sum 1), "shin" (accounts for insider
    # money, better on lopsided markets), or "power".
    devig_method: str = "multiplicative"


MARKET = Market()

# ─────────────────────────────────────────────
# ODDS SOURCE  [YOURS]
# ─────────────────────────────────────────────

# The Odds API key, read from the environment (never commit a key).
#   export ODDS_API_KEY="..."
# Falls back to ESPN's free endpoint when unset.
ODDS_API_ENV_VAR = "ODDS_API_KEY"
ODDS_API_REGION = "us"
ODDS_API_MARKETS = "spreads,h2h"

# Books to pull. Empty list = all available; we always flag the best number.
BOOKS: list = []

# ─────────────────────────────────────────────
# VALIDATION BAR
# ─────────────────────────────────────────────

# The model has to clear these on held-out seasons before it's worth betting.
# -110 spread juice breaks even at 52.38%.
MIN_ATS_WIN_RATE = 0.5238
MIN_CLV_POSITIVE = True
