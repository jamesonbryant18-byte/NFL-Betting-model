"""Grader: 2026 Weeks 1-7 live straight-up, margin and probability accuracy from the archive."""
import sys
sys.path.insert(0, 'src')
import numpy as np, pandas as pd
from nflmodel.data import load_games
from nflmodel.market import devig

g = load_games(); g = g[(g.season == 2026) & g.result.notna()]
rows = []
for wk in range(1, 8):
    p = pd.read_csv(f'picks/2026/week{wk:02d}_picks.csv')
    c = pd.read_csv(f'picks/2026/week{wk:02d}_closing.csv')
    for _, r in p.iterrows():
        away, home = [x.strip() for x in r.matchup.split('@')]
        gg = g[(g.week == wk) & (g.home_team == home) & (g.away_team == away)]
        if gg.empty:
            print('no result', wk, r.matchup); continue
        gg = gg.iloc[0]
        cr = c[(c.home_team == home) & (c.away_team == away)].iloc[0]
        hwp = r.win_prob if r.winner == home else 1 - r.win_prob
        hproj = r.proj_margin if r.winner == home else -r.proj_margin
        fav_pub_home = (r.winner == home) == bool(r.market_favorite)
        pub_line = r.spread_line if 'spread_line' in p.columns and pd.notna(r.get('spread_line')) else np.nan
        rows.append(dict(week=wk, game_id=gg.game_id, home=home, away=away, res=gg.result, hwp=hwp, hproj=hproj,
                         pick_home=r.winner == home, fav_pub_home=fav_pub_home, pub_line=pub_line,
                         close_line=cr.close_spread, chml=cr.close_home_ml, caml=cr.close_away_ml, src=cr.close_source,
                         nfl_line=gg.spread_line))
d = pd.DataFrame(rows)
print('games', len(d), 'ties', int((d.res == 0).sum()), 'pickem at close', int((d.close_line == 0).sum()),
      'close sources', d.src.value_counts().to_dict())
d['fav_close_home'] = np.where(d.close_line != 0, d.close_line > 0, d.chml < d.caml)
ok = d.res != 0
y = (d.res > 0)
for lab, fav in (('publication', 'fav_pub_home'), ('close', 'fav_close_home')):
    k = ok & ~((lab == 'close') & (d.close_line == 0))
    m = (d.pick_home == y)[k].astype(float); f = (d[fav] == y)[k].astype(float)
    x = m - f; se = x.std(ddof=1) / np.sqrt(len(x))
    dis = k & (d.pick_home != d[fav])
    print(f'SU vs favorite at {lab}: n={k.sum()} model {int(m.sum())}-{int(k.sum()-m.sum())} ({m.mean():.3f}) fav {int(f.sum())} ({f.mean():.3f}) '
          f'diff {x.sum():+.0f} games, per game {100*x.mean():+.1f} pts SE {100*se:.1f}; disagreements {dis.sum()}, model won {int((d.pick_home == y)[dis].sum())}')
    print('   disagreement games:', d.loc[dis, ['week', 'away', 'home', 'pick_home', 'res', 'hwp']].assign(
        pick=lambda z: np.where(z.pick_home, z.home, z.away)).drop(columns='pick_home').to_string(index=False).replace('\n', '\n   '))
# expected wins band
pp = np.where(d.pick_home, d.hwp, 1 - d.hwp)[ok]
print(f'expected SU wins (model odds) {pp.sum():.1f} +/- {np.sqrt((pp*(1-pp)).sum()):.1f}; actual {(d.pick_home == y)[ok].sum()}')
# MAE vs FanDuel close and vs nflverse close
em = (d.res - d.hproj).abs(); el = (d.res - d.close_line).abs(); en = (d.res - d.nfl_line).abs()
x = em - el
print(f'MAE model {em.mean():.3f} FD close {el.mean():.3f} diff {x.mean():+.3f} SE {x.std(ddof=1)/np.sqrt(len(x)):.3f} t {x.mean()/(x.std(ddof=1)/np.sqrt(len(x))):+.2f} (n={len(d)}); nflverse close MAE {en.mean():.3f}')
# Brier vs de-vigged FD close ML
fair = np.array([devig(h, a)[0] if pd.notna(h) and pd.notna(a) else np.nan for h, a in zip(d.chml, d.caml)])
kb = ok & ~np.isnan(fair)
yy = y.astype(float)
bm = (d.hwp - yy) ** 2; bk = (fair - yy) ** 2
x = (bm - bk)[kb]
ll = lambda p: -(yy*np.log(p) + (1-yy)*np.log(1-p))
print(f'Brier model {bm[kb].mean():.4f} FD close {bk[kb].mean():.4f} diff {x.mean():+.4f} t {x.mean()/(x.std(ddof=1)/np.sqrt(len(x))):+.2f} n={kb.sum()}; '
      f'logloss {ll(d.hwp)[kb].mean():.4f} vs {ll(pd.Series(fair))[kb].mean():.4f}')
# 5-pt reliability on live
pp_all = np.where(d.pick_home, d.hwp, 1 - d.hwp); won = (d.pick_home == y).astype(float)
t = pd.DataFrame(dict(p=pp_all[ok], won=won[ok]))
t['b'] = pd.cut(t.p, [0.5, .55, .6, .65, .7, .75, .8, .85, .9, 1.01], right=False)
gq = t.groupby('b', observed=True).agg(n=('won', 'size'), said=('p', 'mean'), won=('won', 'mean'))
gq['lo'] = gq.n * gq.said - 1.96 * np.sqrt(gq.n * gq.said * (1 - gq.said)); gq['hi'] = gq.n * gq.said + 1.96 * np.sqrt(gq.n * gq.said * (1 - gq.said))
gq['wins'] = gq.n * gq.won
print(gq.round(3).to_string())
d.to_csv('../work/live_games.csv', index=False)
