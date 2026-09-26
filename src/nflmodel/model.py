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

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .adjustments import total_adjustment, adjustment_breakdown
from .config import (ADJUSTMENTS, ADVISORY_MODE, MARKET, RATINGS, STAKING,
                     THRESHOLDS, Adjustments, Market, RatingsParams, Staking,
                     Thresholds)
from .market import (MarginModel, american_to_prob, devig, format_spread,
                     kelly_stake, prob_to_american, vig_pct)
from .ratings import (REPLACEMENT_QB, blend_with_prior, fit_market_ratings,
                      fit_ratings_qb, qb_value, ratings_table)


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

    # Whether the bet is on the team the model picks to win, and why, in plain
    # words. Set in project(); blank on NO BET rows.
    bet_type: str = ""
    bet_why: str = ""
    # Weekly self-tune nudge already included in projected_margin (points,
    # home perspective). 0 when self-tune is off.
    selftune_adj: float = 0.0
    # Correction from confirmed miss-trends (trends.py), already included in
    # projected_margin. 0 when no trend applies to this game.
    trend_adj: float = 0.0

    def as_row(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


WITH_PICK = "ON MODEL'S PICK"
AGAINST_PICK = "VALUE — AGAINST PICK"


def explain_bet(market, team, pick, pick_margin, ticket=None, odds=None,
                model_p=None, market_p=None) -> str:
    """
    One sentence saying what has to happen for a bet to win and why the
    model wants it.

    `ticket` is the spread number as printed on the bet for `team` (+8.5 when
    getting points, -3.0 when laying). `model_p` / `market_p` are that team's
    win chance from the model and from the de-vigged price.
    """
    if market == "SPREAD" and ticket is not None:
        head = f"Model: {pick} by {abs(pick_margin):.1f}."
        n = float(ticket)
        whole = n.is_integer()
        if n < 0:
            cond = f"{team} wins by {math.floor(-n) + 1}+"
        elif n > 0:
            k = math.ceil(n) - 1
            cond = f"{team} wins or loses by {k} or less" if k > 0 else f"{team} wins"
        else:
            cond = f"{team} wins"
        if whole and n != 0:
            cond += f" (push at {abs(n):.0f})"
        return f"{head} {team} {n:+g} — bet wins if {cond}."
    if market == "MONEYLINE" and model_p is not None and market_p is not None:
        if team == pick:
            return (f"Model gives {team} {model_p:.0%} to win; the {odds:+.0f} price "
                    f"only assumes {market_p:.0%}. Bet wins if {team} wins.")
        return (f"Model still picks {pick} to win, but gives {team} {model_p:.0%} — "
                f"the {odds:+.0f} price assumes only {market_p:.0%}. "
                f"Bet wins only if {team} pulls the upset.")
    return ""


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
        # Weekly self-tune (selftune.live_corrections). Empty = frozen model.
        self.team_adjust: dict[str, float] = {}
        self.max_tune: float | None = None
        # Confirmed miss-trend fixes (trends.py / data/trends.json).
        # game_adjust: game_id -> points added to the home side.
        # calibration: {a, b} recalibration of home win probability.
        self.game_adjust: dict[str, float] = {}
        self.calibration: dict | None = None

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

    def components(self, game) -> dict:
        """
        The pieces a projection is made of, for display only.

        project() collapses team rating, quarterback, home field and the
        market prior into one number. A reader deciding whether to trust a
        lean needs to see those pieces separately -- in Week 1 most of the
        "rating" is the market's own preseason opinion, and a quarterback the
        fit has never seen sits at replacement level whether or not that is
        true of him. This recomputes exactly the terms project() uses and
        returns them unblended. Nothing here feeds back into a projection;
        it is additive and changes no math.

        Market probabilities are de-vigged the same way project() does, so the
        edge shown on the workbook is the edge the model actually acted on.
        """
        g = game if isinstance(game, dict) else game.to_dict()
        home, away = g["home_team"], g["away_team"]
        neutral = bool(g.get("neutral", False))
        home_qb, away_qb = g.get("home_qb_name"), g.get("away_qb_name")

        def known(name) -> bool:
            return isinstance(name, str) and name in self.qb_ratings

        h_ml, a_ml = g.get("home_moneyline"), g.get("away_moneyline")
        h_ml = None if h_ml is None or pd.isna(h_ml) else float(h_ml)
        a_ml = None if a_ml is None or pd.isna(a_ml) else float(a_ml)
        if h_ml is not None and a_ml is not None:
            fair_h, fair_a = devig(h_ml, a_ml, self.market_cfg.devig_method)
            vig = vig_pct(h_ml, a_ml)
        else:
            fair_h = fair_a = vig = float("nan")

        return {
            "home_team_rating": float(self.team_ratings.get(home, 0.0)),
            "away_team_rating": float(self.team_ratings.get(away, 0.0)),
            "home_qb": home_qb if isinstance(home_qb, str) else "",
            "away_qb": away_qb if isinstance(away_qb, str) else "",
            "home_qb_adj": float(qb_value(self.qb_ratings, home_qb)),
            "away_qb_adj": float(qb_value(self.qb_ratings, away_qb)),
            "home_qb_known": known(home_qb),
            "away_qb_known": known(away_qb),
            "replacement_qb_value": float(self.qb_ratings.get(REPLACEMENT_QB, 0.0)),
            "home_strength": float(self.strength(home, home_qb)),
            "away_strength": float(self.strength(away, away_qb)),
            "hfa_used": 0.0 if neutral else float(self.hfa),
            "neutral": neutral,
            "market_prior_weight": float(self.market_prior_weight_used),
            "market_home_prob": float(fair_h),
            "market_away_prob": float(fair_a),
            "vig_pct": float(vig),
        }

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
        tune = self.team_adjust.get(home, 0.0) - self.team_adjust.get(away, 0.0)
        if self.max_tune is not None:
            tune = float(np.clip(tune, -self.max_tune, self.max_tune))
        trend = float(self.game_adjust.get(g.get("game_id", ""), 0.0))
        projected = base + adj + tune + trend

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
        if self.calibration:
            # The model's spreads are compressed, so raw win probabilities
            # overrate long underdogs (+401 dogs: said 25%, won 12-13%).
            # Recalibrated to what actually happened; see trends.py.
            from .trends import calibrate
            home_wp = float(calibrate(home_wp, self.calibration))
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

        # Tag the bet against the straight-up pick (report.straight_up_ranking
        # picks by win probability, so this does too).
        pick_home = home_wp >= 0.5
        pick = home if pick_home else away
        side_team = rec["bet_side"].split()[0] if rec["bet_side"] else ""
        if side_team:
            bet_home = side_team == home
            rec["bet_type"] = WITH_PICK if bet_home == pick_home else AGAINST_PICK
            rec["bet_why"] = explain_bet(
                rec["bet_market"], side_team, pick,
                projected if pick_home else -projected,
                ticket=(None if line is None else (-line if bet_home else line)),
                odds=rec["bet_odds"],
                model_p=home_wp if bet_home else 1.0 - home_wp,
                market_p=(fair_h if bet_home else fair_a),
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
            selftune_adj=tune,
            trend_adj=trend,
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
        df.loc[killed, ["bet_market", "bet_side", "bet_type", "bet_why"]] = ""
        df.loc[killed, "bet_odds"] = 0.0

        return df

    def power_ratings(self) -> pd.DataFrame:
        """Current team ratings, QB included, best to worst."""
        return ratings_table(self.team_ratings)
