"""Walk-forward ablations for components inside the base projection (2021-25 only).
Writes work/wf_<variant>.parquet. Never touches data/cache."""
import sys, json, time
sys.path.insert(0, 'src')
from dataclasses import replace
import pandas as pd
from nflmodel.config import CACHE_DIR, RATINGS
from nflmodel.selftune import walk_forward_adaptive

variant = sys.argv[1]
df = pd.read_parquet(CACHE_DIR / 'dataset_2010_2025.parquet').sort_values(['season', 'week']).reset_index(drop=True)
best = json.loads((CACHE_DIR / 'tuning_results.json').read_text())[0]
params = replace(RATINGS, **{k: v for k, v in best.items() if k in RATINGS.__dataclass_fields__})
qbl = best['qb_lambda']
print('params', {k: best[k] for k in best if k in RATINGS.__dataclass_fields__}, 'qb_lambda', qbl)
deployed = True
if variant == 'no_prior':
    deployed = False
elif variant == 'no_qb':
    df = df.copy()
    df['home_qb_name'] = 'SAMEQB'; df['away_qb_name'] = 'SAMEQB'   # both sides one column -> cancels
elif variant == 'live_loader':
    from nflmodel.data import load_games
    g = load_games()
    df = df.drop(columns=['home_qb_name', 'away_qb_name']).merge(
        g[['game_id', 'home_qb_name', 'away_qb_name']], on='game_id', how='left')
    df = df.sort_values(['season', 'week']).reset_index(drop=True)
t0 = time.time()
bt = walk_forward_adaptive(df, list(range(2021, 2026)), params=params, qb_lambda=qbl, alpha=0.0,
                           deployed=deployed)
bt.to_parquet(f'../work/wf_{variant}.parquet', index=False)
print(variant, len(bt), 'MAE', round((bt.result - bt.projected_margin).abs().mean(), 4), f'{time.time()-t0:.0f}s')
