"""5c: movement CLV, de-vigged for moneylines, key-number aware for spreads (repo table), model card + his bets."""
import sys
sys.path.insert(0, 'src'); sys.path.insert(0, '../work')
import numpy as np, pandas as pd
from nflmodel.trends import margin_model_for_history
from nflmodel.market import points_to_prob_table
from nflmodel.betlog import _per_point
from nflmodel.data import load_games
from metrics import imp, payout

mm = margin_model_for_history(); PTS = points_to_prob_table(mm)

def devig2(a, b):
    pa, pb = imp(a), imp(b); return float(pa / (pa + pb))

def tstat(v):
    v = pd.Series(v, dtype=float).dropna(); return len(v), v.mean(), v.std(ddof=1), v.mean() / (v.std(ddof=1) / np.sqrt(len(v)))

rows = []
for w in range(1, 8):
    cl = pd.read_csv(f'picks/2026/week{w:02d}_closing.csv')
    try:
        src = pd.read_csv(f'picks/2026/week{w:02d}_first_leans.csv'); lab = 'first'
    except FileNotFoundError:
        src = pd.read_csv(f'picks/2026/week{w:02d}_leans.csv'); lab = 'final(backfilled)'
    fin = pd.read_csv(f'picks/2026/week{w:02d}_leans.csv')
    for which, df in (('published', src), ('final', fin)):
        for _, l in df.iterrows():
            s = str(l.bet_side)
            if s == 'nan' or not s:
                continue
            team, num = s.split()[0], s.split()[1]; home = team == l.home_team
            c = cl[(cl.home_team == l.home_team) & (cl.away_team == l.away_team)].iloc[0]
            if l.bet_market == 'SPREAD':
                taken = 0.0 if num == 'PK' else float(num)
                close = -c.close_spread if home else c.close_spread
                pts = taken - close
                clv = pts * _per_point(taken, PTS)
                # juice part: de-vigged price at the close vs price taken, same number only
                rows.append(dict(week=w, which=which, src=lab if which == 'published' else 'final', bet=s, market='SPREAD',
                                 clv_pts=pts, clv_prob=clv))
            else:
                p_pub = devig2(l.home_ml, l.away_ml); p_pub = p_pub if home else 1 - p_pub
                p_cl = devig2(c.close_home_ml, c.close_away_ml); p_cl = p_cl if home else 1 - p_cl
                rows.append(dict(week=w, which=which, src=lab if which == 'published' else 'final', bet=s, market='MONEYLINE',
                                 clv_pts=np.nan, clv_prob=p_cl - p_pub))
C = pd.DataFrame(rows)
for which in ('published', 'final'):
    x = C[C.which == which]
    print(f'MODEL CARD, CLV from the {which} number (wk1-4 published = final card, backfilled):')
    for m in ('SPREAD', 'MONEYLINE', None):
        y = x if m is None else x[x.market == m]
        n, mu, sd, t = tstat(y.clv_prob)
        print(f'   {m or "ALL":<10} n={n} mean {100*mu:+.2f}% sd {100*sd:.2f}% t {t:+.2f}' + (f'   (points: mean {y.clv_pts.mean():+.2f})' if m == 'SPREAD' else ''))
    big = x.clv_prob.abs().idxmax()
    n, mu, sd, t = tstat(x.drop(index=big).clv_prob)
    print(f'   without largest move ({x.loc[big, "bet"]} wk{x.loc[big, "week"]} {100*x.loc[big, "clv_prob"]:+.1f}%): n={n} mean {100*mu:+.2f}% t {t:+.2f}')
    news = x[x.bet.isin(['CIN +2.5', 'PHI -1.5', 'PHI +3.5'])]
    n, mu, sd, t = tstat(x.drop(index=news.index).clv_prob)
    print(f'   without QB-news moves ({", ".join(news.bet)}): n={n} mean {100*mu:+.2f}% t {t:+.2f}')

# his bets: line/odds he typed vs FanDuel close (game-day number)
import openpyxl
ws = openpyxl.load_workbook('../wb/wk07.xlsx', read_only=True)['Bet Tracker']
alias = {'JAC': 'JAX', 'NY': 'NYG', 'LAR': 'LA', 'WSH': 'WAS'}
g = load_games(); g = g[(g.season == 2026)]
hr = []
for r in ws.iter_rows(min_row=12, max_row=60, values_only=True):
    if r[0] is None:
        continue
    wk, mt, mkt, side, line, odds, stake, res = r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8]
    a, h = [alias.get(t.strip(), t.strip()) for t in mt.split('@')]
    gg = g[(g.week == wk) & (g.home_team == h) & (g.away_team == a)]
    if gg.empty:
        print('no match', wk, mt); continue
    cl = pd.read_csv(f'picks/2026/week{int(wk):02d}_closing.csv')
    c = cl[(cl.home_team == h) & (cl.away_team == a)].iloc[0]
    home = side.strip().upper() == 'HOME'
    if mkt == 'SPREAD':
        close = -c.close_spread if home else c.close_spread
        pts = float(line) - close
        clv = pts * _per_point(float(line), PTS)
        # EV at the fair close for the number+price he took
    else:
        p_cl = devig2(c.close_home_ml, c.close_away_ml); p_cl = p_cl if home else 1 - p_cl
        clv = p_cl - imp(odds)          # vs his raw price (the game-day price he got)
        pts = np.nan
    team_margin = gg.result.iloc[0] * (1 if home else -1)
    hr.append(dict(week=wk, matchup=mt.strip(), market=mkt, side=('HOME ' if home else 'AWAY ') + (h if home else a), line=line, odds=odds,
                   result=res, profit=(stake * payout(odds) if res == 'W' else -stake if res == 'L' else 0), clv_pts=pts, clv_prob=clv,
                   be=float(imp(odds))))
Hh = pd.DataFrame(hr)
Hh.to_csv('../work/his_bets.csv', index=False)
print(f'\nHIS TRACKER: {len(Hh)} bets, {int((Hh.result=="W").sum())}-{int((Hh.result=="L").sum())}, P&L ${Hh.profit.sum():+.2f} on ${5*len(Hh)} ({Hh.profit.sum()/(5*len(Hh)):+.1%}); mean break-even of his prices {Hh.be.mean():.3f}')
for m in ('SPREAD', 'MONEYLINE'):
    y = Hh[Hh.market == m]; n, mu, sd, t = tstat(y.clv_prob)
    print(f'   {m:<10} n={n} CLV mean {100*mu:+.2f}% (t {t:+.2f})' + (f'  points {y.clv_pts.mean():+.2f}' if m == 'SPREAD' else '  (moneyline: fair close minus implied prob of his price)'))
print(Hh[['week', 'matchup', 'market', 'side', 'line', 'odds', 'result', 'clv_pts', 'clv_prob', 'be']].round(3).to_string(index=False))
