"""
report.py — the straight-up view of a slate.

The betting sheet answers "where does the model disagree with the price?".
This answers a different and simpler question: "who wins?", every game,
ordered by how sure the model is. The two are not the same list and should
never be confused -- a 75% favorite that the market has priced at 75% is the
most confident pick on the board and the worst bet on it.

Confidence here is win probability, which in Week 1 is roughly 80% inherited
from the market prior. Read it as the model's best guess at the winner, not
as evidence of an edge.
"""

from __future__ import annotations

import pandas as pd

# Win-probability bands. The bottom band exists because a 50.2% pick is not a
# pick, and presenting it as the 14th-most-confident winner implies a
# discrimination the model does not have.
TIERS = [
    (0.70, "strong"),
    (0.62, "solid"),
    (0.57, "lean"),
    (0.53, "slight"),
    (0.00, "coin flip"),
]


def _tier(p: float) -> str:
    for floor, label in TIERS:
        if p >= floor:
            return label
    return "coin flip"


def straight_up_ranking(slate: pd.DataFrame) -> pd.DataFrame:
    """
    Every game as a predicted winner, most confident first.

    The winner is whichever side the win probability favours, and the margin
    is reported from that side. Where the two disagree -- possible only inside
    a tenth of a point, because probability comes from tilting the empirical
    margin distribution rather than from the point estimate alone -- the game
    is a coin flip and is labelled one.
    """
    rows = []
    for _, g in slate.iterrows():
        home_favored = g.home_win_prob >= 0.5
        win_prob = g.home_win_prob if home_favored else 1.0 - g.home_win_prob
        margin = g.projected_margin if home_favored else -g.projected_margin
        rows.append({
            "winner": g.home_team if home_favored else g.away_team,
            "loser": g.away_team if home_favored else g.home_team,
            "matchup": f"{g.away_team} @ {g.home_team}",
            "at_home": bool(home_favored),
            "win_prob": float(win_prob),
            "proj_margin": float(margin),
            "moneyline": float(g.home_ml if home_favored else g.away_ml),
            # Does the model's winner match the one the market favours?
            "market_favorite": bool((g.spread_line > 0) == home_favored)
                               if g.spread_line != 0 else True,
            "confidence": _tier(float(win_prob)),
            # A pick whose probability and projected margin point opposite ways
            # is not a pick, whatever the ranking says.
            "consistent": bool(margin > 0),
        })

    out = pd.DataFrame(rows).sort_values("win_prob", ascending=False)
    out.loc[~out["consistent"], "confidence"] = "coin flip"
    out.insert(0, "rank", range(1, len(out) + 1))
    return out.reset_index(drop=True)


def format_ranking(ranked: pd.DataFrame) -> str:
    """The straight-up ranking as a terminal block."""
    lines = []
    lines.append("=" * 78)
    lines.append("  PREDICTED WINNERS — most confident first")
    lines.append("=" * 78)
    lines.append(f"  {'#':>2}  {'pick':<5}{'over':<6}{'win%':>7}{'margin':>9}{'ml':>7}"
                 f"   {'confidence':<11}{'vs market':<10}")
    lines.append("  " + "-" * 74)
    for _, r in ranked.iterrows():
        site = "" if r.at_home else "@"
        tag = "favorite" if r.market_favorite else "UNDERDOG"
        lines.append(
            f"  {r['rank']:>2}. {r.winner:<5}{site + r.loser:<6}"
            f"{r.win_prob:>7.1%}{r.proj_margin:>+9.1f}{int(r.moneyline):>+7}"
            f"   {r.confidence:<11}{tag:<10}"
        )
    lines.append("  " + "-" * 74)
    flips = int((ranked.confidence == "coin flip").sum())
    dogs = int((~ranked.market_favorite).sum())
    lines.append(f"  {len(ranked)} games — {flips} coin flip(s), "
                 f"{dogs} pick(s) against the market favorite.")
    lines.append("=" * 78)
    return "\n".join(lines)
