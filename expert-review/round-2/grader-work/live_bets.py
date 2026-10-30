import sys
sys.path.insert(0, 'src')
import numpy as np, pandas as pd
from nflmodel.data import load_games
from nflmodel.market import devig, points_to_prob_table
from nflmodel.trends import margin_model_for_history
from nflmodel.scorecard import model_bets, value_at_price, _close_fair_home
from nflmodel.closing import load_closing, close_for, ticket, bet_clv, card_clv, _fair_move

g = load_games(); mm = margin_model_for_history()
b = model_bets(2026, range(1, 8), g, mm)
print('bets on final cards:', len(b), b.groupby('week').size().to_dict())
pay = lambda o: o/100 if o > 0 else 100/abs(o)
be = lambda o: -o/(-o+100) if o < 0 else 100/(o+100)

# independent recheck of value at the price taken
chk = []
for wk in range(1, 8):
    L = pd.read_csv(f'picks/2026/week{wk:02d}_leans.csv'); C = pd.read_csv(f'picks/2026/week{wk:02d}_closing.csv')
    for _, l in L.iterrows():
        side = l.bet_side; team = side.split()[0]; bet_home = team == l.home_team
        cr = C[(C.home_team == l.home_team) & (C.away_team == l.away_team)].iloc[0]
        if l.bet_market == 'MONEYLINE':
            fh = devig(cr.close_home_ml, cr.close_away_ml)[0]; p = fh if bet_home else 1 - fh
            ev = p * pay(l.bet_odds) - (1 - p)
            close_num = cr.close_home_ml if bet_home else cr.close_away_ml
            clv_final = (devig(cr.close_home_ml, cr.close_away_ml)[0] - devig(l.home_ml, l.away_ml)[0]) * (1 if bet_home else -1)
            pub_fair = devig(l.home_ml, l.away_ml)[0]; pub_fair = pub_fair if bet_home else 1 - pub_fair
        else:
            ev, _ = value_at_price(mm, 'SPREAD', bet_home, ticket(side), float(l.bet_odds), cr)
            close_num = -cr.close_spread if bet_home else cr.close_spread
            clv_final = ticket(side) - close_num
            pub_fair = np.nan
        chk.append(dict(week=wk, bet=side, market=l.bet_market, odds=l.bet_odds, ev_mine=ev, close=close_num,
                        clv_final=clv_final, pub_fair=pub_fair, src=cr.close_source))
c = pd.DataFrame(chk)
b = b.reset_index(drop=True).join(c[['ev_mine', 'close', 'clv_final', 'pub_fair']])
print('max |value repo - mine|:', float((b.value_at_close - b.ev_mine).abs().max()))

def band(x):
    x = np.asarray(x, float); x = x[~np.isnan(x)]
    return x.mean(), x.std(ddof=1), x.std(ddof=1)/np.sqrt(len(x)), len(x)

dec = b[b.out != 'P']
print(f"\nrecord {(b.out=='W').sum()}-{(b.out=='L').sum()}-{(b.out=='P').sum()}, units {b.units.sum():+.2f}, ROI {b.units.mean():+.3f} (SE {b.units.std(ddof=1)/np.sqrt(len(b)):.3f}); "
      f"win% {(dec.out=='W').mean():.3f} vs break-even {dec.odds.map(be).mean():.3f}")
pm = dec.p_model.to_numpy(); pc = dec.p_close.to_numpy()
print(f"expected wins: model {pm.sum():.1f} +/- {np.sqrt((pm*(1-pm)).sum()):.1f}; closing market {np.nansum(pc):.1f} +/- {np.sqrt(np.nansum(pc*(1-pc))):.1f}; actual {(dec.out=='W').sum()} (decided {len(dec)})")
m, sd, se, n = band(b.value_at_close)
print(f"value at the price taken: mean {m:+.4f} SD {sd:.3f} SE {se:.4f} t {m/se:+.2f} n {n}")
i = b.value_at_close.idxmax(); bb = b.drop(i)
m2, sd2, se2, n2 = band(bb.value_at_close)
print(f"   without largest ({b.loc[i,'bet']} wk{b.loc[i,'week']} {b.loc[i,'value_at_close']:+.3f}): mean {m2:+.4f} SE {se2:.4f} t {m2/se2:+.2f} n {n2}")
for mk in ('SPREAD', 'MONEYLINE'):
    x = b[b.market == mk]; mm_, sd_, se_, n_ = band(x.value_at_close)
    print(f"   {mk}: n {n_} value {mm_:+.4f} (SE {se_:.4f}, t {mm_/se_:+.2f}); record {(x.out=='W').sum()}-{(x.out=='L').sum()}-{(x.out=='P').sum()} ROI {x.units.mean():+.3f}")
# weeks 4+ only ($5 flat era)
x = b[b.week >= 4]; mm_, sd_, se_, n_ = band(x.value_at_close)
print(f"   weeks 4-7: n {n_} value {mm_:+.4f} (t {mm_/se_:+.2f}); weeks 5-7: ", end='')
x = b[b.week >= 5]; mm_, sd_, se_, n_ = band(x.value_at_close); print(f"n {n_} value {mm_:+.4f} (t {mm_/se_:+.2f})")
# slices
b['fav'] = np.where(b.market == 'MONEYLINE', b.odds < 0, b.bet.str.split().str[1].astype(float) < 0)
b['odds_bucket'] = pd.cut(b.odds, [-1000, -200, -130, -100.5, 150, 1000], labels=['<=-200', '-199..-130', '-129..-101', '-100..+150', '>+150'])
print('\nslices (n, record, ROI, mean value, mean model p, mean close p):')
for col in ('market', 'fav', 'odds_bucket'):
    for k_, x in b.groupby(col, observed=True):
        print(f'   {col}={k_}: n {len(x)} {(x.out=="W").sum()}-{(x.out=="L").sum()}-{(x.out=="P").sum()} ROI {x.units.mean():+.3f} value {x.value_at_close.mean():+.3f} p_model {x.p_model.mean():.3f} p_close {x.p_close.mean():.3f}')
b.to_csv('../work/live_bets.csv', index=False)

# CLV: first-published (repo) and final card (mine)
pts = points_to_prob_table(mm)
frames = [card_clv(2026, w, pts_table=pts) for w in range(1, 8)]
cf = pd.concat(frames, ignore_index=True)
print('\nCLV from first-published card (repo card_clv): n', len(cf))
for mk, col in (('SPREAD', 'clv_pts'), ('MONEYLINE', 'clv_prob')):
    x = cf[cf.market == mk][col].astype(float); print(f'   {mk}: n {len(x)} mean {x.mean():+.4f} SD {x.std(ddof=1):.4f} t {x.mean()/(x.std(ddof=1)/np.sqrt(len(x))):+.2f}')
    if mk == 'SPREAD':
        xp = cf[cf.market == mk].clv_prob.astype(float); print(f'      as prob via key-number table: mean {xp.mean():+.4f} t {xp.mean()/(xp.std(ddof=1)/np.sqrt(len(xp))):+.2f}')
print('CLV from the final card (mine):')
for mk in ('SPREAD', 'MONEYLINE'):
    x = b[b.market == mk].clv_final.astype(float)
    print(f'   {mk}: n {len(x)} mean {x.mean():+.4f} SD {x.std(ddof=1):.4f} t {x.mean()/(x.std(ddof=1)/np.sqrt(len(x))):+.2f}')
print(cf[['week', 'bet_side', 'market', 'taken', 'close', 'clv_pts', 'clv_prob', 'card_source']].to_string())
