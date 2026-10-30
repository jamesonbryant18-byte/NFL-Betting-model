"""3c(iv): live market prior includes the current week's lines; the replay does not. Measure it."""
import sys, json
sys.path.insert(0, 'src'); sys.path.insert(0, '../work')
from dataclasses import replace
import numpy as np, pandas as pd
from nflmodel.config import CACHE_DIR, RATINGS
from nflmodel.model import NFLModel
from nflmodel.ratings import qb_value, fit_market_ratings
from nflmodel.data import load_games
from metrics import su_vs_fav, paired

df = pd.read_parquet(CACHE_DIR / 'dataset_2010_2025.parquet').sort_values(['season', 'week']).reset_index(drop=True)
best = json.loads((CACHE_DIR / 'tuning_results.json').read_text())[0]
params = replace(RATINGS, **{k: v for k, v in best.items() if k in RATINGS.__dataclass_fields__})
rows = []
for season in range(2021, 2026):
    for week in sorted(df.loc[df.season == season, 'week'].unique()):
        slate = df[(df.season == season) & (df.week == week) & df.played & df.spread_line.notna()]
        if slate.empty:
            continue
        mg = df.copy()
        cur = (mg.season == season) & (mg.week == week)
        mg.loc[cur, 'played'] = False          # what the live run sees: this week's lines, games unplayed
        m = NFLModel(params=params, qb_lambda=best['qb_lambda']).fit(df, season, week, market_games=mg)
        for _, g in slate.iterrows():
            proj = (m.team_ratings.get(g.home_team, 0) + qb_value(m.qb_ratings, g.home_qb_name)
                    - m.team_ratings.get(g.away_team, 0) - qb_value(m.qb_ratings, g.away_qb_name)
                    + (0 if g.neutral else m.hfa))
            rows.append(dict(game_id=g.game_id, season=season, week=week, live_prior=proj, w=m.market_prior_weight_used))
L = pd.DataFrame(rows)
base = pd.read_parquet('../work/holdout.parquet')
x = base.merge(L.drop(columns=['season', 'week']), on='game_id')
print('games', len(x))
dd = (x.live_prior - x.base)
print(f'|live-prior proj - replay proj|: mean {dd.abs().mean():.3f} pts, 90th pct {dd.abs().quantile(.9):.3f}, max {dd.abs().max():.3f}')
print('by week bucket mean |diff|:', x.assign(d=dd.abs()).groupby(pd.cut(x.week, [0, 2, 4, 8, 12, 22])).d.mean().round(3).to_dict())
print(f'|base - line| replay {np.abs(x.base - x.spread_line).mean():.3f}  live-prior {np.abs(x.live_prior - x.spread_line).mean():.3f}')
for nm, p in (('replay (as scored)', x.base), ('live-style prior', x.live_prior)):
    e = (x.result - p).abs(); r = su_vs_fav(np.where(p > 0, 0.6, 0.4), x.spread_line, x.result)
    edge = (p - x.spread_line).abs()
    print(f'  {nm:<20} MAE {e.mean():.3f}  SU {r["model"]:.4f} (fav {r["fav"]:.4f}) disagreements {r["n_dis"]}  '
          f'games with |edge|>=1.5: {(edge >= 1.5).sum()}  >=3: {(edge >= 3).sum()}')
d, se, t = paired((x.result - x.live_prior).abs(), (x.result - x.base).abs())
print(f'  MAE live-style minus replay {d:+.3f} (t {t:+.2f}) -- note: live-style here leaks nothing; these lines are known pregame')

# 2026 now: which unplayed games carry lines in the live loader (look-ahead lines also enter the live prior)
g = load_games()
g26 = g[g.season == 2026]
print('2026 unplayed games with a spread_line in the loader today:', g26[~g26.played & g26.spread_line.notna()].groupby('week').size().to_dict())
