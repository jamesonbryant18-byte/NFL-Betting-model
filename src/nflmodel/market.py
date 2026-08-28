"""
market.py — odds conversion, de-vigging, and turning a projected margin into
bettable probabilities.

The single most important function here is devig(). A sportsbook's posted
odds do not sum to 100% -- the excess is the vig, the book's margin. Comparing
a model probability against a RAW implied probability, as the MLB model does,
measures your edge against a price that is deliberately shaded against you.
You must strip the vig first to recover the market's actual opinion, then
compare against that. On NFL spreads priced at -110/-110 the raw numbers sum
to 104.8%, so this is a ~2.4 point swing on every single bet.
"""

from __future__ import annotations

import numpy as np
from scipy import optimize

from .config import STAKING, Staking


# ─────────────────────────────────────────────
# ODDS CONVERSION
# ─────────────────────────────────────────────

def american_to_prob(odds: float) -> float:
    """Raw implied probability of American odds. Includes vig."""
    odds = float(odds)
    if odds < 0:
        return -odds / (-odds + 100.0)
    return 100.0 / (odds + 100.0)


def prob_to_american(p: float) -> float:
    """
    Fair American odds for a probability. Inverse of american_to_prob.

    Exactly even money is ambiguous -- +100 and -100 are the same price -- and
    convention writes it +100, so the favorite branch is strict.
    """
    p = min(max(float(p), 1e-9), 1 - 1e-9)
    if p > 0.5:
        return -100.0 * p / (1.0 - p)
    return 100.0 * (1.0 - p) / p


def american_to_decimal(odds: float) -> float:
    odds = float(odds)
    return 1.0 + (odds / 100.0 if odds > 0 else 100.0 / -odds)


def payout_profit(odds: float, stake: float) -> float:
    """Profit (not total return) on a winning bet."""
    odds = float(odds)
    return stake * (odds / 100.0) if odds > 0 else stake * (100.0 / -odds)


# ─────────────────────────────────────────────
# DE-VIGGING
# ─────────────────────────────────────────────

def _devig_multiplicative(probs: np.ndarray) -> np.ndarray:
    """Scale both sides down proportionally. Simple; slightly biased toward
    favorites, but the standard baseline."""
    return probs / probs.sum()


def _devig_power(probs: np.ndarray) -> np.ndarray:
    """Find k with sum(p_i ** k) == 1. Handles favorite-longshot bias better
    than multiplicative on lopsided markets."""
    def objective(k):
        return np.sum(probs ** k) - 1.0

    try:
        k = optimize.brentq(objective, 0.5, 3.0, xtol=1e-10)
    except ValueError:
        return _devig_multiplicative(probs)
    return probs ** k


def _devig_shin(probs: np.ndarray) -> np.ndarray:
    """
    Shin's method: assumes some fraction z of money is informed, and backs out
    the probabilities a book would set facing that. Generally the most accurate
    of the three on markets with a heavy favorite.
    """
    total = probs.sum()

    def fair(z):
        return (np.sqrt(z ** 2 + 4 * (1 - z) * probs ** 2 / total) - z) / (2 * (1 - z))

    def objective(z):
        return fair(z).sum() - 1.0

    try:
        z = optimize.brentq(objective, 1e-9, 0.35, xtol=1e-10)
    except ValueError:
        return _devig_multiplicative(probs)
    return fair(z)


_DEVIG = {
    "multiplicative": _devig_multiplicative,
    "power": _devig_power,
    "shin": _devig_shin,
}


def devig(odds_a: float, odds_b: float, method: str = "multiplicative") -> tuple[float, float]:
    """
    Convert a two-way market into fair, vig-free probabilities summing to 1.

    >>> devig(-110, -110)          # standard spread pricing
    (0.5, 0.5)
    """
    probs = np.array([american_to_prob(odds_a), american_to_prob(odds_b)])
    fair = _DEVIG.get(method, _devig_multiplicative)(probs)
    return float(fair[0]), float(fair[1])


