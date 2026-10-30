"""Live 2026 Weeks 1-7 from the archive: SU vs favorite (publication/close), MAE, Brier, calibration."""
import sys
sys.path.insert(0, 'src'); sys.path.insert(0, '../work')
import numpy as np, pandas as pd
from nflmodel.data import load_games
from metrics import *

g = load_games(); g = g[(g.season == 2026) & g.played]
rows = []
for w in range(1, 8):
    p = pd.read_csv(f'picks/2026/week{w:02d}_picks.csv')
    c = pd.read_csv(f'picks/2026/week{w:02d}_closing.csv')
    s = pd.read_csv(f'output/slate_2026_wk{w:02d}.csv')
    for _, r in p.iterrows():
        away, home = [x.strip() for x in r.matchup.split('@')]
        gg = g[(g.week == w) & (g.home_team == home) & (g.away_team == away)]
        if gg.empty:
            continue
        gg = gg.iloc[0]
        hwp = r.win_prob if r.at_home else 1 - r.win_prob
        hm = r.proj_margin if r.at_home else -r.proj_margin
        pub_line = r.spread_line if 'spread_line' in p.columns and pd.notna(r.get('spread_line')) else np.nan
        if np.isnan(pub_line):
            ss = s[(s.home_team == home) & (s.away_team == away)]
            pub_line = float(ss.spread_line.iloc[0]) if len(ss) else np.nan
        cc = c[(c.home_team == home) & (c.away_team == away)].iloc[0]
        rows.append(dict(week=w, game=r.matchup, home=home, away=away, pick=r.winner, home_wp=hwp, home_margin=hm,
                         pub_line=pub_line, mf_flag=bool(r.market_favorite), close_line=cc.close_spread,
                         close_hml=cc.close_home_ml, close_aml=cc.close_away_ml, result=gg.result,
                         tier=r.confidence, pick_p=r.win_prob))
L = pd.DataFrame(rows)
# carried games with no archived line: favourite = model pick if market_favorite flag set (sign only)
miss = L.pub_line.isna()
L.loc[miss, 'pub_line'] = np.where((L.loc[miss, 'home_wp'] >= 0.5) == L.loc[miss, 'mf_flag'], 1.0, -1.0) * np.nan_to_num(L.loc[miss, 'close_line'].abs(), nan=1.0)
print('filled publication-line sign from market_favorite flag for', int(miss.sum()), 'carried game(s):', L.loc[miss, 'game'].tolist())
L.to_csv('../work/live_games.csv', index=False)
print('graded games', len(L), 'ties', int((L.result == 0).sum()))
# consistency: market_favorite flag vs pub_line
chk = L[L.pub_line.notna() & (L.pub_line != 0)]
mf = ((chk.pub_line > 0) == (chk.home_wp >= 0.5))
print('market_favorite flag agrees with archived pub line on', int((mf == chk.mf_flag).sum()), 'of', len(chk))

for nm, col in (('publication', 'pub_line'), ('close (FanDuel)', 'close_line')):
    r = su_vs_fav(L.home_wp, L[col], L.result)
    ok = (L[col] != 0) & (L.result != 0)
    exp = L.loc[ok, 'pick_p'].sum(); sd = np.sqrt((L.loc[ok, 'pick_p'] * (1 - L.loc[ok, 'pick_p'])).sum())
    print(f"SU vs favorite at {nm}: n={r['n']} (pk excl {r['n_excl_pk']}, ties {r['n_excl_tie']}) model {r['wins_model']} ({r['model']:.3f}) "
          f"fav {r['wins_fav']} ({r['fav']:.3f}) diff {100*r['diff']:+.1f} pts (se {100*r['se']:.1f}) | disagreements {r['n_dis']} won {r['dis_hit']:.3f} "
          f"| model expected {exp:.1f} +/- {1.96*sd:.1f}")
    ok = (L[col] != 0) & (L.result != 0)
    dis = ok & ((L.home_wp >= 0.5) != (L[col] > 0))
    print(L.loc[dis, ['week', 'game', 'pick', 'home_wp', col, 'result']].to_string(index=False))

print('\nraw SU', int(((L.home_wp >= 0.5) == (L.result > 0))[L.result != 0].sum()), 'of', int((L.result != 0).sum()))
em = (L.result - L.home_margin).abs(); ec = (L.result - L.close_line).abs(); ep = (L.result - L.pub_line).abs()
d, se, t = paired(em, ec)
print(f'MAE live: model {em.mean():.3f}  FanDuel close {ec.mean():.3f}  line at publication {ep.mean():.3f}  model-close {d:+.3f} (t {t:+.2f}) n={len(L)}')
ok = (L.result != 0) & L.close_hml.notna() & L.close_aml.notna()
y = (L.result[ok] > 0).astype(float).to_numpy()
pm = devig_home(L.close_hml[ok], L.close_aml[ok]); pmod = L.home_wp[ok].to_numpy()
bm, bk = (pmod - y) ** 2, (pm - y) ** 2
d, se, t = paired(bm, bk)
lm = -(y * np.log(pmod) + (1 - y) * np.log(1 - pmod)); lk = -(y * np.log(pm) + (1 - y) * np.log(1 - pm))
print(f'Brier live: model {bm.mean():.4f} market(devig FD close) {bk.mean():.4f} diff {d:+.4f} (t {t:+.2f}); logloss {lm.mean():.4f} vs {lk.mean():.4f}; n={ok.sum()}')
print('\nlive calibration (picked side, 5-pt buckets):')
nt = L.result != 0
won = ((L.home_wp >= 0.5) == (L.result > 0))[nt].astype(float)
pp = L.pick_p[nt]
cut = pd.cut(pp, np.arange(0.5, 1.0001, 0.05), include_lowest=True)
t = pd.DataFrame({'b': cut, 'p': pp, 'w': won}).groupby('b', observed=True).agg(n=('w', 'size'), said=('p', 'mean'), won=('w', 'mean'))
t['band_lo'] = (t.said - 1.96 * np.sqrt(t.said * (1 - t.said) / t.n)).clip(0); t['band_hi'] = (t.said + 1.96 * np.sqrt(t.said * (1 - t.said) / t.n)).clip(upper=1)
print(t.round(3).to_string())
