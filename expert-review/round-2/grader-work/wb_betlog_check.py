import sys; sys.path.insert(0,'src')
import numpy as np, pandas as pd, openpyxl
from nflmodel.data import load_games
WB="../work/wb/NFL_Model_2026_Week08.xlsx"
wb=openpyxl.load_workbook(WB)
ws=wb["Bet Log"]
hdr=[c.value for c in ws[10]]
rows=[]
for r in ws.iter_rows(min_row=11, max_row=ws.max_row, values_only=True):
    if r[0] is None: continue
    rows.append(dict(zip(hdr,r)))
bl=pd.DataFrame(rows)
print("Bet Log rows:", len(bl), bl.Week.value_counts().sort_index().to_dict())
g=load_games(); g=g[g.season==2026]
lb=pd.read_csv("../work/live_bets.csv")
# --- check every row with a model bet against my settled bets
bets=bl[(bl["Model Bet"]!="—") & (bl.Week<=7)].copy()
print("model bets in Bet Log wk1-7:", len(bets), " mine:", len(lb))
m=bets.merge(lb, left_on=["Week","Model Bet"], right_on=["week","bet"], how="outer", indicator=True)
print(m._merge.value_counts().to_dict())
res_map={"WIN":"W","LOSS":"L","PUSH":"P"}
bad_res=m[m["Model Bet Result"].map(res_map)!=m.out]
print("result mismatches:", len(bad_res)); print(bad_res[["Week","Model Bet","Model Bet Result","out"]].to_string() if len(bad_res) else "")
d=(m["Model Bet Value @ Close"].astype(float)-m.value_at_close).abs()
print("value@close max abs diff:", d.max(), " mean in sheet:", m["Model Bet Value @ Close"].astype(float).mean(), " mine:", lb.value_at_close.mean())
# --- check picks, winners, favorites per game vs archive + results
errs=[]
for _,r in bl[bl.Week<=7].iterrows():
    wk=int(r.Week); away,home=r.Game.split(" @ ")
    P=pd.read_csv(f"picks/2026/week{wk:02d}_picks.csv")
    p=P[P.matchup==r.Game]
    if p.empty: errs.append((wk,r.Game,"not in archive picks")); continue
    p=p.iloc[0]
    if p.winner!=r["Model Picked"]: errs.append((wk,r.Game,"pick",p.winner,r["Model Picked"]))
    if abs(p.win_prob-r["Win Chance"])>1e-9: errs.append((wk,r.Game,"winprob",p.win_prob,r["Win Chance"]))
    gg=g[(g.week==wk)&(g.home_team==home)&(g.away_team==away)].iloc[0]
    hs,as_=int(gg.home_score),int(gg.away_score)
    if r["Final Score"]!=f"{away} {as_} – {home} {hs}": errs.append((wk,r.Game,"score",r["Final Score"],f"{away} {as_} – {home} {hs}"))
    win = home if hs>as_ else (away if as_>hs else "TIE")
    if r.Winner!=win: errs.append((wk,r.Game,"winner",r.Winner,win))
    right = "TIE" if win=="TIE" else ("YES" if p.winner==win else "NO")
    if r["Model Right?"]!=right: errs.append((wk,r.Game,"right",r["Model Right?"],right))
    # favorite at publication = archived moneyline sign / market_favorite
    fav = p.winner if bool(p.market_favorite) else p.loser
    if r.Favorite!=fav: errs.append((wk,r.Game,"fav",r.Favorite,fav))
    fr = "—" if win=="TIE" else ("YES" if fav==win else "NO")
    if r["Favorite Right?"]!=fr: errs.append((wk,r.Game,"favright",r["Favorite Right?"],fr))
print("per-game mismatches:", len(errs))
for e in errs: print("   ",e)
# --- summary formula values recomputed from the cells
I=bl[bl.Week<=8]["Model Right?"]; R=bl["Favorite Right?"]
y,n=(I=="YES").sum(),(I=="NO").sum(); fy,fn=(R=="YES").sum(),(R=="NO").sum()
v=bl[bl["Bet Type"]=="VALUE — AGAINST PICK"]; vw,vl=(v["Model Bet Result"]=="WIN").sum(),(v["Model Bet Result"]=="LOSS").sum()
print(f"D5 model pick won: {y}/{y+n} = {y/(y+n):.4f}; D7 favorite: {fy}/{fy+fn} = {fy/(fy+fn):.4f}; D6 value picks: {vw}/{vw+vl} = {vw/(vw+vl):.4f}; D8 value avg {bl['Model Bet Value @ Close'].dropna().astype(float).mean():+.4f} over {bl['Model Bet Value @ Close'].dropna().shape[0]}")
