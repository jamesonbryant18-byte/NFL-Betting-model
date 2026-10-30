"""5b/5c/6c: the model's live card (Weeks 1-7) and his tracker: luck vs skill, CLV."""
import sys
sys.path.insert(0, 'src'); sys.path.insert(0, '../work')
import numpy as np, pandas as pd
from scipy.optimize import brentq
from nflmodel.data import load_games
from nflmodel.trends import margin_model_for_history
from nflmodel.closing import card_clv, summarize_clv
from nflmodel.market import points_to_prob_table
from metrics import imp, payout

mm = margin_model_for_history()
PTS = points_to_prob_table(mm)
g = load_games(); g = g[(g.season == 2026) & g.played].set_index(['week', 'home_team', 'away_team'])


def devig2(a, b):
    pa, pb = imp(a), imp(b)
    return float(pa / (pa + pb))


def mkt_mean(close_home_line, p_home_fair):
    """Margin-distribution mean at which the home side's no-push cover share equals the fair price."""
    f = lambda M: (lambda c: c[0] / (c[0] + c[2]))(mm.cover_prob(M, close_home_line)) - p_home_fair
    return brentq(f, -40, 40)


def spread_probs(M, home_line, bet_home):
    ph, pp, pa = mm.cover_prob(M, home_line)
    return (ph, pp, pa) if bet_home else (pa, pp, ph)


def grade(team_margin, market, ticket):
    if market == 'SPREAD':
        c = team_margin + ticket
    else:
        c = team_margin
    return 'W' if c > 0 else ('P' if c == 0 else 'L')


def close_ev(market, home, away, bet_home, ticket, odds, cl):
    """Expected profit per unit at the FanDuel close (de-vigged; spreads key-number aware)."""
    if market == 'MONEYLINE':
        if pd.isna(cl.close_home_ml) or pd.isna(cl.close_away_ml):
            return np.nan, np.nan
        ph = devig2(cl.close_home_ml, cl.close_away_ml)
        p = ph if bet_home else 1 - ph
        return p * payout(odds) - (1 - p), p
    if pd.isna(cl.close_spread):
        return np.nan, np.nan
    ho, ao = cl.close_home_spread_odds, cl.close_away_spread_odds
    ph_fair = devig2(ho, ao) if pd.notna(ho) and pd.notna(ao) else 0.5
    M = mkt_mean(cl.close_spread, ph_fair)
    home_line = -ticket if bet_home else ticket      # ticket is from bettor's side; convert to home-favoured-by
    pw, pp, pl = spread_probs(M, home_line, bet_home)
    return pw * payout(odds) - pl, pw / (pw + pl)


rows = []
for w in range(1, 8):
    final = pd.read_csv(f'picks/2026/week{w:02d}_leans.csv')
    try:
        first = pd.read_csv(f'picks/2026/week{w:02d}_first_leans.csv')
    except FileNotFoundError:
        first = None
    cl = pd.read_csv(f'picks/2026/week{w:02d}_closing.csv')
    slate = pd.read_csv(f'output/slate_2026_wk{w:02d}.csv')
    for _, l in final.iterrows():
        side = str(l.bet_side)
        if not side or side == 'nan':
            continue
        team, num = side.split()[0], side.split()[1]
        market = l.bet_market; bet_home = team == l.home_team
        ticket = 0.0 if num in ('PK',) else float(num)
        odds = float(l.bet_odds)
        res = g.loc[(w, l.home_team, l.away_team)].result
        tm = res if bet_home else -res
        out = grade(tm, market, ticket)
        c = cl[(cl.home_team == l.home_team) & (cl.away_team == l.away_team)].iloc[0]
        hwp = float(l.home_win_prob)
        # model probability the bet wins (spread: recomputed cover share from archived margin/line)
        if market == 'MONEYLINE':
            p_model = hwp if bet_home else 1 - hwp
            p_mkt_pub = (devig2(l.home_ml, l.away_ml) if bet_home else 1 - devig2(l.home_ml, l.away_ml))
        else:
            ph, pp, pa = mm.cover_prob(float(l.projected_margin), float(l.spread_line))
            pw, pl = (ph, pa) if bet_home else (pa, ph)
            p_model = pw / (pw + pl)
            s = slate[(slate.home_team == l.home_team) & (slate.away_team == l.away_team)]
            if len(s) and pd.notna(s.home_spread_odds.iloc[0]) and pd.notna(s.away_spread_odds.iloc[0]):
                pf = devig2(s.home_spread_odds.iloc[0], s.away_spread_odds.iloc[0])
                p_mkt_pub = pf if bet_home else 1 - pf
            else:
                p_mkt_pub = np.nan
        ev_close, p_close = close_ev(market, l.home_team, l.away_team, bet_home, ticket, odds, c)
        # first-published number for this game+market+team
        fp_ticket, fp_odds = ticket, odds
        if first is not None:
            f = first[(first.home_team == l.home_team) & (first.away_team == l.away_team) & (first.bet_market == market)
                      & (first.bet_side.astype(str).str.split().str[0] == team)]
            if len(f):
                fp_ticket = 0.0 if f.bet_side.iloc[0].split()[1] == 'PK' else float(f.bet_side.iloc[0].split()[1])
                fp_odds = float(f.bet_odds.iloc[0])
        ev_close_first, _ = close_ev(market, l.home_team, l.away_team, bet_home, fp_ticket, fp_odds, c)
        rows.append(dict(week=w, game=f'{l.away_team} @ {l.home_team}', bet=side, market=market, odds=odds,
                         fav=(odds < 0) if market == 'MONEYLINE' else (ticket < 0), result=out,
                         profit=(payout(odds) if out == 'W' else (0.0 if out == 'P' else -1.0)),
                         p_model=p_model, p_mkt_pub=p_mkt_pub, p_close=p_close,
                         be=imp(odds), ev_close=ev_close, ev_close_first=ev_close_first,
                         first_changed=(fp_ticket != ticket or fp_odds != odds),
                         edge=(abs(l.spread_edge_pts) if market == 'SPREAD' else 100 * max(l.ml_edge_home if bet_home else l.ml_edge_away, 0)),
                         card=str(l.get('card', '')) if 'card' in l else ''))
