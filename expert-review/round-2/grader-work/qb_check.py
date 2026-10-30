import sys, json; sys.path.insert(0,'src')
import pandas as pd
from nflmodel.data import load_games
from nflmodel.teamstats import normalize_name
g=load_games(); g=g[(g.season==2026)&(g.week<=7)]
print([c for c in g.columns if 'qb' in c.lower()])
rows=[]
for w in range(1,8):
    m=json.load(open(f"picks/2026/week{w:02d}_meta.json"))
    st=m["starters"]; src=m["starter_source"]; carried=m.get("carried") or {}
    L=pd.read_csv(f"picks/2026/week{w:02d}_leans.csv")
    P=pd.read_csv(f"picks/2026/week{w:02d}_picks.csv")
    for _,r in g[g.week==w].iterrows():
        for side in ("home","away"):
            t=r[f"{side}_team"]; actual=r[f"{side}_qb_name"]; assumed=st.get(t)
            if assumed is None: continue
            if normalize_name(str(assumed))!=normalize_name(str(actual)):
                mu=f"{r.away_team} @ {r.home_team}"
                bet=L[(L.home_team==r.home_team)&(L.away_team==r.away_team)]
                pk=P[P.matchup==mu]
                rows.append(dict(week=w, team=t, game=mu, assumed=assumed, source=src.get(t), actual=actual,
                                 carried=mu in carried, pick=pk.winner.iloc[0] if len(pk) else None,
                                 bet=bet.bet_side.iloc[0] if len(bet) else None))
d=pd.DataFrame(rows)
pd.set_option("display.width",250)
print(d.to_string())
