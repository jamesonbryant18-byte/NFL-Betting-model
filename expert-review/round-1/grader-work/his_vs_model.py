"""6c: his tracker vs the model card, with prices (closing EV at the FanDuel fair close) and results."""
import sys
sys.path.insert(0, 'src'); sys.path.insert(0, '../work')
import numpy as np, pandas as pd
from scipy.optimize import brentq
from nflmodel.trends import margin_model_for_history
from metrics import imp, payout

mm = margin_model_for_history()


def devig2(a, b):
    pa, pb = imp(a), imp(b); return float(pa / (pa + pb))


def mkt_mean(close_home_line, p_home_fair):
    f = lambda M: (lambda c: c[0] / (c[0] + c[2]))(mm.cover_prob(M, close_home_line)) - p_home_fair
    return brentq(f, -40, 40)


def close_ev(market, bet_home, ticket, odds, cl):
    if market == 'MONEYLINE':
        ph = devig2(cl.close_home_ml, cl.close_away_ml); p = ph if bet_home else 1 - ph
        return p * payout(odds) - (1 - p)
    ho, ao = cl.close_home_spread_odds, cl.close_away_spread_odds
    ph_fair = devig2(ho, ao) if pd.notna(ho) and pd.notna(ao) else 0.5
    M = mkt_mean(cl.close_spread, ph_fair)
    home_line = -ticket if bet_home else ticket
    ph, pp, pa = mm.cover_prob(M, home_line)
    pw, pl = (ph, pa) if bet_home else (pa, ph)
    return pw * payout(odds) - pl


alias = {'JAC': 'JAX', 'NY': 'NYG', 'LAR': 'LA', 'WSH': 'WAS'}
H = pd.read_csv('../work/his_bets.csv')
M = pd.read_csv('../work/model_card_live.csv')
M['away'] = M.game.str.split(' @ ').str[0]; M['home'] = M.game.str.split(' @ ').str[1]
M['team'] = M.bet.str.split().str[0]
typo = {(5, 'MIN @ NO'): -1.5, (6, 'HOU @ JAX'): -2.5}      # documented in CLAUDE.md 2026-10-19 (favorite typed as +)
rows = []
for _, b in H.iterrows():
    a, h = [alias.get(t.strip(), t.strip()) for t in b.matchup.split('@')]
    team = b.side.split()[1]; bet_home = team == h
    cl = pd.read_csv(f'picks/2026/week{int(b.week):02d}_closing.csv')
    c = cl[(cl.home_team == h) & (cl.away_team == a)].iloc[0]
    line = typo.get((int(b.week), b.matchup), b.line)
    ev = close_ev(b.market, bet_home, float(line) if b.market == 'SPREAD' else 0.0, float(b.odds), c)
    m = M[(M.week == b.week) & (M.home == h) & (M.away == a) & (M.market == b.market) & (M.team == team)]
    mo = M[(M.week == b.week) & (M.home == h) & (M.away == a)]
    status = 'same bet' if len(m) else ('same game, other market/side' if len(mo) else 'off-card')
    rows.append(dict(week=int(b.week), game=f'{a} @ {h}', market=b.market, his=f'{team} {line if b.market=="SPREAD" else ""} {int(b.odds):+d}'.replace('  ', ' '),
                     model=(m.bet.iloc[0] + f' {int(m.odds.iloc[0]):+d}') if len(m) else (mo.bet.iloc[0] if len(mo) else ''),
                     status=status, his_ev=ev, model_ev=(m.ev_close.iloc[0] if len(m) else np.nan),
                     his_res=b.result, his_units=(payout(b.odds) if b.result == 'W' else (-1.0 if b.result == 'L' else 0.0)),
                     model_units=(m.profit.iloc[0] if len(m) else np.nan)))
R = pd.DataFrame(rows)
pd.set_option('display.width', 250)
print(R.round(3).to_string(index=False))
same = R[R.status == 'same bet']
print(f'\nHIS 28 BETS: closing EV mean {R.his_ev.mean():+.4f}/unit (t {R.his_ev.mean()/(R.his_ev.std(ddof=1)/np.sqrt(len(R))):+.2f}); realized {R.his_units.sum():+.2f} units')
print(f'  same bet as the model card: n={len(same)}; his closing EV {same.his_ev.mean():+.4f} vs model number {same.model_ev.mean():+.4f} '
      f'(his - model {(same.his_ev-same.model_ev).mean():+.4f}); units his {same.his_units.sum():+.2f} vs model {same.model_units.sum():+.2f}')
for s in ('same game, other market/side', 'off-card'):
    x = R[R.status == s]
    if len(x):
        print(f'  {s}: n={len(x)} closing EV {x.his_ev.mean():+.4f}; units {x.his_units.sum():+.2f}; {x.game.tolist()}')
# model bets he did not log (weeks 3-7)
keys = set((r.week, r.game.split(' @ ')[1], r.market, (r.his.split()[0])) for r in R.itertuples())
sk = M[(M.week >= 3) & ~M.apply(lambda r: (r.week, r.home, r.market, r.team) in keys, axis=1)]
print(f'  model card bets wk3-7 not in his tracker: n={len(sk)}, closing EV {sk.ev_close.mean():+.4f}, units {sk.profit.sum():+.2f}')
print(sk[['week', 'bet', 'market', 'odds', 'result', 'profit', 'ev_close']].round(3).to_string(index=False))
