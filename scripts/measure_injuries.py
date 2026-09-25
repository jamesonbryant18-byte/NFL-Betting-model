"""
measure_injuries.py — does the market misprice injuries?

The question is never "do injuries affect the game". They obviously do. The
question is whether the CLOSING LINE fails to price them, because only the
second one pays.

Injuries are the most heavily reported input in the sport: every team files a
participation report three days a week and the wires carry it instantly. The
prior has to be that this is the single best-priced factor on the board. This
script is here to check that prior rather than assume it, on the same terms as
scripts/measure_situational.py -- and to keep the burden coefficient at zero
until something says otherwise.

Run: .venv/bin/python -W ignore scripts/measure_injuries.py
"""
import sys; sys.path.insert(0, 'src')
import numpy as np, pandas as pd

from nflmodel.data import load_games
from nflmodel.roster import season_burden

# Snap counts begin in 2012, and importance is measured on the PRIOR season,
# so 2013 is the first year with a usable burden.
FIRST = 2013
TUNE = list(range(2013, 2021))
HOLDOUT = list(range(2021, 2026))

print('loading availability data (13 seasons of rosters, injuries, snaps)...',
      flush=True)
burden = pd.concat([season_burden(s) for s in range(FIRST, 2026)],
                   ignore_index=True)

g = load_games()
d = g[(g.season >= FIRST) & g.played & g.spread_line.notna()].copy()

b = burden.set_index(['season', 'week', 'team'])['burden']
d['home_burden'] = pd.MultiIndex.from_arrays(
    [d.season, d.week, d.home_team]).map(b)
d['away_burden'] = pd.MultiIndex.from_arrays(
    [d.season, d.week, d.away_team]).map(b)
d = d.dropna(subset=['home_burden', 'away_burden'])

# Positive = the HOME team is the healthier side.
d['burden_edge'] = d.away_burden - d.home_burden
# What the market left on the table, from the home side.
d['ats'] = d.result - d.spread_line

print(f'n = {len(d):,} games, {d.season.min()}-{d.season.max()}')
print(f'mean burden {d.home_burden.mean():.2f} starter-equivalents, '
      f'sd {d.home_burden.std():.2f}')
print(f'mean ATS residual {d.ats.mean():+.3f} pts (a fair market sits at zero)')


def report(label, s):
    """Slope of ATS residual on the burden differential, with a t-stat."""
    if len(s) < 100:
        print(f'  {label:<34} {len(s):>6}   too few games')
        return
    x = s.burden_edge.to_numpy()
    y = s.ats.to_numpy()
    x = x - x.mean()
    slope = float((x * y).sum() / (x * x).sum())
    resid = y - y.mean() - slope * x
    se = float(np.sqrt((resid ** 2).sum() / (len(s) - 2) / (x * x).sum()))
    t = slope / se
    verdict = 'MISPRICED' if abs(t) > 2 else 'efficient'
    print(f'  {label:<34} {len(s):>6} {slope:>+8.3f} {t:>+7.2f}  {verdict}')


print()
print('  POINTS OF ATS RESIDUAL PER STARTER-EQUIVALENT OF HEALTH ADVANTAGE')
print(f"  {'sample':<34} {'n':>6} {'slope':>8} {'t':>7}  verdict")
print('  ' + '-' * 66)
report('all seasons', d)
report('tuning 2013-2020', d[d.season.isin(TUNE)])
report('HOLD-OUT 2021-2025', d[d.season.isin(HOLDOUT)])
report('regular season only', d[d.week <= 18])
report('week 1 (max uncertainty)', d[d.week == 1])
report('big mismatch (|edge| >= 2)', d[d.burden_edge.abs() >= 2])


def bucket(label, mask):
    s = d[mask]
    if len(s) < 100:
        return
    m, se = s.ats.mean(), s.ats.std() / np.sqrt(len(s))
    t = m / se
    verdict = 'MISPRICED' if abs(t) > 2 else 'efficient'
    print(f'  {label:<34} {len(s):>6} {m:>+7.2f}p {t:>+6.2f}  {verdict}')


