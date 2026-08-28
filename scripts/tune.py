"""
tune.py — hyperparameter grid search.

Fit on TRAIN seasons only. The held-out seasons are never touched here; they
exist so that the final number reported is one the model has not been
optimized against. Searching the grid on all seasons and then reporting the
best result is the most common way betting models lie to their authors.
"""
import sys, json, itertools, time
sys.path.insert(0, 'src')
import numpy as np, pandas as pd
from dataclasses import replace
from nflmodel.ratings import fit_ratings_qb, qb_value
from nflmodel.config import RATINGS

TRAIN = list(range(2013, 2021))     # 2013-2020 fit
df = pd.read_parquet('data/cache/dataset_2010_2025.parquet').sort_values(['season','week']).reset_index(drop=True)

def run(params, qb_lambda, seasons):
    err = []
    for season in seasons:
        for week in sorted(df.loc[df.season==season,'week'].unique()):
            slate = df[(df.season==season)&(df.week==week)&df.played&df.spread_line.notna()]
            if slate.empty: continue
            tr, qr, hfa = fit_ratings_qb(df, season, week, params, qb_lambda=qb_lambda)
            for _, g in slate.iterrows():
                proj = ((tr.get(g.home_team,0.)+qb_value(qr,g.home_qb_name))
                      - (tr.get(g.away_team,0.)+qb_value(qr,g.away_qb_name))
                      + (0. if g.neutral else hfa))
                err.append(abs(g.result - proj))
    return float(np.mean(err))

GRID = dict(
    ridge_lambda        = [3, 6, 12, 25, 50],
    recency_decay       = [0.93, 0.96, 0.98, 0.99],
    epa_margin_weight   = [0.0, 0.5, 0.8, 1.0],
    offseason_weeks_equiv = [15, 38, 70],
    qb_lambda           = [20, 40, 80],
)

keys = list(GRID)
combos = list(itertools.product(*[GRID[k] for k in keys]))
print(f'searching {len(combos)} combinations on {TRAIN[0]}-{TRAIN[-1]}', flush=True)

results = []
t0 = time.time()
for i, vals in enumerate(combos, 1):
    cfg = dict(zip(keys, vals))
    qbl = cfg.pop('qb_lambda')
    p = replace(RATINGS, **cfg)
    mae = run(p, qbl, TRAIN)
    results.append({**cfg, 'qb_lambda': qbl, 'train_mae': mae})
    if i % 25 == 0:
        best = min(results, key=lambda r: r['train_mae'])
        el = time.time()-t0
        print(f'  {i}/{len(combos)}  {el:.0f}s  best_mae={best["train_mae"]:.4f}', flush=True)

results.sort(key=lambda r: r['train_mae'])
json.dump(results, open('data/cache/tuning_results.json','w'), indent=2)
print('\nTOP 10:')
for r in results[:10]:
    print('  mae=%.4f  lam=%-3g decay=%-5g epaw=%-4g off=%-3g qblam=%-3g'
          % (r['train_mae'], r['ridge_lambda'], r['recency_decay'],
             r['epa_margin_weight'], r['offseason_weeks_equiv'], r['qb_lambda']))