B = pd.DataFrame(rows)
B.to_csv('../work/model_card_live.csv', index=False)
pd.set_option('display.width', 250)
print(B[['week', 'bet', 'market', 'odds', 'result', 'profit', 'p_model', 'p_mkt_pub', 'p_close', 'ev_close', 'ev_close_first', 'first_changed']].round(3).to_string(index=False))
dec = B[B.result != 'P']
n = len(B); w_ = (B.result == 'W').sum(); l_ = (B.result == 'L').sum()
print(f'\nMODEL CARD wk1-7: {n} bets, {w_}-{l_}-{(B.result=="P").sum()}, units {B.profit.sum():+.2f}, ROI/bet {B.profit.mean():+.3f}')
for lab, col in (('model p', 'p_model'), ('market p @publication', 'p_mkt_pub'), ('market p @close', 'p_close')):
    x = dec.dropna(subset=[col])
    print(f'  expected wins under {lab:<22}: {x[col].sum():.1f} +/- {np.sqrt((x[col]*(1-x[col])).sum()):.1f} (n={len(x)}; actual {int((x.result=="W").sum())})')
print(f'  break-even win rate of prices taken (decided bets): {dec.be.mean():.3f}; actual {(dec.result=="W").mean():.3f}')
sd = B.profit.std(ddof=1); print(f'  ROI {B.profit.mean():+.3f} per unit, SE {sd/np.sqrt(n):.3f}')
for lab, mask in (('spread', B.market == 'SPREAD'), ('moneyline', B.market == 'MONEYLINE'), ('favorite side', B.fav), ('underdog side', ~B.fav)):
    x = B[mask]; print(f'   {lab:<14} n={len(x):>2} {int((x.result=="W").sum())}-{int((x.result=="L").sum())} ROI {x.profit.mean():+.3f}')
B['eb'] = np.where(B.market == 'SPREAD', pd.cut(B.edge, [0, 2, 3, 99]).astype(str), pd.cut(B.edge, [0, 5, 8, 99]).astype(str))
print(B.groupby(['market', 'eb']).agg(n=('profit', 'size'), won=('result', lambda s: (s == 'W').sum()), roi=('profit', 'mean')).round(3).to_string())
for lab, col in (('closing EV, final card number', 'ev_close'), ('closing EV, first-published number', 'ev_close_first')):
    x = B[col].dropna(); t = x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))
    print(f'  {lab:<36} n={len(x)} mean {x.mean():+.4f} sd {x.std(ddof=1):.4f} t {t:+.2f}')
    for lab2, m in (('spreads', B.market == 'SPREAD'), ('moneylines', B.market == 'MONEYLINE')):
        y = B.loc[m, col].dropna(); print(f'      {lab2:<10} n={len(y)} mean {y.mean():+.4f} t {y.mean()/(y.std(ddof=1)/np.sqrt(len(y))):+.2f}')
    xx = B.assign(v=B[col]).dropna(subset=['v'])
    drop = xx.v.abs().idxmax()
    y = xx.drop(index=drop).v
    print(f'      without largest move ({xx.loc[drop, "bet"]}, wk{xx.loc[drop, "week"]}, {xx.loc[drop, "v"]:+.3f}): mean {y.mean():+.4f} t {y.mean()/(y.std(ddof=1)/np.sqrt(len(y))):+.2f}')

print('\nREPO CLV (closing.card_clv: first-published wk5-7, final card wk1-4):')
cc = pd.concat([card_clv(2026, w, pts_table=PTS) for w in range(1, 8)], ignore_index=True)
print(summarize_clv(cc))
for m, col in (('SPREAD', 'clv_pts'), ('SPREAD', 'clv_prob'), ('MONEYLINE', 'clv_prob')):
    v = cc[(cc.market == m)][col].dropna().astype(float)
    print(f'  {m} {col}: n={len(v)} mean {v.mean():+.4f} sd {v.std(ddof=1):.4f} t {v.mean()/(v.std(ddof=1)/np.sqrt(len(v))):+.2f}')