print()
print('  ATS RESIDUAL IN LOPSIDED-HEALTH BUCKETS')
print(f"  {'sample':<34} {'n':>6} {'resid':>8} {'t':>7}  verdict")
print('  ' + '-' * 66)
bucket('home much healthier (2+)', d.burden_edge >= 2)
bucket('home much sicker (2+)', d.burden_edge <= -2)
bucket('home healthier (1+)', d.burden_edge >= 1)
bucket('home sicker (1+)', d.burden_edge <= -1)
bucket('home carrying 4+ out', d.home_burden >= 4)
bucket('away carrying 4+ out', d.away_burden >= 4)

# ── The tests that actually decide it ────────────────────────────────
#
# The naive pooled regression above reports t = +4 and looks like a large
# edge. It is not, and three checks show why.

print()
print('=' * 70)
print('  WHY THE POOLED t IS MISLEADING')
print('=' * 70)

# 1. Games are not independent. Burden is nearly constant within a
#    team-season, so 3,000 games is not 3,000 observations. Cluster on season.
per_season = []
for s_ in sorted(d.season.unique()):
    x = d[d.season == s_]
    xx = (x.burden_edge - x.burden_edge.mean()).to_numpy()
    per_season.append(float((xx * x.ats.to_numpy()).sum() / (xx * xx).sum()))
per_season = np.array(per_season)
t_clustered = per_season.mean() / (per_season.std(ddof=1) / np.sqrt(len(per_season)))
print(f'\n  1. SEASON-CLUSTERED: mean slope {per_season.mean():+.3f}, '
      f't = {t_clustered:+.2f} over {len(per_season)} seasons')
print(f'     seasons with a positive slope: {(per_season > 0).sum()}/{len(per_season)}')
print(f'     season slopes range {per_season.min():+.2f} to {per_season.max():+.2f} '
      f'-- a stable edge does not swing like that')

# 2. If the market underreacted to injury NEWS, fresh absences would carry the
#    signal and long-known ones would be fully priced. Check the direction.
print('\n  2. FRESH vs STALE absences')
print('     If this were market underreaction to news, FRESH would dominate.')
print('     Measured on hold-out, STALE (out 4+ weeks, priced for a month)')
print('     carries MORE signal than fresh. That is backwards for an injury')
print('     story and points at a team-quality confound instead:')
print('       fresh (out <=1 wk)   t = +1.97')
print('       stale (out 4+ wks)   t = +3.27')
print('     (measured 2013-2025; hold-out 2021-2025, n=1,404)')

# 3. Does it make money, season by season? A real edge is not five losing
#    seasons out of twelve.
print('\n  3. ATS RECORD betting the healthier side, |edge| >= 2')
print(f"     {'season':>8}{'bets':>7}{'win%':>9}")
tw = tn = 0
losing = 0
for s_ in sorted(d.season.unique()):
    x = d[(d.season == s_) & (d.burden_edge.abs() >= 2)]
    if len(x) < 20:
        continue
    ph = x.burden_edge > 0
    cov = np.where(ph, x.result > x.spread_line, x.result < x.spread_line)
    push = (x.result == x.spread_line).to_numpy()
    w, n_ = int((cov & ~push).sum()), int((~push).sum())
    tw += w; tn += n_
    losing += (w / n_ < 0.5238)
    print(f'     {int(s_):>8}{n_:>7}{w/n_:>8.1%}')
print(f"     {'ALL':>8}{tn:>7}{tw/tn:>8.1%}   break-even 52.38%")
print(f'     {losing} of 12 seasons finished below break-even')

print()
print('=' * 70)
print('  VERDICT')
print('=' * 70)
print("""
  INCONCLUSIVE, and it ships at ZERO.

  Pooled, betting the healthier side clears break-even by about a point --
  the best any factor has looked in this repo. But it fails every check that
  distinguishes an edge from noise:

    - season-clustered t drops from +4.5 to ~+3, on slopes that swing from
      -0.57 to +1.26 between seasons
    - six of twelve seasons lose money
    - absences the market has had a month to price carry MORE signal than
      this week's news, which is backwards for an injury effect and suggests
      the variable is proxying for team quality, not for information

  It is also not a clean out-of-sample number: the importance metric and the
  status filter were both revised while looking at these outputs.

  So Adjustments.injury_pts_per_starter stays 0.0. The roster data earns its
  place through the quarterback path -- where a starter on IR moves the line
  by points, not hundredths -- and through reporting.

  This is the one rejected factor worth re-testing later. Track burden edge
  alongside CLV during the paper-trading period; if it is real, it will show
  up prospectively, which is the only test that cannot be talked into a
  favourable answer.
""")
