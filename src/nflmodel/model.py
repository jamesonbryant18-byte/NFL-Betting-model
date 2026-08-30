"""
model.py — the prediction pipeline.

Ties ratings, adjustments, and market math into a single object that takes a
game and returns a bet recommendation with a stake attached.

The chain is:

    team + QB ratings  ->  projected margin  ->  cover / win probabilities
                                             ->  compare vs de-vigged market
                                             ->  edge  ->  Kelly stake
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .adjustments import total_adjustment, adjustment_breakdown
from .config import (ADJUSTMENTS, ADVISORY_MODE, MARKET, RATINGS, STAKING,
                     THRESHOLDS, Adjustments, Market, RatingsParams, Staking,
                     Thresholds)
from .market import (MarginModel, american_to_prob, devig, format_spread,
                     kelly_stake, prob_to_american, vig_pct)
from .ratings import (blend_with_prior, fit_market_ratings, fit_ratings_qb,
                      qb_value, ratings_table)


@dataclass
class GameProjection:
    """Everything the model concluded about one game."""
    game_id: str
    home_team: str
    away_team: str
    week: int

    projected_margin: float
    fair_spread: float
    situational_adj: float

    spread_line: float | None
    home_cover_prob: float
    push_prob: float
    away_cover_prob: float
    spread_edge_pts: float

    home_win_prob: float
    home_ml: float | None
    away_ml: float | None
    home_ml_fair: float
    away_ml_fair: float
    ml_edge_home: float
    ml_edge_away: float

    recommendation: str
    bet_market: str
    bet_side: str
    bet_odds: float
    stake: float
    confidence: str

    def as_row(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


class NFLModel:
    """Fit once per week, then project every game on the slate."""

    def __init__(
        self,
        params: RatingsParams = RATINGS,
        staking: Staking = STAKING,
        thresholds: Thresholds = THRESHOLDS,
        market_cfg: Market = MARKET,
        adjust_cfg: Adjustments = ADJUSTMENTS,
        qb_lambda: float = 40.0,
    ):
        self.params = params
        self.staking = staking
        self.thresholds = thresholds
        self.market_cfg = market_cfg
        self.adjust_cfg = adjust_cfg
        self.qb_lambda = qb_lambda

        self.team_ratings: dict[str, float] = {}
        self.qb_ratings: dict[str, float] = {}
        self.hfa: float = 0.0
        self.margin_model = MarginModel(sigma=market_cfg.margin_sigma)
        self.market_prior_weight_used = 0.0

    # -- fitting -----------------------------------------------------------

    def fit(self, history: pd.DataFrame, season: int, week: int,
            market_games: pd.DataFrame | None = None) -> "NFLModel":
        """
        Fit on everything strictly before (season, week).

        If market_games is supplied, the fitted ratings are blended toward
        ratings backed out of this season's posted spreads, weighted by how
        little current-season data exists. In Week 1 that blend is nearly all
        market, which is correct: the model has seen no 2026 football, while
        the line has absorbed every offseason move. Without this the model
        invents five-point "edges" out of last season's ratings and its own
        ignorance.

        The blend decays to zero as real games accumulate.
        """
        self.team_ratings, self.qb_ratings, self.hfa = fit_ratings_qb(
            history, season, week, self.params, qb_lambda=self.qb_lambda
        )

        if market_games is not None:
            played = history[
                (history["season"] == season)
                & (history["week"] < week)
                & history["played"]
            ]
            games_played = len(played) / 16.0   # in team-weeks

            # asof_week is mandatory here. Without it, replaying a completed
            # season lets the market prior see every closing line in the year,
            # including games that have not happened at the simulated moment.
            # That leak moved ratings by 0.8 pts and fabricated a 56% ATS
            # hold-out result -- the single most dangerous kind of bug in a
            # betting model, because it looks like success.
            market, market_hfa = fit_market_ratings(
                market_games, season, self.params, asof_week=week
            )
            if any(abs(v) > 1e-9 for v in market.values()):
                self.team_ratings = blend_with_prior(
                    self.team_ratings, market, games_played, self.params
                )
                w = self.params.prior_decay_games / (
                    self.params.prior_decay_games + max(games_played, 0.0)
                ) * self.params.market_prior_weight
                self.hfa = (1 - w) * self.hfa + w * market_hfa
                self.market_prior_weight_used = w

        return self

    def set_residuals(self, residuals: np.ndarray,
                      margins: np.ndarray | None = None) -> "NFLModel":
        """
        Install the empirical distributions used to turn a projected margin
        into probabilities.

        `margins` is the historical distribution of actual game margins, which
        is what carries the 3-and-7 key-number structure. Pass it. Without it
        the model falls back to smooth noise and reports a flat push
        probability at every line, which is wrong by a factor of nine on a
        three-point spread.
        """
        self.margin_model = MarginModel(
            residuals=residuals, sigma=self.market_cfg.margin_sigma, margins=margins
        )
        return self

    def strength(self, team: str, qb: str | None = None) -> float:
        """A team's rating including its quarterback."""
        return self.team_ratings.get(team, 0.0) + qb_value(self.qb_ratings, qb)

    # -- projection --------------------------------------------------------

    def project(self, game) -> GameProjection:
        g = game if isinstance(game, dict) else game.to_dict()

        home, away = g["home_team"], g["away_team"]
        neutral = bool(g.get("neutral", False))

        base = (
            self.strength(home, g.get("home_qb_name"))
            - self.strength(away, g.get("away_qb_name"))
            + (0.0 if neutral else self.hfa)
        )
        adj = total_adjustment(g, self.adjust_cfg, projected_margin=base)
        projected = base + adj

        # ── Spread ──
        line = g.get("spread_line")
        line = None if line is None or pd.isna(line) else float(line)

        if line is not None:
            p_home, p_push, p_away = self.margin_model.cover_prob(projected, line)
            spread_edge = projected - line
        else:
            p_home = p_push = p_away = float("nan")
            spread_edge = float("nan")

        # ── Moneyline ──
        home_wp = self.margin_model.win_prob(projected)
        h_ml, a_ml = g.get("home_moneyline"), g.get("away_moneyline")
        h_ml = None if h_ml is None or pd.isna(h_ml) else float(h_ml)
        a_ml = None if a_ml is None or pd.isna(a_ml) else float(a_ml)

        if h_ml is not None and a_ml is not None:
            fair_h, fair_a = devig(h_ml, a_ml, self.market_cfg.devig_method)
            ml_edge_h = home_wp - fair_h
            ml_edge_a = (1.0 - home_wp) - fair_a
        else:
            fair_h = fair_a = float("nan")
            ml_edge_h = ml_edge_a = float("nan")

        hso, aso = g.get("home_spread_odds"), g.get("away_spread_odds")

        rec = self._recommend(
            projected, line, spread_edge, p_home, p_push, p_away,
            home_wp, h_ml, a_ml, ml_edge_h, ml_edge_a, home, away,
            hso, aso,
        )

        return GameProjection(
            game_id=g.get("game_id", ""),
            home_team=home, away_team=away, week=int(g.get("week", 0)),
            projected_margin=projected,
            fair_spread=round(projected * 2) / 2,
            situational_adj=adj,
            spread_line=line,
            home_cover_prob=p_home, push_prob=p_push, away_cover_prob=p_away,
            spread_edge_pts=spread_edge,
            home_win_prob=home_wp,
            home_ml=h_ml, away_ml=a_ml,
            home_ml_fair=prob_to_american(home_wp),
            away_ml_fair=prob_to_american(1.0 - home_wp),
            ml_edge_home=ml_edge_h, ml_edge_away=ml_edge_a,
            **rec,
        )

    # -- bet selection -----------------------------------------------------

    def _recommend(self, projected, line, spread_edge, p_home, p_push, p_away,
                   home_wp, h_ml, a_ml, ml_edge_h, ml_edge_a, home, away,
                   home_spread_odds=None, away_spread_odds=None) -> dict:
        """
        Pick the best bet on the game, if any, and size it.

        Spread is preferred when both markets qualify: it is the more liquid
        market and the model's native output is a margin, so the spread edge is
        the more direct expression of what the model actually believes.
        """
        t = self.thresholds
        candidates = []

        # Spread candidate.
        if line is not None and not np.isnan(spread_edge):
            if abs(spread_edge) >= t.spread_min_edge_pts:
                side_home = spread_edge > 0
                win_p = p_home if side_home else p_away

                # Use the book's actual juice when we have it. Real spread
                # prices run from about +100 to -133, and assuming a flat -110
                # misstates break-even on every bet: -120 needs 54.5%, +100
                # needs 50.0%.
                odds = home_spread_odds if side_home else away_spread_odds
                if odds is None or (isinstance(odds, float) and np.isnan(odds)):
                    odds = -110.0
                odds = float(odds)

                stake, _ = kelly_stake(
                    win_p, odds, self.staking.bankroll, self.staking, push_prob=p_push
                )
                # `line` is home-favored-by; the side we are betting lays or
                # takes the negation of it. format_spread owns that flip.
                team = home if side_home else away
                favored_by = line if side_home else -line
                candidates.append({
                    "market": "SPREAD",
                    "side": format_spread(team, favored_by),
                    "odds": odds,
                    "edge_display": abs(spread_edge),
                    "stake": stake,
                    "priority": 2,
                })

        # Moneyline candidate.
        if h_ml is not None and a_ml is not None:
            for is_home, edge, ml, team, wp in (
                (True, ml_edge_h, h_ml, home, home_wp),
                (False, ml_edge_a, a_ml, away, 1.0 - home_wp),
            ):
                if np.isnan(edge) or edge < t.ml_min_edge:
                    continue
                if ml < t.ml_max_favorite or ml > t.ml_max_underdog:
                    continue
                stake, _ = kelly_stake(wp, ml, self.staking.bankroll, self.staking)
                candidates.append({
                    "market": "MONEYLINE",
                    "side": f"{team} {ml:+.0f}",
                    "odds": ml,
                    "edge_display": edge * 100,
                    "stake": stake,
                    "priority": 1,
                })

        candidates = [c for c in candidates if c["stake"] > 0]

        if not candidates:
            return {
                "recommendation": "NO BET", "bet_market": "", "bet_side": "",
                "bet_odds": 0.0, "stake": 0.0,
                "confidence": self._confidence(spread_edge),
            }

        best = sorted(candidates, key=lambda c: (-c["priority"], -c["edge_display"]))[0]

        # A moneyline pick necessarily failed the spread threshold, so grading
        # it on spread edge stamps every one of them 'Low'. Grade each market
        # on its own scale.
        if best["market"] == "MONEYLINE":
            edge = max(x for x in (ml_edge_h, ml_edge_a) if not np.isnan(x))
            conf = ("High" if edge >= t.ml_strong_edge
                    else "Medium" if edge >= t.ml_min_edge else "Low")
        else:
            conf = self._confidence(spread_edge)

        return {
            "recommendation": f"BET {best['side']}",
            "bet_market": best["market"],
            "bet_side": best["side"],
            "bet_odds": best["odds"],
            "stake": best["stake"],
            "confidence": conf,
        }

    def _confidence(self, spread_edge: float) -> str:
        if spread_edge is None or np.isnan(spread_edge):
            return "—"
        e = abs(spread_edge)
        if e >= self.thresholds.spread_strong_edge_pts:
            return "High"
        if e >= self.thresholds.spread_min_edge_pts:
            return "Medium"
        return "Low"

    # -- slate -------------------------------------------------------------

    def project_slate(self, games: pd.DataFrame, advisory: bool | None = None) -> pd.DataFrame:
        """
        Project every game in a week, sorted by edge, then apply portfolio
        limits across the slate.
        """
        rows = [self.project(g).as_row() for _, g in games.iterrows()]
        df = pd.DataFrame(rows)
        if df.empty:
            return df

        df = df.sort_values(
            "spread_edge_pts", key=lambda s: s.abs(), ascending=False
        ).reset_index(drop=True)

        advisory = ADVISORY_MODE if advisory is None else advisory

        if advisory:
            # Show the analysis, stake nothing, and say LEAN rather than BET.
            df["recommendation"] = df["recommendation"].str.replace(
                "^BET ", "LEAN ", regex=True
            )
            df["stake"] = 0.0
            return df

        # Weekly exposure cap, strongest edge first.
        cap = self.staking.bankroll * self.staking.max_weekly_exposure_pct
        running = 0.0
        stakes = []
        for s in df["stake"]:
            if s <= 0:
                stakes.append(0.0)
                continue
            allowed = min(s, max(0.0, cap - running))
            if allowed < self.staking.min_bet:
                allowed = 0.0
            stakes.append(allowed)
            running += allowed
        df["stake"] = stakes

        # Clear the bet fields too. Leaving a fully specified side and price
        # next to a NO BET verdict is how a reader (or a script) ends up
        # placing a bet the model declined.
        killed = df["stake"] <= 0
        df.loc[killed, "recommendation"] = "NO BET"
        df.loc[killed, ["bet_market", "bet_side"]] = ""
        df.loc[killed, "bet_odds"] = 0.0

        return df

    def power_ratings(self) -> pd.DataFrame:
        """Current team ratings, QB included, best to worst."""
        return ratings_table(self.team_ratings)
