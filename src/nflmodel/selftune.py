"""
selftune.py — weekly self-correction from recent prediction error.

The idea this implements: after every week, look at what the model got wrong,
and adjust. If a team keeps beating its projection, nudge that team's rating
up; if the league as a whole keeps beating the home number, nudge home field.
Do it again next week, forever. This is what "the model should be constantly
improving" means when written as code.

The mechanism
-------------
After week W is played, each game yields a residual:

    r = actual_margin - projected_margin        (home perspective)

Positive r means the home team outperformed the projection, which is the same
as saying the away team underperformed it. So each game deposits a *signed*
residual with both teams:  home gets +r, away gets -r.

Before predicting week W+1, each team's recent signed residuals are collapsed
into one correction with an exponential weight (`half_life` in weeks), and the
projection is nudged:

    projected += alpha * (correction[home] - correction[away])

`alpha` is how hard the model chases what just happened:

    alpha = 0.0   the frozen model. Ignores last week entirely.
    alpha = 0.5   moves halfway toward recent error.
    alpha = 1.0   fully believes the last few weeks.

alpha=0 reproduces the baseline projection exactly, which is what makes this
an honest experiment rather than a new model: the only difference between the
adaptive and frozen runs is how much recent error is allowed to move the
number.

The feedback is closed on purpose: corrections are computed from the residuals
of the *shipped* (already-corrected) predictions, not from a parallel
uncorrected model. That is what a self-tuning system actually experiences, and
it is where the failure mode lives if there is one -- a correction that
overshoots generates the residual that justifies the next overshoot.

Walk-forward discipline is unchanged and non-negotiable: the correction
applied to week W is built only from games that finished strictly before week
W. Residuals reset at each season boundary by default (`carry_offseason`),
since "this team has been outperforming lately" should not survive a draft and
free agency.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

from .config import RATINGS, RatingsParams
from .ratings import fit_ratings_qb, qb_value


class ResidualMemory:
    """Per-team exponentially-weighted memory of recent prediction error."""

    def __init__(self, half_life: float = 3.0, cap: float = 7.0):
        if half_life <= 0:
            raise ValueError("half_life must be positive")
        self.decay = 0.5 ** (1.0 / half_life)
        self.cap = cap
        # team -> list of (time_index, signed_residual)
        self._obs: dict[str, list[tuple[float, float]]] = defaultdict(list)
        self._league: list[tuple[float, float]] = []

    def observe(self, t: float, home: str, away: str, residual: float) -> None:
        """Record one played game's residual against both teams."""
        self._obs[home].append((t, residual))
        self._obs[away].append((t, -residual))
        self._league.append((t, residual))

    def _ewma(self, obs: list[tuple[float, float]], now: float) -> float:
        if not obs:
            return 0.0
        w = np.array([self.decay ** max(0.0, now - t) for t, _ in obs])
        v = np.array([r for _, r in obs])
        tot = w.sum()
        if tot <= 0:
            return 0.0
        return float((w * v).sum() / tot)

    def correction(self, team: str, now: float) -> float:
        """Points to add to `team`'s rating, before alpha scaling."""
        c = self._ewma(self._obs.get(team, []), now)
        # A cap keeps one 40-point blowout from rewriting a team's rating.
        # Without it a single Week 1 result can move a projection by more than
        # the entire home-field advantage.
        return float(np.clip(c, -self.cap, self.cap))

    def hfa_drift(self, now: float) -> float:
        """League-wide mean residual: are home teams beating the number?"""
        return self._ewma(self._league, now)

    def reset(self) -> None:
        self._obs.clear()
        self._league.clear()


