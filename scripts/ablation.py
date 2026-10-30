"""
ablation.py — what each piece of the deployed model is worth, on 2021-2025.

Drop one piece at a time from the canonical replay (src/nflmodel/replay.py,
fit on 2013-2020 only) and score the rest on 2021-2025, never seen. Also adds
back the two pieces switched off 2026-10-29, to show why:
  + EPA/play factor   (weights re-fit with it, on 2013-2020)
  + weekly self-tune  (EPA signal, 0.5-pt cap, as adjust_lab replays it)

Effect = full model minus the variant, paired over the same games:
  SU  + = the piece adds correct picks      MAE / Brier  - = the piece helps
A piece HURTS if it is worse on any of them at |t| >= 2 with no significant
gain elsewhere. The win-% side is held at the full model's walk-forward plan
(per-season slope and margin table, replay.win_plan) for every variant
(re-fitting it per variant would credit the recalibration with the change).

Not covered here (each needs a full walk-forward re-run of the ratings):
the market prior blend, the joint QB fit, home field.

    .venv/bin/python -W ignore scripts/ablation.py
"""
import sys

sys.path.insert(0, "src")
sys.path.insert(0, "scripts")
import numpy as np
import pandas as pd

from nflmodel import replay

d = replay.deployed()
plan = d.attrs["win_plan"]
hold = d.season.isin(replay.HOLD).to_numpy()

# + EPA/play: the three-factor set, re-fit on 2013-2020
w3, _ = replay.fit_factor_weights(d, ["inj_total", "rt_rest_diff", "eff_epa"],
                                  d.result - (d.base + d.trend))
epa3 = replay.add_factors(d, w3).fac

# + self-tune: the EPA nudge as it ran live (adjust_lab replays selftune.live_corrections)
import adjust_lab as al
tg = al.team_game_stats(range(2013, 2026))
st_frame = al.attach(d.drop(columns=["projected_margin"]).assign(projected_margin=d.base), tg)
st_frame = st_frame.sort_values(["season", "week"]).reset_index(drop=True)
st = al.run(st_frame, "epa", 1.0, half_life=3.0, clip=14.0, max_adj=0.5)
st = pd.Series(st["adj"].to_numpy(), index=st_frame.game_id).reindex(d.game_id).fillna(0).to_numpy()

variants = {
    "FULL (as deployed)": d.proj,
    "- trend pull (3+ pts, 1.5)": d.proj - d.trend,
    "- injuries factor": d.proj - d.fac_inj,
    "- rest factor": d.proj - d.fac_rest,
    "- all factors": d.proj - d.fac,
    "+ EPA/play factor (off)": d.base + d.trend + epa3,
    "+ weekly self-tune (off)": d.proj + st,
}
H = d[hold].reset_index(drop=True)
res = H.result.to_numpy(float)
y = (res > 0).astype(float)
dec = res != 0


def metrics(proj, recal=True):
    proj = np.asarray(proj, float)[hold]
    wp = replay.apply_win_pct(H, proj, plan, recalibrate=recal)
    su = ((wp >= 0.5) == (res > 0)).astype(float)
    card = replay.card_summary(replay.card(H.assign(proj=proj, wp=wp)))
    return np.abs(res - proj), (wp - y) ** 2, su, card


full_err, full_br, full_su, full_card = metrics(d.proj)
rows = []
for name, proj in list(variants.items()) + [("- win-% recalibration", None)]:
    err, br, su, card = metrics(d.proj, recal=False) if proj is None else metrics(proj)
    if name.startswith("FULL"):
        e = dict(dSU=np.nan, tSU=np.nan, dMAE=np.nan, tMAE=np.nan, dBrier=np.nan, tBrier=np.nan)
    else:
        sgn = -1 if name.startswith("+") else 1        # effect of the piece itself
        dsu, sesu, _ = replay._paired(full_su[dec], su[dec])
        dm, sem, _ = replay._paired(full_err, err)
        db, seb, _ = replay._paired(full_br[dec], br[dec])
        e = dict(dSU=100 * sgn * dsu, tSU=sgn * dsu / sesu if sesu else np.nan,
                 dMAE=sgn * dm, tMAE=sgn * dm / sem if sem else np.nan,
                 dBrier=sgn * db, tBrier=sgn * db / seb if seb else np.nan)
    rows.append(dict(variant=name, SU=100 * su[dec].mean(), MAE=err.mean(),
                     Brier=br[dec].mean(), card_ROI=100 * card["roi"], **e))

pd.set_option("display.width", 220)
print(f"  ABLATION -- deployed model on 2021-2025 ({hold.sum()} games), "
      f"everything fit on 2013-2020")
print(pd.DataFrame(rows).round(3).to_string(index=False))
print("\n  d* = what the piece itself does (variant 'FULL - x': full minus without; "
      "'+ x': with minus full).")
print("  SU: + helps.  MAE / Brier: - helps.  card_ROI is the variant's own card (SE about 3.6%).")
