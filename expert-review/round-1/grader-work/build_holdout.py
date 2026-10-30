"""Grader reconstruction of the deployed stack on 2013-2025 walk-forward projections.

Run from the scratch copy root with PYTHONPATH=src. Writes work/holdout.parquet.
Components (each kept as its own column so ablations are post-processing):
  base      frozen walk-forward projection (ratings + joint QB + HFA + market prior, as replayed)
  st        EPA self-tune nudge (adjust_lab.run: epa, alpha 1, hl 3, clip 14, cap 0.5)
  trend     -1.5 * sign(base - line) when |base - line| >= 3 (the one live trend fix)
  fac_*     factor terms with weights refit on 2013-2020 only (same ridge+LOSO as factor_lab)
  fac_live_* factor terms with the LIVE weights (fit 2013-2025: in-sample for 2021-25)
"""
import sys, json
sys.path.insert(0, 'src'); sys.path.insert(0, 'scripts')
import numpy as np, pandas as pd
from nflmodel.config import CACHE_DIR, FACTORS
from nflmodel.trends import margin_model_for_history, win_probs, calibrate

OUT = sys.argv[1]
base = pd.read_parquet(CACHE_DIR / 'base_projections_2013_2025.parquet')
ds = pd.read_parquet(CACHE_DIR / 'dataset_2010_2025.parquet')
fac = pd.read_parquet(CACHE_DIR / 'factors_2013_2025.parquet')[['game_id', 'inj_total', 'eff_epa', 'rt_rest_diff']]
d = base.merge(ds[['game_id', 'home_spread_odds', 'away_spread_odds', 'gameday', 'weekday', 'div_game']],
               on='game_id', how='left').merge(fac, on='game_id', how='left')
d = d.sort_values(['season', 'week']).reset_index(drop=True)

# --- EPA self-tune exactly as adjust_lab.run does it
import adjust_lab as al
tg = al.team_game_stats(range(2013, 2026))
d2 = al.attach(d, tg).sort_values(['season', 'week']).reset_index(drop=True)
st = al.run(d2, 'epa', 1.0, half_life=3.0, clip=14.0, max_adj=0.5)
d = d2.copy()
d['st'] = st['adj'].to_numpy()
d['base'] = d.projected_margin
gap = d.base - d.spread_line
d['trend'] = np.where(gap.abs() >= 3, -1.5 * np.sign(gap), 0.0)

# --- factor weights refit on 2013-2020 only (factor_lab.fit_family procedure)
cols = ['inj_total', 'eff_epa', 'rt_rest_diff']
X = d[cols].fillna(0.0).to_numpy()
TUNE = list(range(2013, 2021))
tune = d.season.isin(TUNE).to_numpy()
ALPHAS = [1, 3, 10, 30, 100, 300, 1000, 3000]

def ridge_fit(X, y, alpha):
    mu, sd = X.mean(0), X.std(0) + 1e-12
    Z = (X - mu) / sd
    b = np.linalg.solve(Z.T @ Z + alpha * np.eye(Z.shape[1]), Z.T @ (y - y.mean()))
    return b / sd

def fit(target):
    y = target.to_numpy()
    best, best_a = np.inf, None
    for a in ALPHAS:
        err = 0.0
        for s in TUNE:
            tr = tune & (d.season != s).to_numpy(); te = (d.season == s).to_numpy()
            w = ridge_fit(X[tr], y[tr], a)
            # same as factor_lab: prediction centred on train mean
            mu = X[tr].mean(0)
            pred = (X[te] - mu) @ w + y[tr].mean()
            err += np.abs(y[te] - pred).sum()
        if err < best:
            best, best_a = err, a
    return ridge_fit(X[tune], y[tune], best_a), best_a

w_A, a_A = fit(d.result - d.base)                              # factor_lab target (frozen model miss)
w_B, a_B = fit(d.result - (d.base + d.st + d.trend))           # target with the live trend pull + self-tune
print('2013-20 weights (target result-base):', dict(zip(cols, np.round(w_A, 4))), 'alpha', a_A)
print('2013-20 weights (target result-base-st-trend):', dict(zip(cols, np.round(w_B, 4))), 'alpha', a_B)
print('live weights (2013-2025 fit):', FACTORS)
w_live = np.array([FACTORS['inj_total'], FACTORS['eff_epa'], FACTORS['rt_rest_diff']])
for nm, w in (('fac', w_B), ('facA', w_A), ('fac_live', w_live)):
    for c, wi in zip(cols, w):
        d[f'{nm}_{c}'] = wi * d[c].fillna(0.0)
    d[nm] = sum(d[f'{nm}_{c}'] for c in cols)

d['proj'] = d.base + d.st + d.trend + d.fac            # deployed stack, clean hold-out weights
d['proj_live_w'] = d.base + d.st + d.trend + d.fac_live

# --- probabilities: same margin model run_week uses; calibration b fit on 2013-20 (disc_fit)
tj = json.load(open('data/trends.json'))
b_disc = tj['calibration']['disc_fit']['b']; b_live = tj['calibration']['b']
mm = margin_model_for_history()
for nm in ('base', 'proj', 'proj_live_w'):
    d[f'wp_raw_{nm}'] = win_probs(d[nm], mm)
d['wp_proj'] = calibrate(d.wp_raw_proj.to_numpy(), dict(a=0.0, b=b_disc))
d['wp_proj_bl'] = calibrate(d.wp_raw_proj.to_numpy(), dict(a=0.0, b=b_live))
d['wp_live_w'] = calibrate(d.wp_raw_proj_live_w.to_numpy(), dict(a=0.0, b=b_live))
print('calibration b_disc', b_disc, 'b_live', b_live)
d.to_parquet(OUT, index=False)
print('saved', OUT, d.shape)
