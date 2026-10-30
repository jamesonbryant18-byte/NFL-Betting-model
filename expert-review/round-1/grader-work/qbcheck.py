"""8a: archived assumed starter (weekNN_meta.json) vs actual starter (attempts leader)."""
import sys, json
sys.path.insert(0, 'src')
import pandas as pd
from nflmodel.data import load_games
from nflmodel.teamstats import normalize_name

q = pd.read_parquet('data/cache/qb_attempts_2026.parquet')
lead = q.sort_values('attempts', ascending=False).drop_duplicates(['week', 'team'])
games = load_games(); g26 = games[(games.season == 2026) & games.played]
rows = []
for w in range(1, 8):
    m = json.load(open(f'picks/2026/week{w:02d}_meta.json'))
    st = m['starters']; src = m['starter_source']
    for _, g in g26[g26.week == w].iterrows():
        for side in ('home', 'away'):
            t = g[f'{side}_team']
            act = lead[(lead.week == w) & (lead.team == t)]
            all_q = q[(q.week == w) & (q.team == t)].sort_values('attempts', ascending=False)
            actual = act.player_display_name.iloc[0] if len(act) else None
            assumed = st.get(t)
            if actual and assumed and normalize_name(actual) != normalize_name(assumed):
                rows.append(dict(week=w, team=t, game=f'{g.away_team} @ {g.home_team}', assumed=assumed,
                                 source=src.get(t), actual=actual,
                                 attempts=', '.join(f'{r.player_display_name} {r.attempts}' for r in all_q.itertuples())))
df = pd.DataFrame(rows)
pd.set_option('display.width', 250)
print(df.to_string(index=False))
