"""6a/6b: replay the deployed bet-selection rules on the 2021-25 hold-out at closing prices (nflverse close + real juice).

Mirrors model._recommend (1.5-pt spread edge, 3% ML edge vs multiplicative de-vig, -350/+250 caps, half-Kelly
qualification on $1,000 with min $5, spread preferred) and model._weekly_card (top 7 by bet_chance, top-up to 4 with
positive-EV near misses). Settles at the same closing number and juice.
usage: replay66.py [primary|live]   primary = facA (2013-20 factor weights) + b_disc; live = live weights + b_live (in-sample)
"""
import sys, json
sys.path.insert(0, 'src'); sys.path.insert(0, '../work')
import numpy as np, pandas as pd
from nflmodel.trends import margin_model_for_history, win_probs, calibrate
from nflmodel.market import devig, kelly_stake
from nflmodel.config import STAKING, THRESHOLDS as T

VARIANT = sys.argv[1] if len(sys.argv) > 1 else 'primary'
mm = margin_model_for_history()
tj = json.load(open('data/trends.json'))
b_disc, b_live = tj['calibration']['disc_fit']['b'], tj['calibration']['b']
d = pd.read_parquet('../work/holdout.parquet')
H = d[d.season.between(2021, 2025)].copy().reset_index(drop=True)
if VARIANT == 'primary':
    H['P'] = H.projA; H['WP'] = H.wpA
elif VARIANT == 'live':
    H['P'] = H.base + H.st + H.trend + H.fac_live
    H['WP'] = calibrate(win_probs(H.P, mm), dict(a=0.0, b=b_live))
elif VARIANT == 'facB':
    H['P'] = H.base + H.st + H.trend + H.fac
    H['WP'] = calibrate(win_probs(H.P, mm), dict(a=0.0, b=b_disc))
elif VARIANT == 'basetrend':
    H['P'] = H.base + H.trend
    H['WP'] = calibrate(win_probs(H.P, mm), dict(a=0.0, b=b_disc))
print('variant', VARIANT, 'games', len(H))


def pay(o):
    return o / 100 if o > 0 else 100 / abs(o)


rows = []
for _, g in H.iterrows():
    P, line, hwp = float(g.P), float(g.spread_line), float(g.WP)
    ph, pp, pa = mm.cover_prob(P, line)
    edge = P - line
    fh, fa = devig(g.home_moneyline, g.away_moneyline, 'multiplicative')
    eh, ea = hwp - fh, (1 - hwp) - fa
    base = dict(season=g.season, week=g.week, game_id=g.game_id, result=g.result, line=line, P=P, edge=edge,
                ph=ph, pp=pp, pa=pa, hwp=hwp, fh=fh, eh=eh, ea=ea)
    cands = []
    if abs(edge) >= T.spread_min_edge_pts:
        sh = edge > 0
        odds = float(g.home_spread_odds if sh else g.away_spread_odds)
        st, _ = kelly_stake(ph if sh else pa, odds, STAKING.bankroll, STAKING, push_prob=pp)
        if st > 0:
            pw = ph if sh else pa
            cands.append(dict(market='SPREAD', home=sh, odds=odds, edge_disp=abs(edge), pri=2, chance=pw / (1 - pp)))
    for is_home, e, ml, p in ((True, eh, g.home_moneyline, hwp), (False, ea, g.away_moneyline, 1 - hwp)):
        if e < T.ml_min_edge or ml < T.ml_max_favorite or ml > T.ml_max_underdog:
            continue
        st, _ = kelly_stake(p, float(ml), STAKING.bankroll, STAKING)
        if st > 0:
            cands.append(dict(market='MONEYLINE', home=is_home, odds=float(ml), edge_disp=100 * e, pri=1, chance=p))
    best = sorted(cands, key=lambda c: (-c['pri'], -c['edge_disp']))[0] if cands else None
    # near miss (model._near_miss)
    nm = None
    found = []
    if edge != 0:
        sh = edge > 0
        pw, pl = (ph, pa) if sh else (pa, ph)
        odds = float(g.home_spread_odds if sh else g.away_spread_odds)
        if pw * pay(odds) - pl > 0:
            found.append(dict(market='SPREAD', home=sh, odds=odds, chance=pw / (pw + pl)))
    for is_home, ml, e in ((True, g.home_moneyline, eh), (False, g.away_moneyline, ea)):
        if e <= 0 or ml < T.ml_max_favorite or ml > T.ml_max_underdog:
            continue
        p = hwp if is_home else 1 - hwp
        if p * pay(ml) - (1 - p) > 0:
            found.append(dict(market='MONEYLINE', home=is_home, odds=float(ml), chance=p))
    if found:
        nm = max(found, key=lambda c: c['chance'])
    rows.append(dict(base, best=best, nm=nm))
R = pd.DataFrame(rows)


def settle(r, b):
    tm = r.result if b['home'] else -r.result
    c = tm + (-r.line if b['home'] else r.line) if b['market'] == 'SPREAD' else tm
    return (pay(b['odds']) if c > 0 else (0.0 if c == 0 else -1.0)), ('W' if c > 0 else ('P' if c == 0 else 'L'))


