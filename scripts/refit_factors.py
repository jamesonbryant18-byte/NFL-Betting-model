"""
refit_factors.py — re-weight the live game factors, and check the set on the hold-out.

Expert review 2026-10-29: the EPA/play factor hurt on 2021-25 (worse straight
up, margin error and Brier) and the live weights had been set by hand from a
2013-2025 fit with no script behind them. This is that script.

Target: the miss of the model as it runs now, result - (base + trend fix), with
the self-tune off. Ridge, penalty by leave-one-season-out (factor_lab.py's
procedure, via replay.fit_factor_weights).

  1. Each factor set fit on 2013-2020 only, scored on 2021-2025 (never seen),
     with its own 2013-2020 win-% slope. This decides the SET.
  2. The chosen set re-fit on 2013-2025: the weights that go in config.FACTORS.

    .venv/bin/python -W ignore scripts/refit_factors.py
"""
import sys

sys.path.insert(0, "src")
import numpy as np
import pandas as pd

from nflmodel import replay

SETS = {
    "no factors": [],
    "injuries": ["inj_total"],
    "injuries + rest": ["inj_total", "rt_rest_diff"],
    "injuries + rest + EPA/play (old)": ["inj_total", "rt_rest_diff", "eff_epa"],
}

d = replay.load()
d["trend"] = replay.trend_shift(d, fit="disc")
target = d.result - (d.base + d.trend)
hold = d.season.isin(replay.HOLD).to_numpy()

print(f"  FACTOR REFIT -- fit on 2013-2020 ({(~hold).sum()} games), "
      f"scored on 2021-2025 ({hold.sum()} games, never seen)\n")
rows, cards = [], {}
base_err = None
for name, cols in SETS.items():
    w, a = replay.fit_factor_weights(d, cols, target) if cols else ({}, float("nan"))
    x = replay.add_factors(d, w)
    x["proj"] = x.base + x.trend + x.fac
    b = replay.fit_win_slope(x)
    x["wp"] = replay.win_pct(x.proj, b)
    h = x[hold]
    sc = replay.scorecard(h)
    err = np.abs(h.result - h.proj).to_numpy()
    if base_err is None:
        base_err = err
    dm, se, t = replay._paired(err, base_err)
    c = replay.card_summary(replay.card(h))
    cards[name] = c
    rows.append(dict(set=name, weights=", ".join(f"{k} {v:+.3f}" for k, v in w.items()) or "-",
                     alpha=a, slope_b=round(b, 3), su=100 * sc["su_model"],
                     su_fav=100 * sc["su_favorite"], mae=sc["mae_model"], mae_vs_none_t=t,
                     brier=sc["brier_model"], cal_slope=sc["calibration_slope"],
                     card_win=100 * c["win_pct"], card_roi=100 * c["roi"], card_se=100 * c["roi_se"]))
pd.set_option("display.width", 220)
print(pd.DataFrame(rows).round(3).to_string(index=False))
print("\n  su_fav = the closing favorite on the same games; mae_vs_none_t < 0 = lower error "
      "than no factors; cal_slope 1.00 = win % honest on 2021-25")

keep = SETS["injuries + rest"]
w_live, a_live = replay.fit_factor_weights(d, keep, target, seasons=list(range(2013, 2026)))
print(f"\n  live weights, 'injuries + rest' re-fit on 2013-2025 (penalty {a_live:g}):")
print("  FACTORS = dict(" + ", ".join(f"{k}={v:.3f}" for k, v in w_live.items()) + ")")
