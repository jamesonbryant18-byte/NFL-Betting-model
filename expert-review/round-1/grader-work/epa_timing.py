"""4a spot-check: is eff_epa built from pregame plays only? Truncate the season after week W and
corrupt week-W plays' EPA; week-W features must not move."""
import sys
sys.path.insert(0, 'src')
import numpy as np, pandas as pd
import nflmodel.factors as F

orig = F.load_wide_pbp
SEASON, WEEK = int(sys.argv[1]), int(sys.argv[2])

def patched(season, refresh=False):
    p = orig(season, refresh)
    if season == SEASON:
        p = p[p.week <= WEEK].copy()
        p.loc[p.week == WEEK, 'epa'] = p.loc[p.week == WEEK, 'epa'] + 5.0   # corrupt the game's own plays
    return p

full = F.team_efficiency([SEASON])
F.load_wide_pbp = patched
trunc = F.team_efficiency([SEASON])
F.load_wide_pbp = orig
cols = ['o_epa', 'd_epa']
a = full[full.week == WEEK].set_index(['game_id', 'team'])[cols]
b = trunc[trunc.week == WEEK].set_index(['game_id', 'team'])[cols]
diff = (a - b.reindex(a.index)).abs().max().max()
cache = pd.read_parquet('data/cache/factors_2013_2025.parquet')
gids = sorted(a.index.get_level_values(0).unique())[:5]
print(f'{SEASON} wk{WEEK}: {len(a)} team-games; max |full - truncated&corrupted| on o_epa/d_epa = {diff:.2e}')
for gid in gids:
    c = cache[cache.game_id == gid].iloc[0]
    h, aw = c.home_team, c.away_team
    rec = (b.loc[(gid, h), 'o_epa'] - b.loc[(gid, h), 'd_epa']) - (b.loc[(gid, aw), 'o_epa'] - b.loc[(gid, aw), 'd_epa'])
    print(f'  {gid}: cached eff_epa {c.eff_epa:+.4f}  recomputed from pregame-only data {rec:+.4f}')
