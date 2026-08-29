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


def format_spread(team: str, favored_by: float) -> str:
    """
    Render a spread the way a bet ticket reads.

    `favored_by` follows the nflverse convention: points the team is favored
    by, positive when favored. A ticket shows the NEGATION of that, because a
    three-point favorite lays -3. Getting this backwards prints the opposite
    side of every game, so every display site routes through here rather than
    formatting the number itself.

    >>> format_spread("DET", 7.0)     # DET favored by 7
    'DET -7.0'
    >>> format_spread("NO", -7.0)     # NO is the 7-point dog
    'NO +7.0'
    """
    return f"{team} {-favored_by:+.1f}"


def vig_pct(odds_a: float, odds_b: float) -> float:
    """The book's hold on a two-way market, as a percentage."""
    return (american_to_prob(odds_a) + american_to_prob(odds_b) - 1.0) * 100.0


# ─────────────────────────────────────────────
# MARGIN → PROBABILITY
# ─────────────────────────────────────────────

class MarginModel:
    """
    Converts a projected margin into cover / win / push probabilities.

    NFL margins are emphatically not normal. Football scores in 3s and 7s, so
    the margin distribution has hard spikes -- a game lands on exactly 3 about
    nine times more often than on exactly 4. Any model that smooths over that
    misprices every game sitting on a key number, which is most of them.

    The method here is EXPONENTIAL TILTING of the empirical margin
    distribution. Start from the observed frequency of every integer margin in
    NFL history, P0(k), which carries the real 3-and-7 structure. Then tilt it
    to have the mean this game projects:

        P_M(k)  proportional to  P0(k) * exp(theta * k)

    solving for the theta that makes E[k] = M. Tilting reweights the
    distribution without smearing it, so the spikes survive the shift. That is
    the whole point: shifting a histogram preserves its shape, while adding
    noise to a continuous variable and rounding does not.

    An earlier version simply added residual noise to the projection and
    rounded, which produced an identical ~3.3% push probability at lines of 1,
    3, 4, 7 and 10 -- flatly contradicting reality and this docstring.
    """

    def __init__(self, residuals: np.ndarray | None = None, sigma: float = 13.2,
                 margins: np.ndarray | None = None):
        self.sigma = float(sigma)
        self.residuals = (
            np.asarray(residuals, dtype=float) if residuals is not None else None
        )
        if self.residuals is not None and len(self.residuals) < 200:
            self.residuals = None   # too small to be trustworthy

        self._grid = np.arange(-60, 61)
        self._p0 = self._build_base(margins)

    def _build_base(self, margins) -> np.ndarray | None:
        """Empirical P(margin = k), centered on zero. None => no tilting."""
        if margins is None:
            return None
        m = np.rint(np.asarray(margins, dtype=float))
        m = m[np.isfinite(m)]
        if len(m) < 500:
            return None
        counts = np.array([(m == k).sum() for k in self._grid], dtype=float)
        # Laplace smoothing so no reachable margin has literally zero mass.
        counts += 0.5
        # Deliberately NOT recentered. Key numbers are absolute -- games land
        # on a margin of exactly 3 far more often than 4, at every projection.
        # Rolling the histogram to mean-zero would drag those spikes off the
        # key numbers, which is exactly the failure this class exists to avoid.
        # The tilt below moves the MEAN without moving the grid.
        return counts / counts.sum()

    def _tilted(self, projected: float) -> np.ndarray:
        """P0 exponentially tilted to have mean `projected`."""
        p0 = self._p0
        lo, hi = -2.0, 2.0

        def mean_at(theta):
            w = p0 * np.exp(theta * self._grid)
            w /= w.sum()
            return float((self._grid * w).sum())

        target = float(np.clip(projected, self._grid[0] + 5, self._grid[-1] - 5))
        for _ in range(60):                      # bisection on theta
            mid = (lo + hi) / 2
            if mean_at(mid) < target:
                lo = mid
            else:
                hi = mid
        theta = (lo + hi) / 2
        w = p0 * np.exp(theta * self._grid)
        return w / w.sum()

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
        if self._p0 is not None:
            pmf = self._tilted(projected_margin)
            g = self._grid
            return (float(pmf[g > spread_line].sum()),
                    float(pmf[g == spread_line].sum()),
                    float(pmf[g < spread_line].sum()))

        margins = np.rint(self._simulated_margins(projected_margin))
        return (float(np.mean(margins > spread_line)),
                float(np.mean(margins == spread_line)),
                float(np.mean(margins < spread_line)))

    def win_prob(self, projected_margin: float) -> float:
        """P(home wins outright). Ties are vanishingly rare but are excluded."""
        if self._p0 is not None:
            pmf = self._tilted(projected_margin)
            g = self._grid
            return float(pmf[g > 0].sum() + pmf[g == 0].sum() * 0.5)

        margins = np.rint(self._simulated_margins(projected_margin))
        return float(np.mean(margins > 0) + np.mean(margins == 0) * 0.5)

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
