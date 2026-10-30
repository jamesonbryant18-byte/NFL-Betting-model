"""
replay_deployed.py — the scorecard of the model as it runs live, on 2021-2025.

The one canonical replay (src/nflmodel/replay.py; expert review 2026-10-29):
every hold-out number about the deployed model -- straight up vs the favorite,
margin error vs the line, win % vs the closing moneyline, the weekly card at
closing prices -- comes from here, so every round measures the same thing.

  clean (default)  factor weights fit on 2013-2020 only; the win-% side
                   walk-forward (each season's slope and margin table from
                   earlier seasons only, as live refits it). THE number to quote.
  --live           the shipped weights (fit on every season): in-sample for
                   2021-25, shown for reference only.

    .venv/bin/python -W ignore scripts/replay_deployed.py
    .venv/bin/python -W ignore scripts/replay_deployed.py --save work/holdout.parquet
"""
import argparse
import sys

sys.path.insert(0, "src")
import pandas as pd

from nflmodel import replay

ap = argparse.ArgumentParser()
ap.add_argument("--live", action="store_true", help="shipped weights (in-sample for 2021-25)")
ap.add_argument("--save", help="write the per-game frame (parquet) for further checks")
args = ap.parse_args()

d = replay.deployed(live=args.live)
hold = d[d.season.isin(replay.HOLD)].reset_index(drop=True)
w = d.attrs["factor_weights"]
print("=" * 78)
print(f"  DEPLOYED MODEL, REPLAYED ON 2021-2025 ({len(hold)} games) -- "
      + ("LIVE weights (in-sample)" if args.live else "fit on 2013-2020 only"))
print("=" * 78)
plan = d.attrs["win_plan"]
print("  factors: " + (", ".join(f"{k} {v:+.3f}" for k, v in w.items()) or "none"))
print("  win-% slope b by season: " + ", ".join(
    f"{s} {plan[s][0]:.3f}" for s in replay.HOLD if s in plan and plan[s][0])
    + ("  (fit on earlier seasons only)" if not args.live else "  (shipped)"))

s = replay.scorecard(hold)
print("\n  STRAIGHT UP  (same games; ties left out)")
print(f"    model     {s['su_model']:.2%}  ({s['wins_model']} of {s['decided']})")
print(f"    favorite  {s['su_favorite']:.2%}  ({s['wins_favorite']})   difference "
      f"{100 * s['su_diff']:+.2f} pts (SE {100 * s['su_diff_se']:.2f}, t {s['su_diff_t']:+.2f})")
print(f"    against the favorite: {s['disagree_won']} of {s['disagree']} right")
print(f"    expected wins: {s['expected_wins_model']:.0f} by the model's odds, "
      f"{s['expected_wins_market']:.0f} by the closing market's")
print("\n  MARGIN AND WIN %")
print(f"    error  model {s['mae_model']:.3f}  line {s['mae_line']:.3f}  (t {s['mae_diff_t']:+.1f})")
print(f"    Brier  model {s['brier_model']:.4f}  market {s['brier_market']:.4f}   "
      f"log loss {s['logloss_model']:.4f} vs {s['logloss_market']:.4f}")
print(f"    calibration slope {s['calibration_slope']:.3f}  (1.00 = honest; below 1 = overconfident)")
t = replay.calibration_table(hold)
print("    picked side, 5-pt bands:")
print("    said  " + "  ".join(f"{r.said:5.1%}" for r in t.itertuples()))
print("    won   " + "  ".join(f"{r.won:5.1%}" for r in t.itertuples()))
print("    off   " + "  ".join(f"{100 * r.off:+5.1f}" for r in t.itertuples()))
print("    SEs   " + "  ".join(f"{r.z:+5.1f}" for r in t.itertuples()))
print("    games " + "  ".join(f"{r.n:>5}" for r in t.itertuples()))

bets = replay.card(hold)
print("\n  THE WEEKLY CARD  (live rules, closing numbers and prices)")


def line(label, x):
    c = replay.card_summary(x)
    if not c.get("n"):
        return
    print(f"    {label:<14} {c['n']:>4} bets  {c['won']}-{c['lost']}-{c['push']}  won "
          f"{c['win_pct']:.1%} (break-even {c['break_even']:.1%}, model said "
          f"{c['expected_win_pct']:.1%})  ROI {c['roi']:+.2%} (SE {c['roi_se']:.2%})")


line("all", bets)
line("spreads", bets[bets.market == "SPREAD"])
line("moneylines", bets[bets.market == "MONEYLINE"])
line("filler", bets[bets.filler])
for season in replay.HOLD:
    line(str(season), bets[bets.season == season])
if args.save:
    hold.to_parquet(args.save, index=False)
    print(f"\n  saved {args.save}")