def vig_pct(odds_a: float, odds_b: float) -> float:
    """The book's hold on a two-way market, as a percentage."""
    return (american_to_prob(odds_a) + american_to_prob(odds_b) - 1.0) * 100.0


# ─────────────────────────────────────────────
# MARGIN → PROBABILITY
# ─────────────────────────────────────────────

class MarginModel:
    """
    Converts a projected margin into cover / win / push probabilities.

    Uses the empirical distribution of model residuals rather than a normal
    curve. NFL margins are emphatically not normal -- they pile up on 3 and 7
    because of how scoring works, and a normal approximation misprices every
    game sitting on a key number.
    """

    def __init__(self, residuals: np.ndarray | None = None, sigma: float = 13.2):
        self.sigma = float(sigma)
        self.residuals = (
            np.asarray(residuals, dtype=float) if residuals is not None else None
        )
        if self.residuals is not None and len(self.residuals) < 200:
            self.residuals = None   # too small to be trustworthy; fall back to normal

    # -- internals ---------------------------------------------------------

    def _simulated_margins(self, projected: float) -> np.ndarray:
        if self.residuals is not None:
            return projected + self.residuals
        rng = np.random.default_rng(0)
        return projected + rng.normal(0.0, self.sigma, 20000)

    # -- public API --------------------------------------------------------

    def cover_prob(self, projected_margin: float, spread_line: float) -> tuple[float, float, float]:
        """
        P(home covers), P(push), P(away covers) for a home-perspective spread.

        Home covers when the final margin exceeds the line. Margins are integers,
        so a whole-number line carries real push probability that has to come out
        of both sides -- ignoring it overstates your edge on every key number.
        """
        margins = np.rint(self._simulated_margins(projected_margin))

        p_home = float(np.mean(margins > spread_line))
        p_push = float(np.mean(margins == spread_line))
        p_away = float(np.mean(margins < spread_line))

        return p_home, p_push, p_away

    def win_prob(self, projected_margin: float) -> float:
        """P(home wins outright). Ties are vanishingly rare but are excluded."""
        margins = np.rint(self._simulated_margins(projected_margin))
        wins = np.mean(margins > 0)
        ties = np.mean(margins == 0)
        return float(wins + ties * 0.5)

    def fair_spread(self, projected_margin: float) -> float:
        """The line at which this projection would be a coin flip."""
        return round(projected_margin * 2) / 2


# ─────────────────────────────────────────────
# STAKING
# ─────────────────────────────────────────────

def kelly_stake(
    win_prob: float,
    odds: float,
    bankroll: float | None = None,
    staking: Staking = STAKING,
    push_prob: float = 0.0,
) -> tuple[float, float]:
    """
    Fractional Kelly stake, capped.

    Returns (stake in dollars, full-Kelly fraction of bankroll).

    Push probability is handled by renormalizing onto the decided outcomes: a
    push returns the stake, so it neither helps nor hurts and should not dilute
    the sizing.
    """
    bankroll = bankroll if bankroll is not None else staking.bankroll

    decided = 1.0 - push_prob
    if decided <= 0:
        return 0.0, 0.0

    p = win_prob / decided
    q = 1.0 - p
    b = american_to_decimal(odds) - 1.0

    if b <= 0:
        return 0.0, 0.0

    full_kelly = (b * p - q) / b

    if full_kelly <= 0:
        return 0.0, float(full_kelly)

    fraction = min(full_kelly * staking.kelly_fraction, staking.max_bet_pct)
    stake = bankroll * fraction

    if stake < staking.min_bet:
        return 0.0, float(full_kelly)

    stake = round(stake / staking.round_to) * staking.round_to
    return float(stake), float(full_kelly)


def closing_line_value(bet_odds: float, closing_odds: float) -> float:
    """
    CLV in probability points: how much better your number was than the close.

    Positive CLV is the best available early evidence that a model has real
    edge -- it shows up in weeks, where profit takes seasons to distinguish
    from luck.
    """
    return american_to_prob(closing_odds) - american_to_prob(bet_odds)
