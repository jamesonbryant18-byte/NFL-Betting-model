import sys; sys.path.insert(0,'src')
import numpy as np, pandas as pd, json
from nflmodel.trends import margin_model_for_history
from nflmodel.market import devig
from nflmodel.config import THRESHOLDS
from nflmodel.closing import ticket
mm=margin_model_for_history()
be=lambda o: -o/(-o+100) if o<0 else 100/(o+100)
pay=lambda o: o/100 if o>0 else 100/abs(o)
rows=[]
for w in range(1,8):
    L=pd.read_csv(f"picks/2026/week{w:02d}_leans.csv"); C=pd.read_csv(f"picks/2026/week{w:02d}_closing.csv")
    gen=json.load(open(f"picks/2026/week{w:02d}_meta.json"))["generated_utc"]
    for _,l in L.iterrows():
        c=C[(C.home_team==l.home_team)&(C.away_team==l.away_team)].iloc[0]
        bh=l.bet_side.split()[0]==l.home_team
        if l.bet_market=="SPREAD":
            close_home_line = -c.close_spread   # home 'favored by' convention in archive: spread_line = home favored by
            # archive spread_line is "home favored by" (positive = home favored); closing close_spread is home spread (negative = home favored)
            hl = float(c.close_spread)
            edge = float(l.projected_margin) - hl
            side_edge = edge if bh else -edge
            ph,pp,pa = mm.cover_prob(float(l.projected_margin), hl)
            pw,pl = (ph,pa) if bh else (pa,ph)
            odds = c.close_home_spread_odds if bh else c.close_away_spread_odds
            ev = pw*pay(odds) - pl
            q = side_edge >= THRESHOLDS.spread_min_edge_pts and ev>0
            rows.append(dict(week=w, bet=l.bet_side, mk="S", pub_line=l.spread_line, close_line=hl, edge_pub=abs(float(l.spread_edge_pts)), edge_close=side_edge, ev_close=ev, still=q))
        else:
            p = float(l.home_win_prob) if bh else 1-float(l.home_win_prob)
            ml = c.close_home_ml if bh else c.close_away_ml
            fh = devig(c.close_home_ml, c.close_away_ml)[0]; fair = fh if bh else 1-fh
            edge = p - fair
            q = edge >= THRESHOLDS.ml_min_edge and THRESHOLDS.ml_max_favorite <= ml <= THRESHOLDS.ml_max_underdog
            rows.append(dict(week=w, bet=l.bet_side, mk="M", pub_line=l.bet_odds, close_line=ml, edge_pub=np.nan, edge_close=edge, ev_close=p*pay(ml)-(1-p), still=q))
d=pd.DataFrame(rows)
pd.set_option("display.width",200)
print(d.to_string())
print("\nstill qualifies at FanDuel close (model's own view unchanged):", int(d.still.sum()), "of", len(d))
print(d.groupby("week").still.agg(['sum','count']).T.to_string())
print("weeks 1,2,7 (mid-week final card):", int(d[d.week.isin([1,2,7])].still.sum()), "of", int(d.week.isin([1,2,7]).sum()), "; weeks 3-6 (game-day card):", int(d[d.week.isin([3,4,5,6])].still.sum()), "of", int(d.week.isin([3,4,5,6]).sum()))
