"""
adjustments.py — situational adjustments to the projected margin.

READ THIS BEFORE TURNING ANY OF THESE ON.

Every coefficient in this file was measured against the closing line on 5,431
games from 2006-2025, and essentially all of them came back at zero. The test
that matters is not "does rest predict the final margin" -- of course it does,
and the market knows it. The test is "does rest predict the ERROR in the
closing line", because that residual is the only place an edge can live.

Measured mean ATS residual, home perspective (t-statistic in parentheses):

    home off bye              -0.27  (-0.44)
    away off bye              -0.94  (-1.33)
    home short week           -0.21  (-0.27)
    away short week           -0.20  (-0.26)
    wind >= 15 mph            +0.16  (+0.24)
    wind >= 20 mph            -0.56  (-0.44)
    cold < 32F                +1.13  (+1.33)
    away crosses 2+ zones     +0.56  (+1.15)
    week 17                   +1.03  (+1.35)
    weeks 17-18               +0.87  (+1.45)
    divisional game           -0.36  (-1.23)
    favorite of 10+           +0.71  (+1.48)

Not one reaches |t| = 2. Across roughly fifteen hypotheses you would expect a
couple of false positives at that bar by chance alone, and we got none -- so
this is not a case of "underpowered, probably real". The market's overall
mean residual is -0.04 points, which is unbiased to within four hundredths of
a point over two decades.

The consequence: every coefficient below ships at zero. Turning them on would
move projections by a point or so on the strength of noise, and every such
move costs money at -110. The framework stays because the measurement should
be repeatable and because a factor could become mispriced later -- rerun
scripts/measure_situational.py each offseason -- but the default is off, and
the default is correct.

The one factor that DID prove out is the quarterback, and it is not handled
here. QB belongs in the ratings themselves (see ratings.fit_ratings_qb), not
as a post-hoc nudge, because a quarterback is a component of team strength
rather than a circumstance surrounding it. Decomposing team and QB improved
out-of-sample MAE by 0.096 points.
"""

from __future__ import annotations

import pandas as pd

from .config import ADJUSTMENTS, Adjustments
from .data import TEAM_TZ_OFFSET


def rest_adjustment(game, cfg: Adjustments = ADJUSTMENTS) -> float:
    """Rest differential. Measured at zero against the closing line."""
    if cfg.rest_pts_per_day == 0.0:
        return 0.0

    home_rest = game.get("home_rest", 7) or 7
    away_rest = game.get("away_rest", 7) or 7
    raw = (home_rest - away_rest) * cfg.rest_pts_per_day

    if home_rest >= 13:
        raw += cfg.off_bye_bonus
    if away_rest >= 13:
        raw -= cfg.off_bye_bonus
    if home_rest <= 4:
        raw -= cfg.short_week_penalty
    if away_rest <= 4:
        raw += cfg.short_week_penalty

    return max(-cfg.rest_max_adjustment, min(cfg.rest_max_adjustment, raw))


def travel_adjustment(game, cfg: Adjustments = ADJUSTMENTS) -> float:
    """Time-zone crossing and body clock. Measured at zero."""
    if cfg.timezone_pts_per_zone == 0.0:
        return 0.0

    home_tz = TEAM_TZ_OFFSET.get(game.get("home_team"), 0)
    away_tz = TEAM_TZ_OFFSET.get(game.get("away_team"), 0)
    return (home_tz - away_tz) * cfg.timezone_pts_per_zone


def weather_adjustment(game, cfg: Adjustments = ADJUSTMENTS) -> float:
    """
    Wind compresses margins, pulling the game toward the underdog. Measured at
    zero against the closing line -- books price weather well.
    """
    if cfg.wind_margin_compression == 0.0:
        return 0.0
    if cfg.dome_no_weather and str(game.get("roof", "")).lower() in ("dome", "closed"):
        return 0.0

    wind = game.get("wind")
    if wind is None or pd.isna(wind) or wind <= cfg.wind_threshold_mph:
        return 0.0

    # Compression shrinks the projected margin toward ZERO. It must therefore
    # depend on the sign of the margin: a fixed negative number would push an
    # away-favored game further from zero, which is the opposite of the
    # intended effect. Needs the current projection, so callers pass it in.
    excess = wind - cfg.wind_threshold_mph
    shrink = min(1.0, excess * cfg.wind_margin_compression)
    projected = game.get("_projected_margin", 0.0)
    return -projected * shrink


def motivation_adjustment(game, cfg: Adjustments = ADJUSTMENTS) -> float:
    """
    Weeks 17-18 resting-starters effects. Measured at zero.

    Genuinely tricky to model even if it were mispriced: it depends on playoff
    seeding scenarios that resolve during the week the game is played.
    """
    if cfg.motivation_max_adjustment == 0.0:
        return 0.0
    if game.get("week") not in cfg.motivation_weeks:
        return 0.0
    return 0.0


def total_adjustment(game, cfg: Adjustments = ADJUSTMENTS,
                     projected_margin: float = 0.0) -> float:
    """
    Sum of all situational adjustments. Zero by default, by design.

    projected_margin is needed by the weather term, which shrinks a margin
    toward zero rather than pushing in a fixed direction.
    """
    game = dict(game)
    game["_projected_margin"] = projected_margin
    return (
        rest_adjustment(game, cfg)
        + travel_adjustment(game, cfg)
        + weather_adjustment(game, cfg)
        + motivation_adjustment(game, cfg)
    )


def adjustment_breakdown(game, cfg: Adjustments = ADJUSTMENTS,
                         projected_margin: float = 0.0) -> dict[str, float]:
    """Per-factor detail, for showing your work on the dashboard."""
    game = dict(game)
    game["_projected_margin"] = projected_margin
    return {
        "rest": rest_adjustment(game, cfg),
        "travel": travel_adjustment(game, cfg),
        "weather": weather_adjustment(game, cfg),
        "motivation": motivation_adjustment(game, cfg),
    }
