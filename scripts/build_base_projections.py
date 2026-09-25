"""
build_base_projections.py — the frozen model's walk-forward projections,
saved once so adjustment experiments are post-processing, not re-fits.

Every self-tune variant is additive on top of the frozen projection, and the
frozen fit for week W uses only games before W, so computing it once and
layering variants on top is exactly equivalent to re-fitting per variant.

    .venv/bin/python -W ignore scripts/build_base_projections.py
"""
import sys, json
sys.path.insert(0, 'src')
from dataclasses import replace
import pandas as pd
from nflmodel.config import CACHE_DIR, RATINGS
from nflmodel.selftune import walk_forward_adaptive

df = pd.read_parquet(CACHE_DIR / 'dataset_2010_2025.parquet') \
       .sort_values(['season', 'week']).reset_index(drop=True)
best = json.loads((CACHE_DIR / 'tuning_results.json').read_text())[0]
params = replace(RATINGS, **{k: v for k, v in best.items()
                             if k in RATINGS.__dataclass_fields__})
bt = walk_forward_adaptive(df, list(range(2013, 2026)), params=params,
                           qb_lambda=best['qb_lambda'], alpha=0.0, verbose=True)
bt.to_parquet(CACHE_DIR / 'base_projections_2013_2025.parquet', index=False)
for lo, hi in ((2021, 2025), (2013, 2020)):
    x = bt[bt.season.between(lo, hi)]
    print(lo, hi, len(x), round((x.result - x.projected_margin).abs().mean(), 3))