bets_all, bets_card = [], []
for (s, w), wk in R.groupby(['season', 'week'], sort=True):
    q = wk[wk.best.notna()]
    for _, r in q.iterrows():
        u, o = settle(r, r.best)
        bets_all.append(dict(season=s, week=w, market=r.best['market'], odds=r.best['odds'], chance=r.best['chance'],
                             edge=r.best['edge_disp'], units=u, out=o, kind='qualifying', home=r.best['home'],
                             base_edge=r.edge))
    keep = q.assign(ch=[b['chance'] for b in q.best]).sort_values('ch', ascending=False).head(STAKING.card_max)
    for _, r in keep.iterrows():
        u, o = settle(r, r.best)
        bets_card.append(dict(season=s, week=w, market=r.best['market'], odds=r.best['odds'], chance=r.best['chance'],
                              edge=r.best['edge_disp'], units=u, out=o, kind='card'))
    need = STAKING.card_min - len(keep)
    if need > 0:
        pool = wk[wk.best.isna() & wk.nm.notna()]
        pool = pool.assign(ch=[b['chance'] for b in pool.nm]).sort_values('ch', ascending=False).head(need)
        for _, r in pool.iterrows():
            u, o = settle(r, r.nm)
            bets_card.append(dict(season=s, week=w, market=r.nm['market'], odds=r.nm['odds'], chance=r.nm['chance'],
                                  edge=np.nan, units=u, out=o, kind='filler'))
A, C = pd.DataFrame(bets_all), pd.DataFrame(bets_card)


def summ(x, lab):
    n = len(x); dec = x[x.out != 'P']
    roi = x.units.mean(); se = x.units.std(ddof=1) / np.sqrt(n)
    be = np.mean([(-o / (-o + 100)) if o < 0 else (100 / (o + 100)) for o in dec.odds])
    print(f'  {lab:<34} n={n:>4}  W-L-P {int((x.out=="W").sum())}-{int((x.out=="L").sum())}-{int((x.out=="P").sum())}  '
          f'win% {100*(dec.out=="W").mean():5.1f} (break-even {100*be:4.1f})  ROI {100*roi:+6.2f}%  SE {100*se:4.2f}  '
          f'95% CI [{100*(roi-1.96*se):+.1f}, {100*(roi+1.96*se):+.1f}]  model-expected win% {100*x.chance.mean():.1f}')


print('\n=== 6a DEPLOYED CARD (top 7 by chance, min 4 with filler), 2021-25 at closing prices ===')
summ(C, 'card, all')
for m in ('SPREAD', 'MONEYLINE'):
    summ(C[C.market == m], f'card, {m.lower()}')
summ(C[C.kind == 'filler'], 'card, filler only')
for s in range(2021, 2026):
    summ(C[C.season == s], f'card, {s}')
summ(C[C.week <= 18], 'card, regular season')
summ(C[C.week > 18], 'card, playoffs')
print('  bets per week: ', C.groupby(['season', 'week']).size().value_counts().sort_index().to_dict())
print('\n=== all qualifying bets (no card cap) ===')
summ(A, 'all qualifying')
for m in ('SPREAD', 'MONEYLINE'):
    summ(A[A.market == m], f'all qualifying, {m.lower()}')

print('\n=== 6b edge buckets (all qualifying bets, at closing prices) ===')
for m, bins in (('SPREAD', [1.5, 2, 2.5, 3, 4, 99]), ('MONEYLINE', [3, 5, 8, 12, 99])):
    x = A[A.market == m].copy(); x['b'] = pd.cut(x.edge, bins, right=False)
    for b, y in x.groupby('b', observed=True):
        summ(y, f'{m.lower()} edge {b}')
print('\n=== ATS of the model side on EVERY hold-out game, by |model - line| (closing juice) ===')
R['side_home'] = R.edge > 0
R['odds'] = np.where(R.side_home, H.home_spread_odds, H.away_spread_odds)
ats = []
for _, r in R[R.edge != 0].iterrows():
    u, o = settle(r, dict(market='SPREAD', home=r.side_home, odds=r.odds))
    ats.append(dict(ae=abs(r.edge), units=u, out=o, odds=r.odds, chance=(r.ph if r.side_home else r.pa) / (1 - r.pp)))
X = pd.DataFrame(ats); X['b'] = pd.cut(X.ae, [0, 0.5, 1, 1.5, 2, 3, 99], right=False)
for b, y in X.groupby('b', observed=True):
    summ(y, f'ATS |edge| {b}')
print('  correlation of |edge| with ATS units:', round(np.corrcoef(X.ae, X.units)[0, 1], 4), ' n', len(X))
print('\n=== ML side on every game with the model > market (de-vigged), by edge ===')
ml = []
for _, r in R.iterrows():
    for is_home, e in ((True, r.eh), (False, r.ea)):
        if e > 0:
            o = H.loc[_, 'home_moneyline'] if is_home else H.loc[_, 'away_moneyline']
            u, out = settle(r, dict(market='MONEYLINE', home=is_home, odds=float(o)))
            ml.append(dict(e=100 * e, units=u, out=out, odds=float(o), chance=r.hwp if is_home else 1 - r.hwp))
M = pd.DataFrame(ml); M['b'] = pd.cut(M.e, [0, 3, 5, 8, 12, 99], right=False)
for b, y in M.groupby('b', observed=True):
    summ(y, f'ML edge {b}')
C.to_csv(f'../work/replay66_card_{VARIANT}.csv', index=False); A.to_csv(f'../work/replay66_all_{VARIANT}.csv', index=False)
