"""
half_point_rule.py — what Jameson's half-point rule does to the weekly card.

Rule (2026-10-31, config THRESHOLDS.spread_half_points_only): no spread bets
at a whole number (3, 7, ...); Jameson can't place them. The game's moneyline is
still considered, and the card fills from the next bets by chance to win.
It is Jameson's constraint, not a model change, so it ships either way; this
records what it costs or gains (live rules, closing numbers and prices).

Result 2026-10-31 (44% of 2021-25 games close on a whole number):
    no rule          2013-20 1,022 bets ROI +2.65%   2021-25 653 bets ROI -0.30%
    rule (shipped)   2013-20   979 bets ROI +5.57%   2021-25 628 bets ROI -2.76%
                     vs no rule: +27 units (t +1.4)  /  -15 units (t -1.2)
    rule, and skip the whole game (no moneyline instead):
                     2013-20   669 bets ROI +3.47%   2021-25 464 bets ROI -2.54%
                     vs no rule: -4 units (t -0.1)   /  -10 units (t -0.5)
Helps in one period, hurts in the other, neither significant: no measurable
cost. The shipped version keeps the moneyline (the skip-the-game version is
no better and makes a third fewer bets). It does shift the card toward
moneylines (2021-25: 203 -> 360 of the bets), and replayed moneylines run
below spreads (2021-25 with the rule: spreads +7.5% on 268, SE 5.8%;
moneylines -10.4% on 360, SE 5.0%). This season: 4 of the model's 52 bets
were whole-number spreads (NYG +3, TB +3, SEA -3, MIA +7).

    .venv/bin/python -W ignore scripts/half_point_rule.py
"""
import sys
from dataclasses import replace

sys.path.insert(0, "src")
import pandas as pd

from nflmodel import replay
from nflmodel.config import CACHE_DIR, THRESHOLDS
from nflmodel.model import NFLModel


class SkipWholeGames(NFLModel):
    """The alternative: a whole-number game gets no bet at all."""

    def _recommend(self, projected, line, *a, **k):
        rec = super()._recommend(projected, line, *a, **k)
        if line is not None and float(line).is_integer() and rec["bet_side"]:
            return {**rec, "recommendation": "NO BET", "bet_market": "", "bet_side": "",
                    "bet_odds": 0.0, "stake": 0.0}
        return rec

    def _near_miss(self, r, spread_odds):
        if r["spread_line"] is not None and float(r["spread_line"]).is_integer():
            return None
        return super()._near_miss(r, spread_odds)


def show(label, x):
    c = replay.card_summary(x)
    if not c.get("n"):
        print(f"    {label:<28} none")
        return
    print(f"    {label:<28} {c['n']:>4} bets  {c['won']}-{c['lost']}-{c['push']}  won {c['win_pct']:.1%} "
          f"(break-even {c['break_even']:.1%}, model said {c['expected_win_pct']:.1%})  "
          f"ROI {c['roi']:+.2%} (SE {c['roi_se']:.2%})")


def vs(x, base):
    """Units gained over the no-rule card, paired by week."""
    diff = (x.groupby(["season", "week"]).units.sum().reindex(base.index, fill_value=0) - base)
    se = diff.std(ddof=1) * len(diff) ** 0.5
    return f"{diff.sum():+.1f} units vs no rule over {len(diff)} weeks (t {diff.sum() / se:+.2f})"


def whole(x):
    return (x.market == "SPREAD") & x.side.str.split().str[1].astype(float).mod(1).eq(0)


d = replay.deployed()
models = {"no rule": NFLModel(thresholds=replace(THRESHOLDS, spread_half_points_only=False)),
          "rule (shipped)": NFLModel(),
          "rule, skip the whole game": SkipWholeGames()}

print("=" * 78)
print("  HALF-POINT RULE, REPLAYED (live rules, closing numbers and prices)")
print("=" * 78)
cards = {}
for period, name in ((replay.TUNE, "2013-20"), (replay.HOLD, "2021-25")):
    h = d[d.season.isin(period)].reset_index(drop=True)
    print(f"\n  {name}: {h.spread_line.mod(1).eq(0).mean():.0%} of games closed on a whole number")
    base = None
    for label, m in models.items():
        b = cards[name, label] = replay.card(h, model=m)
        show(label, b)
        if base is None:
            base = b.groupby(["season", "week"]).units.sum()
        else:
            print(f"    {'':<28} {vs(b, base)}")

off, on = cards["2021-25", "no rule"], cards["2021-25", "rule (shipped)"]
key = lambda x: x.game_id + "|" + x.side
removed, added = off[~key(off).isin(key(on))], on[~key(on).isin(key(off))]
print("\n  2021-25, what the shipped rule swapped")
show("whole-number spreads cut", removed[whole(removed)])
show("other bets that left", removed[~whole(removed)])
show("bets that took their place", added)
for name, x in (("spreads", "SPREAD"), ("moneylines", "MONEYLINE")):
    show(f"{name}, no rule", off[off.market == x])
    show(f"{name}, rule", on[on.market == x])
for season in replay.HOLD:
    a, b = replay.card_summary(off[off.season == season]), replay.card_summary(on[on.season == season])
    print(f"    {season}  no rule {a['n']:>3} bets ROI {a['roi']:+6.2%}   rule {b['n']:>3} bets ROI {b['roi']:+6.2%}")

led_path = CACHE_DIR.parent / "model_bet_ledger_2026.csv"
if led_path.exists():
    led = pd.read_csv(led_path)
    sp = led[led.market == "SPREAD"]
    w = sp[sp.line.abs().mod(1).eq(0)]
    done = w[w.out.isin(["W", "L", "P"])]
    print(f"\n  2026 SO FAR: {len(w)} of the model's {len(led)} bets were whole-number spreads "
          f"({', '.join(w.bet)}); graded {(done.out == 'W').sum()}-{(done.out == 'L').sum()}-"
          f"{(done.out == 'P').sum()}, ${done.pnl_at_5.sum():+.2f} at $5")
