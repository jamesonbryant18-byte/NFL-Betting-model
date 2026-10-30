import sys
sys.path.insert(0, 'src')
import numpy as np, pandas as pd
from nflmodel import replay
from nflmodel.market import devig
from nflmodel.trends import fit_logistic_slope, _logit

d = replay.deployed()
h = d[d.season.isin(replay.HOLD)].reset_index(drop=True)
res = h.result.to_numpy(float); line = h.spread_line.to_numpy(float); wp = h.wp.to_numpy(float); proj = h.proj.to_numpy(float)
mkt = replay.market_wp(h)
print('hold-out games', len(h), 'ties', int((res == 0).sum()), 'pickems (line 0)', int((line == 0).sum()),
      'missing ML pair', int(np.isnan(mkt).sum()))

def paired(a, b):
    x = a - b; return x.mean(), x.std(ddof=1)/np.sqrt(len(x))

# 1a: exclude ties and pick'ems
ok = (res != 0) & (line != 0)
pick_home = wp >= 0.5; fav_home = line > 0
m_right = (pick_home == (res > 0)).astype(float); f_right = (fav_home == (res > 0)).astype(float)
dm, se = paired(m_right[ok], f_right[ok])
print(f'\n1a (ties+pickems excluded, n={ok.sum()}): model {m_right[ok].mean():.4f} fav {f_right[ok].mean():.4f} diff {100*dm:+.2f} pts SE {100*se:.2f} t {dm/se:+.2f}')
for s in replay.HOLD:
    k = ok & (h.season.to_numpy() == s)
    dm_, se_ = paired(m_right[k], f_right[k])
    print(f'   {s}: n={k.sum()} model {m_right[k].mean():.3f} fav {f_right[k].mean():.3f} diff {100*dm_:+.2f} (SE {100*se_:.2f})')
# with repo's pickem handling (ML favorite)
s = replay.scorecard(h)
print(f"   repo scorecard (pickems by ML): n={s['decided']} model {s['su_model']:.4f} fav {s['su_favorite']:.4f} diff {100*s['su_diff']:+.2f} SE {100*s['su_diff_se']:.2f}; disagree {s['disagree_won']}/{s['disagree']}")

# 1b: disagreement picks and alternative rules
dis = ok & (pick_home != fav_home)
print(f'\n1b disagreements (pickems excl): n={dis.sum()} model right {int(m_right[dis].sum())} = {m_right[dis].mean():.3f}')
# by |model prob - 0.5| among disagreements
for lo, hi in ((0.5, 0.52), (0.52, 0.55), (0.55, 1.0)):
    pp = np.maximum(wp, 1 - wp)
    k = dis & (pp >= lo) & (pp < hi)
    print(f'   model conf {lo:.2f}-{hi:.2f}: n={k.sum()} right {m_right[k].mean() if k.sum() else float("nan"):.3f}')
# alternative rules on the same games (ok & ML available for the blend)
okm = ok & ~np.isnan(mkt)
print(f'   rules on n={okm.sum()} (needs ML pair):')
rules = {'model only': pick_home, 'favorite only': fav_home}
for thr in (0.52, 0.55, 0.58, 0.60):
    pp = np.maximum(wp, 1 - wp)
    rules[f'disagree only if model p>={thr}'] = np.where(pp >= thr, pick_home, fav_home)
for w in (0.25, 0.5, 0.75):
    bl = w * wp + (1 - w) * np.nan_to_num(mkt, nan=0.5)
    rules[f'blend w_model={w}'] = np.where(bl == 0.5, fav_home, bl > 0.5)
for name, ph in rules.items():
    r = (ph == (res > 0)).astype(float)
    print(f'     {name:<32} {r[okm].mean():.4f}  ({int(r[okm].sum())})')

# 2a MAE
em, el = np.abs(res - proj), np.abs(res - line)
dm, se = paired(em, el)
print(f'\n2a MAE model {em.mean():.4f} line {el.mean():.4f} diff {dm:+.4f} SE {se:.4f} t {dm/se:+.2f} (n={len(h)})')
# 2b Brier/logloss on games with ML and decided
y = (res > 0).astype(float); kb = (res != 0) & ~np.isnan(mkt)
bm, bk = (wp - y)**2, (mkt - y)**2
dm, se = paired(bm[kb], bk[kb])
ll = lambda p: -(y*np.log(np.clip(p,1e-6,1-1e-6)) + (1-y)*np.log(np.clip(1-p,1e-6,1-1e-6)))
print(f'2b Brier model {bm[kb].mean():.4f} market {bk[kb].mean():.4f} diff {dm:+.4f} (SE {se:.4f}, t {dm/se:+.2f}) n={kb.sum()}; logloss {ll(wp)[kb].mean():.4f} vs {ll(mkt)[kb].mean():.4f}')
# 2c calibration: slope of outcome on logit(home wp); and picked-side reliability
dec = res != 0
print(f'2c slope (home p) {fit_logistic_slope(_logit(wp[dec]), y[dec]):.3f}')
# with intercept via simple IRLS
X = np.column_stack([np.ones(dec.sum()), _logit(wp[dec])]); yy = y[dec]; beta = np.zeros(2)
for _ in range(50):
    p = 1/(1+np.exp(-X@beta)); W = p*(1-p); beta += np.linalg.solve(X.T@(X*W[:,None]), X.T@(yy-p))
print(f'   with intercept: a={beta[0]:+.3f} b={beta[1]:.3f}')
pp = np.where(pick_home, wp, 1 - wp); won = m_right
bins = [0.5, .55, .6, .65, .7, .75, .8, .85, .9, .95, 1.001]
t = pd.DataFrame(dict(p=pp[dec], won=won[dec]))
t['b'] = pd.cut(t.p, bins, right=False)
g = t.groupby('b', observed=True).agg(n=('won','size'), said=('p','mean'), won=('won','mean'))
g['gap_pts'] = 100*(g.won - g.said)
print(g.round(3).to_string())
# 3b: OLS result ~ line + proj
def ols(X, y):
    X = np.column_stack([np.ones(len(y)), X]); b = np.linalg.lstsq(X, y, rcond=None)[0]
    r = y - X@b; s2 = r@r/(len(y)-X.shape[1]); cov = s2*np.linalg.inv(X.T@X); return b, np.sqrt(np.diag(cov))
b, se = ols(np.column_stack([line, proj]), res)
print(f'\n3b result ~ line + proj: line {b[1]:.3f} (se {se[1]:.3f}), proj {b[2]:+.3f} (se {se[2]:.3f}, t {b[2]/se[2]:+.2f})')
b, se = ols(np.column_stack([line, proj - line]), res)
print(f'   result ~ line + (proj-line): line {b[1]:.3f} (se {se[1]:.3f}), proj-line {b[2]:+.3f} (se {se[2]:.3f}, t {b[2]/se[2]:+.2f})')
# robustness: cluster by week? simple HC1
for s in replay.HOLD:
    k = h.season.to_numpy() == s
    b, se = ols(np.column_stack([line[k], proj[k] - line[k]]), res[k])
    print(f'   {s}: proj-line coef {b[2]:+.3f} (t {b[2]/se[2]:+.2f})')
