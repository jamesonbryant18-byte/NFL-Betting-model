"""
bet_ledger.py -- the model's own bets, one row each, graded (expert review
round 2, 2026-10-29).

Built from the archive (picks/<season>/weekNN_leans.csv, never changed) and
the recorded closes: each bet's number and price, both spread prices and the
stake (archived from Week 8 on), the model's chance the bet wins, result,
profit per $1 and at $5, FanDuel's close and the value at the price taken.
Unplayed games have a blank result.

    .venv/bin/python -W ignore scripts/bet_ledger.py
    .venv/bin/python -W ignore scripts/bet_ledger.py --season 2026

Writes data/model_bet_ledger_<season>.csv. review_week.py rebuilds it weekly.
"""
import argparse
import sys

sys.path.insert(0, "src")

from nflmodel.config import CURRENT_SEASON
from nflmodel.data import load_games
from nflmodel.scorecard import write_ledger

ap = argparse.ArgumentParser()
ap.add_argument("--season", type=int, default=CURRENT_SEASON)
args = ap.parse_args()

path, led = write_ledger(args.season, load_games())
done = led[led.out != ""]
print(f"{len(led)} bets ({len(done)} graded, {len(led) - len(done)} not played yet) -> {path}")
if len(done):
    w, l, p = (done.out == "W").sum(), (done.out == "L").sum(), (done.out == "P").sum()
    v = done.value_at_close.dropna()
    print(f"graded: {w}-{l}" + (f"-{p}" if p else "") + f", ${done.pnl_at_5.sum():+.2f} at $5 a bet, "
          f"value at the price taken {v.mean():+.1%} a bet on {len(v)}")
