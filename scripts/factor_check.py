"""
factor_check.py — weekly report card for the game factors (config.FACTORS).

Jameson, 2026-09-28: add factors to the model, and "if the model performs
poorly in a certain area then adjust it. Keep doing so until you find some
factors that you like."

For every graded 2026 game that was published WITH factors (Week 4 on), this
asks of each factor separately: did its push move the projection toward what
actually happened, or away? And did it flip any winner, right or wrong?

One week proves nothing (16 games; a factor worth 0.1 pt/game needs
hundreds to show). So the rule is:
  * < 48 graded games: report only.
  * 48+ games and a factor's error change is worse at t <= -2: FLAGGED --
    re-fit it in scripts/factor_lab.py with this season's games added, or swap
    in the next candidate (lab batch 1 & 2 tables, CLAUDE.md section 0).
  * The flag is an alarm for review, never an automatic re-weight.

    .venv/bin/python -W ignore scripts/factor_check.py
"""
import sys

sys.path.insert(0, "src")
import numpy as np
import pandas as pd

from nflmodel.archive import ARCHIVE_DIR
from nflmodel.config import CURRENT_SEASON
from nflmodel.data import load_games

MIN_GAMES = 48
FACTORS = [("factor_inj", "non-QB injuries"), ("factor_epa", "efficiency (EPA/play)"),
           ("factor_rest", "rest days")]

games = load_games()
done = games[(games.season == CURRENT_SEASON) & games.result.notna()]
rows = []
for p in sorted((ARCHIVE_DIR / str(CURRENT_SEASON)).glob("week*_picks.csv")):
    df = pd.read_csv(p)
    if "factor_adj" not in df.columns:
        continue
    df["week"] = int(p.name[4:6])
    rows.append(df)
if not rows:
    print("No published weeks with game factors yet (they start in 2026 Week 4).")
    sys.exit(0)
pk = pd.concat(rows, ignore_index=True)
pk[["away_team", "home_team"]] = pk.matchup.str.split(" @ ", expand=True)
pk = pk.merge(done[["week", "home_team", "away_team", "result"]],
              on=["week", "home_team", "away_team"], how="inner")
if pk.empty:
    print("Weeks with factors are published but none graded yet.")
    sys.exit(0)

home_margin = np.where(pk.at_home, pk.proj_margin, -pk.proj_margin)
res = pk.result.to_numpy()
n = len(pk)
print("=" * 78)
print(f"  GAME FACTORS — report card, {CURRENT_SEASON}, {n} graded game(s) with factors")
print("=" * 78)
print(f"  {'factor':<24}{'avg push':>9}{'helped':>8}{'hurt':>6}{'err chg':>9}{'t':>6}"
      f"{'flips right':>13}{'wrong':>7}  status")
flags = []
for col, label in FACTORS + [("factor_adj", "ALL FACTORS")]:
    if col not in pk.columns:
        continue
    f = pk[col].fillna(0).to_numpy()
    without = home_margin - f
    d = np.abs(res - without) - np.abs(res - home_margin)     # + = factor helped
    moved = np.abs(f) >= 0.05
    t = d.mean() / (d.std(ddof=1) / np.sqrt(n)) if n > 2 and d.std() > 0 else 0.0
    flip = (np.sign(without) != np.sign(home_margin)) & (res != 0)
    right = (flip & (np.sign(home_margin) == np.sign(res))).sum()
    status = "watching (small sample)" if n < MIN_GAMES else ("FLAGGED" if t <= -2 else "ok")
    if status == "FLAGGED":
        flags.append(label)
    print(f"  {label:<24}{np.abs(f).mean():>9.2f}{(d[moved] > 0).sum():>8}{(d[moved] < 0).sum():>6}"
          f"{d.mean():>+9.3f}{t:>6.1f}{right:>13}{flip.sum() - right:>7}  {status}")
print()
print("  err chg: average points the factor moved the projection TOWARD the final")
print("  margin (+ good). flips: games where the factor changed the picked winner.")
print(f"  A factor is only judged after {MIN_GAMES}+ games; before that it is noise.")
if flags:
    print(f"\n  FLAGGED: {', '.join(flags)} — re-fit or replace (scripts/factor_lab.py).")
