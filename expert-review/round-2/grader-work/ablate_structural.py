"""Grader: walk-forward ablation of market prior, joint QB fit, home field on the deployed stack.
Each variant: rebuild base projections 2013-2025 walk-forward, then the deployed post-processing
(trend pull at its 2013-20 size, factor weights + win slope fit on 2013-20) via replay.deployed(d=...).
Scored on 2021-25, paired vs the full deployed model."""
import sys, json, time
sys.path.insert(0, 'src')
import numpy as np, pandas as pd
from dataclasses import replace
from nflmodel.config import CACHE_DIR, RATINGS
from nflmodel.model import NFLModel
from nflmodel.ratings import fit_ratings, fit_market_ratings, blend_with_prior, qb_value
from nflmodel import replay

OUT = sys.argv[1]
df = pd.read_parquet(CACHE_DIR / 'dataset_2010_2025.parquet').sort_values(['season', 'week']).reset_index(drop=True)
best = json.loads((CACHE_DIR / 'tuning_results.json').read_text())[0]
params = replace(RATINGS, **{k: v for k, v in best.items() if k in RATINGS.__dataclass_fields__})
qbl = best['qb_lambda']

rows = []
t0 = time.time()
for season in range(2013, 2026):
    for week in sorted(df.loc[df.season == season, 'week'].unique()):
        slate = df[(df.season == season) & (df.week == week) & df.played & df.spread_line.notna()]
        if slate.empty:
            continue
        # deployed (check), no prior
        m_full = NFLModel(params=params, qb_lambda=qbl).fit(df, season, week, market_games=df)
        m_np = NFLModel(params=params, qb_lambda=qbl).fit(df, season, week, market_games=None)
        # team-only ratings + the same market prior blend as NFLModel.fit
        tr, hfa = fit_ratings(df, season, week, params)
        played = df[(df.season == season) & (df.week < week) & df.played]
        gp = len(played) / 16.0
        mk, mhfa = fit_market_ratings(df, season, params, asof_week=week)
        if any(abs(v) > 1e-9 for v in mk.values()):
            tr = blend_with_prior(tr, mk, gp, params)
            w = params.prior_decay_games / (params.prior_decay_games + max(gp, 0.0)) * params.market_prior_weight
            hfa = (1 - w) * hfa + w * mhfa
        for _, g in slate.iterrows():
            neu = bool(g.neutral)
            def proj(m):
                return (m.team_ratings.get(g.home_team, 0) + qb_value(m.qb_ratings, g.home_qb_name)
                        - m.team_ratings.get(g.away_team, 0) - qb_value(m.qb_ratings, g.away_qb_name)
                        + (0 if neu else m.hfa))
            rows.append(dict(game_id=g.game_id, full=proj(m_full), noprior=proj(m_np),
                             noqb=tr.get(g.home_team, 0) - tr.get(g.away_team, 0) + (0 if neu else hfa),
                             hfa_full=0 if neu else m_full.hfa))
    print(season, round(time.time() - t0, 1), flush=True)
pd.DataFrame(rows).to_parquet(OUT, index=False)
print('saved', OUT)
