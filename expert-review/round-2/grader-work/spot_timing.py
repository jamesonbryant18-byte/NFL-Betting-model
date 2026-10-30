import sys
sys.path.insert(0, 'src')
import numpy as np, pandas as pd
from nflmodel.config import CACHE_DIR, RATINGS
from nflmodel.ratings import _time_index
from nflmodel.roster import load_injuries, OUT_DESIGNATIONS, UNAVAILABLE_STATUS, player_importance, load_snap_counts, _pfr_to_gsis
from nflmodel.depth import load_weekly_rosters
from nflmodel.data import _normalize_team
ds = pd.read_parquet(CACHE_DIR / 'dataset_2010_2025.parquet')
fac = pd.read_parquet(CACHE_DIR / 'factors_2013_2025.parquet').set_index('game_id')
games = ['2021_06_LV_DEN', '2022_12_CIN_TEN', '2023_09_SEA_BAL', '2024_14_LAC_KC', '2025_10_DET_WAS']
for gid in games:
    g = ds[ds.game_id == gid]
    if g.empty:
        print('missing', gid); continue
    g = g.iloc[0]; s, w = int(g.season), int(g.week)
    cut = s * RATINGS.offseason_weeks_equiv + w
    hist = ds[ds.played & (_time_index(ds.season, ds.week, RATINGS) < cut)]
    last = hist.sort_values(['season', 'week']).iloc[-1]
    prior_lines = ds[(ds.season == s) & ds.spread_line.notna() & (ds.week <= w)]
    print(f'\n{gid} ({g.gameday.date() if hasattr(g.gameday, "date") else g.gameday}): ratings fit on {len(hist)} games, latest {last.season}-wk{last.week}; '
          f'prior uses lines from weeks {prior_lines.week.min()}-{prior_lines.week.max()} of {s} ({len(prior_lines)} games); '
          f'rest home {g.home_rest} away {g.away_rest} -> diff {fac.loc[gid, "rt_rest_diff"]}; inj_total {fac.loc[gid, "inj_total"]:+.2f}')
    imp = player_importance(s)
    inj = load_injuries(s); inj = inj[(inj.week == w) & inj.report_status.isin(OUT_DESIGNATIONS)]
    ro = load_weekly_rosters(s); ro = ro[(ro.week == w) & ro.status.isin(UNAVAILABLE_STATUS)]
    snaps = load_snap_counts(s); snaps = snaps[snaps.game_id == gid] if 'game_id' in snaps else snaps.iloc[0:0]
    xw = _pfr_to_gsis(); played_ids = {xw.get(p) for p in snaps.pfr_player_id} if len(snaps) else set()
    for team in (g.home_team, g.away_team):
        a = inj[_normalize_team(inj.team) == team][['gsis_id', 'full_name', 'position', 'report_status']]
        b = ro[_normalize_team(ro.team) == team][['gsis_id', 'full_name', 'position', 'status']] if 'full_name' in ro else ro[_normalize_team(ro.team) == team]
        out = []
        for _, r in a.iterrows():
            v = imp.get(r.gsis_id, 0)
            if v > 0.3: out.append(f"{r.full_name} ({r.position}, {r.report_status}, imp {v:.2f}, played={'YES' if r.gsis_id in played_ids else 'no'})")
        for _, r in b.iterrows():
            v = imp.get(r.gsis_id, 0)
            if v > 0.3: out.append(f"{r.get('full_name', r.gsis_id)} ({r.position}, roster {r.status}, imp {v:.2f}, played={'YES' if r.gsis_id in played_ids else 'no'})")
        print(f'   {team} counted out (imp>0.3): ' + ('; '.join(out) if out else 'none'))
