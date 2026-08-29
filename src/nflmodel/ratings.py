"""
ratings.py — opponent-adjusted team power ratings, expressed in points.

The model is a ridge-regularized least squares fit (a regularized Massey
rating). For each game we write

    margin_home = rating_home - rating_away + HFA + error

and solve for the ratings that best explain every game at once. Because every
team appears on both sides of many games, the fit is automatically
opponent-adjusted: beating a good team moves your rating more than beating a
bad one.

Two things make this work in practice rather than just in theory:

  1. The regression target is not raw scoring margin. It blends margin with an
     EPA-implied margin, because EPA is far more predictive of a team's future
     than its past points are -- it strips out turnover luck and garbage time.

  2. Games are exponentially recency-weighted, with an extra penalty across
     the offseason. A Week 3 result matters more than a Week 3 result from last
     year, and rosters turn over.

Ridge shrinkage is what keeps Week 2 ratings from being nonsense: with two
games played, every team is pulled hard toward league average, and the data
only overcomes that as it accumulates.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import RATINGS, RatingsParams
from .data import TEAMS


def _time_index(season: pd.Series, week: pd.Series, params: RatingsParams) -> pd.Series:
    """A continuous week counter that treats the offseason as a long gap."""
    return season * params.offseason_weeks_equiv + week


def build_target(df: pd.DataFrame, params: RatingsParams) -> pd.Series:
    """
    The quantity the ratings try to explain: a blend of what happened
    (scoring margin) and what should have happened (EPA-implied margin).
    """
    actual = df["result"].astype(float)

    # Re-center the EPA component so it estimates the same quantity as actual
    # margin, home advantage included. Without this the blend dilutes HFA.
    home_flag = np.where(df["neutral"].to_numpy(), 0.0, 1.0)
    epa_margin = (
        df["home_net_epa"].astype(float) * params.epa_to_points
        + params.epa_home_intercept * home_flag
    )

    w = params.epa_margin_weight
    blended = w * epa_margin + (1.0 - w) * actual

    # Fall back to raw margin where EPA is missing (rare, but don't drop games).
    return blended.where(df["home_net_epa"].notna(), actual)


def fit_ratings(
    history: pd.DataFrame,
    asof_season: int,
    asof_week: int,
    params: RatingsParams = RATINGS,
    target: pd.Series | None = None,
    teams: list[str] | None = None,
) -> tuple[dict[str, float], float]:
    """
    Fit ratings using only games that finished before (asof_season, asof_week).

    This cutoff is the whole ballgame for an honest backtest -- one leaked
    future game and the results become fiction.

    Returns (ratings by team, home field advantage in points).
    """
    teams = teams or TEAMS
    idx = {t: i for i, t in enumerate(teams)}
    n_teams = len(teams)

    cutoff = asof_season * params.offseason_weeks_equiv + asof_week
    hist = history[
        history["played"]
        & (_time_index(history["season"], history["week"], params) < cutoff)
    ].copy()

    if len(hist) < n_teams:
        return {t: 0.0 for t in teams}, params_hfa_default()

    y = (target.loc[hist.index] if target is not None
         else build_target(hist, params)).to_numpy(dtype=float)

    # Design matrix: one column per team, plus an unpenalized home-field column.
    n = len(hist)
    X = np.zeros((n, n_teams + 1))
    home_i = hist["home_team"].map(idx).to_numpy()
    away_i = hist["away_team"].map(idx).to_numpy()
    rows = np.arange(n)

    X[rows, home_i] = 1.0
    X[rows, away_i] = -1.0
    X[:, n_teams] = np.where(hist["neutral"].to_numpy(), 0.0, 1.0)

    # Recency weights.
    weeks_ago = cutoff - _time_index(hist["season"], hist["week"], params).to_numpy()
    w = params.recency_decay ** np.clip(weeks_ago, 0, None)

    # Weighted ridge. The home-field column is deliberately left unpenalized:
    # we want it estimated freely, not shrunk toward zero.
    Xw = X * w[:, None]
    with np.errstate(all="ignore"):   # macOS Accelerate BLAS emits spurious FP warnings
        XtWX = X.T @ Xw
        XtWy = Xw.T @ y

    penalty = np.eye(n_teams + 1) * params.ridge_lambda
    penalty[n_teams, n_teams] = 0.0

    beta = np.linalg.solve(XtWX + penalty, XtWy)

    ratings = {t: float(beta[idx[t]]) for t in teams}

    # Center so ratings are strictly relative to league average.
    mean_rating = float(np.mean(list(ratings.values())))
    ratings = {t: r - mean_rating for t, r in ratings.items()}

    return ratings, float(beta[n_teams])


def params_hfa_default() -> float:
    from .config import HFA_BASE
    return HFA_BASE


def fit_market_ratings(
    games: pd.DataFrame,
    season: int,
    params: RatingsParams = RATINGS,
    teams: list[str] | None = None,
    asof_week: int | None = None,
) -> tuple[dict[str, float], float]:
    """
    Back out the market's own power ratings from posted spreads.

    A posted spread IS the market's projected margin, so running the same
    regression with spread_line as the target recovers what oddsmakers think
    every team is worth -- for free, with no scraping, and available before a
    single snap of the season has been played.

    This is the sharpest preseason prior obtainable without paying for one.

    asof_week is a leak guard. Live it is harmless -- only this week's lines
    exist yet. But replayed over a COMPLETED season the unfiltered version sees
    every closing line in the year, including games not yet played at the
    simulated moment, which is worth about a quarter point of counterfeit
    accuracy. Pass asof_week in any backfill or backtest; leave it None only
    when genuinely running forward in time.
    """
    teams = teams or TEAMS
    idx = {t: i for i, t in enumerate(teams)}
    n_teams = len(teams)

    lines = games[
        (games["season"] == season) & games["spread_line"].notna()
    ].copy()

    if asof_week is not None:
        # Keep lines from earlier weeks and from any game not yet played.
        already_played = lines.get("played", pd.Series(False, index=lines.index))
        lines = lines[(lines["week"] < asof_week) | (~already_played.fillna(False))]

    if len(lines) < n_teams:
        return {t: 0.0 for t in teams}, params_hfa_default()

    y = lines["spread_line"].to_numpy(dtype=float)

    n = len(lines)
    X = np.zeros((n, n_teams + 1))
    rows = np.arange(n)
    X[rows, lines["home_team"].map(idx).to_numpy()] = 1.0
    X[rows, lines["away_team"].map(idx).to_numpy()] = -1.0
    X[:, n_teams] = np.where(lines["neutral"].to_numpy(), 0.0, 1.0)

    penalty = np.eye(n_teams + 1) * params.market_ridge_lambda
    penalty[n_teams, n_teams] = 0.0

    with np.errstate(all="ignore"):   # macOS Accelerate BLAS emits spurious FP warnings
        beta = np.linalg.solve(X.T @ X + penalty, X.T @ y)

    ratings = {t: float(beta[idx[t]]) for t in teams}
    mean_rating = float(np.mean(list(ratings.values())))
    ratings = {t: r - mean_rating for t, r in ratings.items()}

    return ratings, float(beta[n_teams])


def blend_with_prior(
    performance: dict[str, float],
    prior: dict[str, float],
    games_played: float,
    params: RatingsParams = RATINGS,
) -> dict[str, float]:
    """
    Weight the preseason prior against in-season performance.

    Prior weight falls off as games accumulate: with prior_decay_games = 10,
    the prior carries half the weight after 10 games and fades from there.
    """
    w_prior = params.prior_decay_games / (params.prior_decay_games + max(games_played, 0.0))
    w_prior *= params.market_prior_weight

    return {
        t: (1.0 - w_prior) * performance.get(t, 0.0) + w_prior * prior.get(t, 0.0)
        for t in set(performance) | set(prior)
    }


def ratings_table(ratings: dict[str, float]) -> pd.DataFrame:
    """Ratings sorted best to worst, for display."""
    return (
        pd.DataFrame({"team": list(ratings), "rating": list(ratings.values())})
        .sort_values("rating", ascending=False)
        .reset_index(drop=True)
        .assign(rank=lambda d: d.index + 1)
    )


# ─────────────────────────────────────────────
# QB-AWARE RATINGS
# ─────────────────────────────────────────────

REPLACEMENT_QB = "__REPLACEMENT__"


def fit_ratings_qb(
    history: pd.DataFrame,
    asof_season: int,
    asof_week: int,
    params: RatingsParams = RATINGS,
    teams: list[str] | None = None,
    qb_lambda: float = 40.0,
    min_qb_starts: int = 8,
) -> tuple[dict[str, float], dict[str, float], float]:
    """
    Fit team and quarterback ratings jointly.

    A team is not one thing. Roughly 15% of NFL team-games are started by
    somebody other than the team's primary quarterback, and the margin swing
    between a primary starter and a backup is about six points -- larger than
    any other factor in the sport, home field included. A rating that treats
    the roster as a monolith is simply wrong in one game out of seven, and
    those are exactly the games where the market has information we don't.

    So the model becomes

        margin = (team_home + qb_home) - (team_away + qb_away) + HFA

    Team and QB are collinear for a quarterback who never changes teams; ridge
    splits the credit, and QBs who do move -- plus every backup start -- are
    what identify the separation. QB columns get a heavier penalty than team
    columns because they are estimated on far less data each.

    Quarterbacks below min_qb_starts prior starts are pooled into a single
    replacement-level bucket. This matters: an unseen quarterback defaulting to
    zero would be treated as league average, which badly overrates a debuting
    backup.

    Returns (team ratings, qb ratings, home field advantage).
    """
    teams = teams or TEAMS
    t_idx = {t: i for i, t in enumerate(teams)}
    n_teams = len(teams)

    cutoff = asof_season * params.offseason_weeks_equiv + asof_week
    hist = history[
        history["played"]
        & (_time_index(history["season"], history["week"], params) < cutoff)
        & history["home_qb_name"].notna()
        & history["away_qb_name"].notna()
    ].copy()

    if len(hist) < n_teams * 2:
        return {t: 0.0 for t in teams}, {}, params_hfa_default()

    # Only quarterbacks with enough prior starts get their own parameter.
    starts = pd.concat([hist["home_qb_name"], hist["away_qb_name"]]).value_counts()
    known_qbs = sorted(starts[starts >= min_qb_starts].index)
    qb_list = known_qbs + [REPLACEMENT_QB]
    q_idx = {q: i for i, q in enumerate(qb_list)}
    n_qbs = len(qb_list)

    def qb_col(name):
        return q_idx.get(name, q_idx[REPLACEMENT_QB])

    y = build_target(hist, params).to_numpy(dtype=float)

    n = len(hist)
    n_params = n_teams + n_qbs + 1
    X = np.zeros((n, n_params))
    rows = np.arange(n)

    X[rows, hist["home_team"].map(t_idx).to_numpy()] = 1.0
    X[rows, hist["away_team"].map(t_idx).to_numpy()] = -1.0

    hq = n_teams + hist["home_qb_name"].map(qb_col).to_numpy()
    aq = n_teams + hist["away_qb_name"].map(qb_col).to_numpy()
    np.add.at(X, (rows, hq), 1.0)
    np.add.at(X, (rows, aq), -1.0)

    X[:, -1] = np.where(hist["neutral"].to_numpy(), 0.0, 1.0)

    weeks_ago = cutoff - _time_index(hist["season"], hist["week"], params).to_numpy()
    w = params.recency_decay ** np.clip(weeks_ago, 0, None)

    with np.errstate(all="ignore"):   # macOS Accelerate BLAS emits spurious FP warnings
        Xw = X * w[:, None]
        XtWX = X.T @ Xw
        XtWy = Xw.T @ y

    penalty = np.zeros((n_params, n_params))
    np.fill_diagonal(penalty[:n_teams, :n_teams], params.ridge_lambda)
    np.fill_diagonal(penalty[n_teams:-1, n_teams:-1], qb_lambda)
    # HFA stays unpenalized.

    beta = np.linalg.solve(XtWX + penalty, XtWy)

    team_ratings = {t: float(beta[t_idx[t]]) for t in teams}
    mean_team = float(np.mean(list(team_ratings.values())))
    team_ratings = {t: r - mean_team for t, r in team_ratings.items()}

    qb_ratings = {q: float(beta[n_teams + q_idx[q]]) for q in qb_list}

    return team_ratings, qb_ratings, float(beta[-1])


def qb_value(qb_ratings: dict[str, float], name) -> float:
    """QB rating, falling back to replacement level for anyone unseen."""
    if name is None or (isinstance(name, float) and np.isnan(name)):
        return qb_ratings.get(REPLACEMENT_QB, 0.0)
    return qb_ratings.get(name, qb_ratings.get(REPLACEMENT_QB, 0.0))


# ─────────────────────────────────────────────
# PROJECTED STARTERS
# ─────────────────────────────────────────────

def projected_starters(history: pd.DataFrame, season: int, week: int) -> dict[str, str]:
    """
    Best guess at each team's starting quarterback for an upcoming week.

    nflverse only fills home_qb_name / away_qb_name once a game has been
    PLAYED, so for a future slate both sides are null. That silently collapses
    the QB term to replacement level on both teams, where it cancels out --
    the whole QB decomposition becomes inert in exactly the situation it was
    built for. Carrying the most recent starter forward restores it.

    Two different questions need two different answers:

      Mid-season, the most RECENT starter is right -- it reflects the current
      injury situation.

      For Week 1, the most recent starter is actively misleading. Week 18 is
      where playoff-bound teams rest everyone, so carrying it forward hands
      you the third-string quarterback: KC's last 2025 starter was Chris
      Oladokun, not Patrick Mahomes. Week 1 therefore uses the prior season's
      most FREQUENT starter, ignoring Week 18 entirely.

    Neither can know about offseason moves -- a team that changed quarterbacks
    in free agency will be wrong until it plays. Override those with --qb.
    """
    played = history[history["played"]].copy()
    if played.empty:
        return {}

    long = pd.concat([
        played[["season", "week", "home_team", "home_qb_name"]]
            .rename(columns={"home_team": "team", "home_qb_name": "qb"}),
        played[["season", "week", "away_team", "away_qb_name"]]
            .rename(columns={"away_team": "team", "away_qb_name": "qb"}),
    ]).dropna(subset=["qb"])

    cutoff = long[(long["season"] < season)
                  | ((long["season"] == season) & (long["week"] < week))]
    if cutoff.empty:
        return {}

    in_season = cutoff[cutoff["season"] == season]

    if len(in_season) >= 16:
        # Enough of the current season has been played: use the latest starter.
        starters = {}
        for team, grp in in_season.groupby("team"):
            starters[team] = grp.sort_values(["season", "week"]).iloc[-1]["qb"]
        return starters

    # Season opener: most frequent starter last year, excluding Week 18 rest.
    prior = cutoff[cutoff["season"] == cutoff["season"].max()]
    prior = prior[prior["week"] != 18]
    if prior.empty:
        return {}

    starters = {}
    for team, grp in prior.groupby("team"):
        starters[team] = grp["qb"].value_counts().idxmax()
    return starters