def walk_forward_adaptive(
    df: pd.DataFrame,
    seasons: list[int],
    params: RatingsParams = RATINGS,
    qb_lambda: float = 1.0,
    alpha: float = 0.0,
    half_life: float = 3.0,
    cap: float = 7.0,
    max_adj: float | None = None,
    adapt_hfa: bool = False,
    hfa_alpha: float = 0.5,
    carry_offseason: bool = False,
    deployed: bool = True,
    verbose: bool = False,
) -> pd.DataFrame:
    """
    Walk forward with weekly self-correction. `alpha=0` is the frozen model.

    Mirrors the loop in scripts/run_backtest.py so the comparison is against
    the estimator that actually ships, market-prior blending included.
    """
    from .model import NFLModel

    df = df.sort_values(["season", "week"]).reset_index(drop=True)
    mem = ResidualMemory(half_life=half_life, cap=cap)
    rows = []

    for season in seasons:
        if not carry_offseason:
            mem.reset()

        for week in sorted(df.loc[df.season == season, "week"].unique()):
            slate = df[(df.season == season) & (df.week == week)
                       & df.played & df.spread_line.notna()]
            if slate.empty:
                continue

            if deployed:
                m = NFLModel(params=params, qb_lambda=qb_lambda)
                m.fit(df, season, week, market_games=df)
                tr, qr, hfa = m.team_ratings, m.qb_ratings, m.hfa
            else:
                tr, qr, hfa = fit_ratings_qb(df, season, week, params,
                                             qb_lambda=qb_lambda)

            now = float(week)
            hfa_used = hfa
            if adapt_hfa:
                hfa_used = hfa + hfa_alpha * mem.hfa_drift(now)

            played = []
            for _, g in slate.iterrows():
                base = ((tr.get(g.home_team, 0.) + qb_value(qr, g.home_qb_name))
                        - (tr.get(g.away_team, 0.) + qb_value(qr, g.away_qb_name))
                        + (0. if g.neutral else hfa_used))

                adj = alpha * (mem.correction(g.home_team, now)
                               - mem.correction(g.away_team, now))
                if max_adj is not None:
                    adj = float(np.clip(adj, -max_adj, max_adj))
                proj = base + adj

                rows.append(dict(
                    game_id=g.game_id, season=season, week=week,
                    home_team=g.home_team, away_team=g.away_team,
                    projected_margin=proj, baseline_margin=base,
                    adjustment=adj,
                    spread_line=g.spread_line, result=g.result,
                    home_moneyline=g.home_moneyline,
                    away_moneyline=g.away_moneyline,
                    neutral=g.neutral, hfa_used=hfa_used))

                played.append((g.home_team, g.away_team, g.result - proj))

            # Learn only AFTER the whole week is predicted. Updating mid-slate
            # would leak Sunday's early results into Sunday's late games.
            for home, away, resid in played:
                mem.observe(now, home, away, resid)

        if verbose:
            print(f"  {season} done (alpha={alpha})", flush=True)

    return pd.DataFrame(rows)


def live_corrections(games: pd.DataFrame, season: int, week: int,
                     alpha: float, half_life: float = 3.0, cap: float = 7.0,
                     archive_dir=None):
    """
    The live version of the loop above: per-team corrections for `week`, built
    from this season's ARCHIVED projections (what the model actually published)
    against the actual results of weeks strictly before `week`.

    Returns (team -> points to add, table of the residuals used). Teams with no
    graded games get nothing. The per-game ceiling is applied by the caller,
    on the home-minus-away difference, exactly as in the backtest.
    """
    from .archive import week_dir

    d = archive_dir or week_dir(season)
    mem = ResidualMemory(half_life=half_life, cap=cap)
    used = []
    played = games[(games.season == season) & (games.week < week)
                   & games.played & games.result.notna()]
    for wk in sorted(played.week.unique()):
        f = d / f"week{int(wk):02d}_picks.csv"
        if not f.exists():
            continue
        pk = pd.read_csv(f)
        for _, r in pk.iterrows():
            away, home = [t.strip() for t in str(r.matchup).split("@")]
            g = played[(played.week == wk) & (played.home_team == home)
                       & (played.away_team == away)]
            if g.empty:
                continue
            # picks.csv is winner-perspective; convert to home margin.
            proj = float(r.proj_margin) if str(r.winner) == home else -float(r.proj_margin)
            resid = float(g.result.iloc[0]) - proj
            mem.observe(float(wk), home, away, resid)
            used.append(dict(week=int(wk), home=home, away=away,
                             projected=proj, actual=float(g.result.iloc[0]),
                             residual=resid))
    teams = set(games.home_team) | set(games.away_team)
    corr = {t: alpha * mem.correction(t, float(week)) for t in teams}
    return corr, pd.DataFrame(used)
