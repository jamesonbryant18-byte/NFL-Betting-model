"""
design_checks.py — the two design questions flagged 2026-10-14, tested
2026-10-31 (expert review round 2, fix 8). Fit on 2013-2020, checked on
2021-2025; ship only what holds. Neither held; nothing was changed.

(a) QB counted twice? The market prior is backed out of spreads with no QB
    term, so it already holds each team's usual QB, and the model adds the QB
    on top. Variant: take each game's QB values (the model's own, fit through
    that week) out of the lines before backing the prior out.
    Result: error a little lower (2021-25 9.855 vs 9.876, t -1.4; 2013-20
    t -0.2), straight up WORSE (65.49% vs 66.06%, t -2.0; 2013-20 -0.23).
    Not shipped: straight-up accuracy is his first goal.

(b) The trend pull's 3-pt cliff vs a smooth pull. Same 1.5-pt cap, pull
    rising from 0 at a gap of `a` to the full 1.5 at 3; `a` chosen on
    2013-2020 (a = 0: the model meets the line halfway, up to 1.5).
    Result: error lower in both periods (2021-25 9.833 vs 9.876, t -2.4;
    Brier t -2.1; all five seasons), straight up unchanged (66.27% vs 66.06%,
    t 0.4; 5 seasons better, 6 worse of 13), fewer bets (563 vs 653) and a
    worse replayed card (-1.8% vs -0.3% a bet, both inside the noise).
    Run through the trend checker, it also switched on "favorites in week
    15+", which the checker had rejected the week before: fragile. Not
    shipped: it helps neither winners nor bets. Left uncapped, every smooth
    pull fit on 2013-2020 runs to "move all the way to the line", the known
    result that the line is more accurate than the model.

    .venv/bin/python -W ignore scripts/build_structural_bases.py   # once, for (a)
    .venv/bin/python -W ignore scripts/design_checks.py
"""
import sys

sys.path.insert(0, "src")
import numpy as np
import pandas as pd

from nflmodel import replay
from nflmodel.config import CACHE_DIR

full = replay.deployed()
d0 = replay.load()
gap = (d0.base - d0.spread_line).to_numpy(float)
res = d0.result.to_numpy(float)
TUNE = d0.season.isin(replay.TUNE).to_numpy()


def score(dv, period, plan=None):
    m = dv.season.isin(period).to_numpy()
    h = dv[m]
    r = h.result.to_numpy(float)
    dec = r != 0
    wp = replay.apply_win_pct(h, h.proj.to_numpy(float), plan or dv.attrs["win_plan"])
    su = ((wp >= 0.5) == (r > 0)).astype(float)
    return su, np.abs(r - h.proj.to_numpy(float)), (wp - (r > 0)) ** 2, \
        replay.card_summary(replay.card(h.assign(wp=wp))), dec


def compare(label, dv, plan=None):
    rows = []
    for period, name in ((replay.HOLD, "2021-25"), (replay.TUNE, "2013-20")):
        fsu, ferr, fbr, fcard, dec = score(full, period)
        su, err, br, card, _ = score(dv, period, plan)
        dsu, sesu, _ = replay._paired(su[dec], fsu[dec])
        dm, sem, _ = replay._paired(err, ferr)
        db, seb, _ = replay._paired(br[dec], fbr[dec])
        rows.append(dict(period=name, SU=100 * su[dec].mean(), SU_now=100 * fsu[dec].mean(),
                         tSU=dsu / sesu, MAE=err.mean(), MAE_now=ferr.mean(), tMAE=dm / sem,
                         tBrier=db / seb, bets=card["n"], bets_now=fcard["n"],
                         ROI=100 * card["roi"], ROI_now=100 * fcard["roi"]))
    print(f"\n  {label}  (vs the model as it runs; t < 0 on MAE/Brier = the change is better)")
    print(pd.DataFrame(rows).round(3).to_string(index=False))


pd.set_option("display.width", 220)

# (a) QB taken out of the market prior
sb_path = CACHE_DIR / "structural_bases_2013_2025.parquet"
if sb_path.exists():
    sb = d0[["game_id"]].merge(pd.read_parquet(sb_path), on="game_id", how="left")
    dv = replay.deployed(d=d0.assign(base=sb.qbprior.to_numpy()))
    compare("(a) QB values taken out of the lines behind the market prior", dv)
else:
    print("  (a) skipped: run scripts/build_structural_bases.py first")

# (b) smooth trend pull at the same 1.5 cap, start chosen on 2013-2020
cliff = full.trend.to_numpy(float)
mae = {}
for a in (0.0, 0.5, 1.0, 1.5, 2.0, 2.5):
    t = -np.sign(gap) * 1.5 * np.clip((np.abs(gap) - a) / (3 - a), 0, 1)
    mae[a] = (np.abs(res[TUNE] - (d0.base.to_numpy()[TUNE] + t[TUNE])).mean(), t)
print("\n  (b) smooth pull, 2013-20 error by where the pull starts (cliff: "
      f"{np.abs(res[TUNE] - (d0.base.to_numpy()[TUNE] + cliff[TUNE])).mean():.4f})")
for a, (m, _) in mae.items():
    print(f"      from {a:.1f} pts: {m:.4f}")
best = min(mae, key=lambda a: mae[a][0])
compare(f"(b) smooth pull from {best:.1f} to 3 pts, max 1.5 (chosen on 2013-20)",
        replay.deployed(d=d0, trend=mae[best][1]))
