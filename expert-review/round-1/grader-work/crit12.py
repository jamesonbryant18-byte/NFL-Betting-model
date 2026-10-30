"""Criteria 1 and 2 on the 2021-25 hold-out: SU vs closing favorite, MAE, Brier, calibration."""
import sys, json
sys.path.insert(0, 'src'); sys.path.insert(0, '../work')
import numpy as np, pandas as pd
from nflmodel.trends import margin_model_for_history, win_probs, calibrate
from metrics import *

d = pd.read_parquet('../work/holdout.parquet')
tj = json.load(open('data/trends.json'))
b_disc = tj['calibration']['disc_fit']['b']
mm = margin_model_for_history()

def wp(margin, b=b_disc):
    p = win_probs(margin, mm)
    return calibrate(p, dict(a=0.0, b=b)) if b else p

# primary deployed reconstruction: live procedure, factor weights refit on 2013-20 (w_A)
d['projA'] = d.base + d.st + d.trend + d.facA
d['wpA'] = wp(d.projA)
d.to_parquet('../work/holdout.parquet', index=False)
H = d[d.season.between(2021, 2025)].copy()
print('hold-out games', len(H))

print('\n=== 1a SU vs closing favorite (2021-25) ===')
for nm, m in (('deployed (facA 2013-20 weights)', H.wpA), ('deployed w/ facB weights', wp(H.base + H.st + H.trend + H.fac)),
              ('deployed w/ LIVE weights (in-sample)', wp(H.base + H.st + H.trend + H.fac_live)),
              ('frozen base only', wp(H.base, None))):
    r = su_vs_fav(m, H.spread_line, H.result)
    print(f"{nm:<40} n={r['n']} (excl pk {r['n_excl_pk']}, ties {r['n_excl_tie']}) model {r['model']:.4f} fav {r['fav']:.4f} "
          f"diff {100*r['diff']:+.2f} pts se {100*r['se']:.2f} t {r['t']:.2f} | disagree n={r['n_dis']} hit {r['dis_hit']:.3f} "
          f"wins {r['wins_model']} vs {r['wins_fav']}")
print('per season (deployed facA):')
for s, g in H.groupby('season'):
    r = su_vs_fav(g.wpA, g.spread_line, g.result)
    print(f"  {s} n={r['n']} model {r['model']:.4f} fav {r['fav']:.4f} diff {100*r['diff']:+.2f} disagree {r['n_dis']} hit {r['dis_hit']:.3f}")

print('\n=== 1b alternative pick rules on hold-out (deployed facA) ===')
ok = (H.spread_line != 0) & (H.result != 0)
G = H[ok].copy()
home_won = (G.result > 0).to_numpy()
fav_home = (G.spread_line > 0).to_numpy()
mkt = devig_home(G.home_moneyline, G.away_moneyline)
p = G.wpA.to_numpy()
rules = {'model only': p >= 0.5, 'favorite only': fav_home}
for thr in (0.52, 0.55, 0.58, 0.60, 0.65):
    pick = np.where((p >= thr) | (p <= 1 - thr), p >= 0.5, fav_home)
    rules[f'disagree only if model p beyond {thr:.2f}'] = pick
for wgt in (0.2, 0.35, 0.5):
    bl = wgt * p + (1 - wgt) * mkt
    rules[f'blend {wgt:.2f} model + market prob'] = np.where(np.isnan(bl), fav_home, bl >= 0.5)
for k, pick in rules.items():
    acc = (pick == home_won).mean()
    print(f"  {k:<44} {acc:.4f}  ({int((pick==home_won).sum())}/{len(G)})")

print('\n=== 2a MAE vs closing line (2021-25) ===')
for nm, proj in (('deployed facA', H.projA), ('deployed facB', H.base + H.st + H.trend + H.fac),
                 ('deployed LIVE w (in-sample)', H.base + H.st + H.trend + H.fac_live), ('frozen base', H.base)):
    em = (H.result - proj).abs(); el = (H.result - H.spread_line).abs()
    dlt, se, t = paired(em, el)
    print(f"  {nm:<30} MAE {em.mean():.3f} line {el.mean():.3f} diff {dlt:+.3f} se {se:.3f} t {t:+.2f}")
for s, g in H.groupby('season'):
    print(f"   {s}: model {(g.result-g.projA).abs().mean():.3f} line {(g.result-g.spread_line).abs().mean():.3f}")

print('\n=== 2b Brier/logloss vs de-vigged closing ML (2021-25) ===')
ok2 = H.home_moneyline.notna() & H.away_moneyline.notna() & (H.result != 0)
B = H[ok2]
y = (B.result > 0).astype(float).to_numpy()
pm = devig_home(B.home_moneyline, B.away_moneyline)
for nm, pmod in (('deployed facA', B.wpA.to_numpy()), ('frozen base raw', wp(B.base, None)),
                 ('deployed facA, no recal', wp(B.projA, None))):
    bm = (pmod - y) ** 2; bk = (pm - y) ** 2
    lm = -(y * np.log(np.clip(pmod, 1e-6, 1)) + (1 - y) * np.log(np.clip(1 - pmod, 1e-6, 1)))
    lk = -(y * np.log(pm) + (1 - y) * np.log(1 - pm))
    dlt, se, t = paired(bm, bk)
    print(f"  {nm:<26} n={len(B)} Brier model {bm.mean():.4f} market {bk.mean():.4f} diff {dlt:+.4f} (t {t:+.2f}) | "
          f"logloss model {lm.mean():.4f} market {lk.mean():.4f}")

print('\n=== 2c calibration (2021-25, deployed facA) ===')
ph = H.wpA.to_numpy(); yh = (H.result > 0).astype(float).to_numpy(); nt = H.result.to_numpy() != 0
a, b, se = fit_logistic(logit(ph[nt]), yh[nt])
print(f"  home-side logistic: intercept {a:+.3f} slope {b:.3f} (se {se[1]:.3f}) n={nt.sum()}")
pick_home = ph >= 0.5
pp = np.where(pick_home, ph, 1 - ph); won = np.where(pick_home, yh, 1 - yh)
a2, b2, se2 = fit_logistic(logit(pp[nt]), won[nt])
print(f"  picked-side logistic: intercept {a2:+.3f} slope {b2:.3f} (se {se2[1]:.3f})")
bins = np.arange(0.5, 1.0001, 0.05)
cut = pd.cut(pp[nt], bins, include_lowest=True)
tab = pd.DataFrame({'b': cut, 'p': pp[nt], 'w': won[nt]}).groupby('b', observed=True).agg(n=('w', 'size'), said=('p', 'mean'), won=('w', 'mean'))
tab['gap_pts'] = 100 * (tab.won - tab.said)
tab['se_pts'] = 100 * np.sqrt(tab.said * (1 - tab.said) / tab.n)
print(tab.round(3).to_string())
# market reference
pmh = devig_home(H.home_moneyline, H.away_moneyline)
okm = nt & ~np.isnan(pmh)
a3, b3, se3 = fit_logistic(logit(pmh[okm]), yh[okm])
print(f"  market home-side logistic slope {b3:.3f} (se {se3[1]:.3f})")
