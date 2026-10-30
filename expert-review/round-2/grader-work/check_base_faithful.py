"""Grader check: do cached base projections equal what the live code path (run_week's
NFLModel.fit with load_fitted params) produces for the same games?"""
import sys, json
sys.path.insert(0, 'src'); sys.path.insert(0, 'scripts')
import numpy as np, pandas as pd
from nflmodel.config import CACHE_DIR
from nflmodel.data import build_dataset, load_games
from nflmodel.model import NFLModel
from nflmodel.ratings import qb_value
import importlib.util
spec = importlib.util.spec_from_file_location('rw', 'scripts/run_week.py')
rw = importlib.util.module_from_spec(spec); spec.loader.exec_module(rw)
params, qb_lambda, fitted = rw.load_fitted()
print('live params', params.ridge_lambda, params.recency_decay, params.offseason_weeks_equiv, 'qb_lambda', qb_lambda)

base = pd.read_parquet(CACHE_DIR / 'base_projections_2013_2025.parquet')
hist = build_dataset(list(range(2010, 2027)))
games = load_games()
ds = pd.read_parquet(CACHE_DIR / 'dataset_2010_2025.parquet')
# cache vs live loader consistency on 2010-2025
h25 = hist[hist.season.between(2010, 2025)].set_index('game_id')
d25 = ds.set_index('game_id')
common = h25.index.intersection(d25.index)
print('dataset rows cache', len(d25), 'live', len(h25), 'common', len(common))
for c in ['home_qb_name', 'away_qb_name', 'result', 'spread_line', 'home_moneyline', 'away_moneyline']:
    a, b = h25.loc[common, c], d25.loc[common, c]
    diff = ~((a == b) | (a.isna() & b.isna()))
    print(f'  {c}: {int(diff.sum())} rows differ')

samples = [(2021, 1), (2021, 9), (2022, 4), (2022, 15), (2023, 2), (2023, 11), (2024, 6), (2024, 17), (2025, 3), (2025, 12)]
out = []
for season, week in samples:
    m = NFLModel(params=params, qb_lambda=qb_lambda)
    m.fit(hist, season, week, market_games=games)
    slate = hist[(hist.season == season) & (hist.week == week) & hist.played & hist.spread_line.notna()]
    for _, g in slate.iterrows():
        p = (m.team_ratings.get(g.home_team, 0) + qb_value(m.qb_ratings, g.home_qb_name)
             - m.team_ratings.get(g.away_team, 0) - qb_value(m.qb_ratings, g.away_qb_name)
             + (0 if g.neutral else m.hfa))
        out.append(dict(season=season, week=week, game_id=g.game_id, live=p))
o = pd.DataFrame(out).merge(base[['game_id', 'projected_margin']], on='game_id', how='left')
o['diff'] = o.live - o.projected_margin
print(o.groupby(['season', 'week'])['diff'].agg(['count', lambda x: x.abs().max(), 'mean']).round(4))
print('overall max |diff|', o['diff'].abs().max().round(5), 'n', len(o), 'missing in cache', o.projected_margin.isna().sum())
