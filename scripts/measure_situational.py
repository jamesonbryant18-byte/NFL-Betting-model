"""
measure_situational.py — test situational factors against the closing line.

Run this each offseason. The question is never "does this factor affect the
game" -- it is "does the market fail to price it". Only the second one pays.
"""
import sys; sys.path.insert(0, 'src')
import numpy as np, pandas as pd
from nflmodel.data import load_games, TEAM_TZ_OFFSET

g = load_games()
d = g[(g.season >= 2006) & g.played & g.spread_line.notna()].copy()
d['ats'] = d.result - d.spread_line

print(f"n={len(d)}  mean ATS residual {d.ats.mean():+.3f} pts "
      f"(a fair market sits at zero)\n")
print(f"  {'factor':<34} {'n':>6} {'resid':>8} {'t':>7}  verdict")
print("  " + "-" * 66)

def test(name, mask):
    s = d[mask]
    if len(s) < 60:
        return
    m, se = s.ats.mean(), s.ats.std() / np.sqrt(len(s))
    t = m / se
    verdict = "MISPRICED" if abs(t) > 2 else "efficient"
    print(f"  {name:<34} {len(s):>6} {m:>+7.2f}p {t:>+6.2f}  {verdict}")

d['rest_diff'] = d.home_rest - d.away_rest
d['tz'] = d.home_team.map(TEAM_TZ_OFFSET) - d.away_team.map(TEAM_TZ_OFFSET)
out = d[d.roof.isin(['outdoors', 'open'])]

test('home off bye', d.home_rest >= 13)
test('away off bye', d.away_rest >= 13)
test('home short week', d.home_rest <= 4)
test('away short week', d.away_rest <= 4)
test('home rest edge 3+ days', d.rest_diff >= 3)
test('away rest edge 3+ days', d.rest_diff <= -3)
test('wind >= 15mph (outdoor)', d.index.isin(out[out.wind >= 15].index))
test('wind >= 20mph (outdoor)', d.index.isin(out[out.wind >= 20].index))
test('cold < 32F (outdoor)', d.index.isin(out[out.temp < 32].index))
# tz = home_offset - away_offset, negative = home further west.
# tz >= 2 means the home stadium is EAST of the away stadium, i.e. the away
# team travelled east. These two labels were previously swapped.
test('away travelled EAST 2+ zones', d.tz >= 2)
test('away travelled WEST 2+ zones', d.tz <= -2)
test('week 17', d.week == 17)
test('week 18', d.week == 18)
test('divisional', d.div_game == 1)
test('favorite of 10+', d.spread_line.abs() >= 10)
test('home underdog', d.spread_line < 0)

print("\n  Any factor reaching |t| > 2 is a candidate for a nonzero coefficient")
print("  in config.Adjustments. Nothing has cleared that bar as of 2025.")
