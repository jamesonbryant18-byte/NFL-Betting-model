"""
weather_style_test.py — do team styles interact with bad weather in a way the
model (or the market) misses?

Hypothesis (Jameson, 2026-09-25): a team whose offense runs on its passing
game, with a weak run game, underperforms in rain/snow/wind -- the ratings
say it should win, conditions say otherwise.

Per game, 2016-2025, outdoor/open-roof only:
  bad weather   precipitation in the gamebook weather line, or wind >= 15 mph
  style         each offense's pass EPA/play minus rush EPA/play, measured on
                games BEFORE this one (season-to-date, prior season blended in
                early), so nothing about the game itself leaks in
  X             bad * (home pass-reliance - away pass-reliance)

Fit on 2016-2020, confirm on 2021-2025. Tested against two residuals: the
model's miss (result - projection) and the market's miss (result - line).
    .venv/bin/python -W ignore scripts/weather_style_test.py
"""
import sys
sys.path.insert(0, 'src')
import numpy as np
import pandas as pd
from nflmodel.config import CACHE_DIR
from nflmodel.data import load_pbp

PRECIP = r'rain|shower|drizzle|snow|sleet|flurr|storm|thunder|wintry'


def style_table(seasons):
    """Pre-game pass-reliance per (game_id, team): pass EPA/play - rush EPA/play
    over the team's earlier games, prior season weighted as 4 games of data."""
    rows = []
    for s in seasons:
        p = load_pbp(s)
        sc = p[p.play_type.isin(['pass', 'run']) & p.posteam.notna() & p.epa.notna()]
        g = sc.groupby(['game_id', 'week', 'posteam', 'play_type']).epa.agg(['sum', 'size']).unstack()
        g.columns = [f'{a}_{b}' for a, b in g.columns]
        g = g.reset_index().rename(columns={'posteam': 'team'})
        g['season'] = s
        rows.append(g)
    t = pd.concat(rows, ignore_index=True).fillna(0).sort_values(['team', 'season', 'week'])
    out = []
    for team, d in t.groupby('team'):
        prev = None
        for s, sd in d.groupby('season'):
            cum = np.zeros(4)                     # pass_sum, pass_n, run_sum, run_n
            if prev is not None:                  # prior season as 4 games' worth
                cum = prev * (4.0 / max(prev_games, 1))
            for _, r in sd.iterrows():
                ps, pn, rs, rn = cum
                rel = (ps / pn - rs / rn) if pn > 50 and rn > 30 else np.nan
                out.append((r.game_id, team, rel))
                cum = cum + np.array([r.sum_pass, r.size_pass, r.sum_run, r.size_run])
            prev = np.array([sd.sum_pass.sum(), sd.size_pass.sum(),
                             sd.sum_run.sum(), sd.size_run.sum()])
            prev_games = len(sd)
    return pd.DataFrame(out, columns=['game_id', 'team', 'pass_rel'])


def fit_line(x, y):
    b = (x * y).sum() / (x * x).sum()              # through the origin: X=0 -> no adj
    resid = y - b * x
    se = np.sqrt((resid ** 2).sum() / (len(x) - 1) / (x * x).sum())
    return b, se


def main():
    base = pd.read_parquet(CACHE_DIR / 'base_projections_2013_2025.parquet')
    base = base[base.season >= 2016]
    wx = pd.read_parquet(CACHE_DIR / 'weather_2016_2025.parquet')
    games = pd.read_parquet(CACHE_DIR / 'games.parquet')[['game_id', 'wind', 'temp']]
    df = base.merge(wx[['game_id', 'weather', 'roof']], on='game_id', how='left') \
             .merge(games, on='game_id', how='left')
    st = style_table(range(2015, 2026)).set_index(['game_id', 'team'])
    for side in ('home', 'away'):
        df[f'{side}_rel'] = st.reindex(list(zip(df.game_id, df[f'{side}_team']))).pass_rel.to_numpy()

    outdoor = df.roof.isin(['outdoors', 'open'])
    cond = df.weather.fillna('').str.lower().str.split('temp').str[0]
    precip = cond.str.contains(PRECIP)
    windy = df.wind.fillna(0) >= 15
    df['bad'] = (outdoor & (precip | windy)).astype(float)
    df['precip'] = (outdoor & precip).astype(float)
    df['rel_diff'] = df.home_rel - df.away_rel
    df = df.dropna(subset=['rel_diff', 'spread_line', 'result'])
    print(f"games {len(df)}; outdoor {outdoor.sum()}; bad-weather {int(df.bad.sum())} "
          f"(precip {int(df.precip.sum())}, wind>=15 {int((df.bad - df.precip).clip(0).sum())})")

    df['r_model'] = df.result - df.projected_margin
    df['r_market'] = df.result - df.spread_line
    for flag in ('bad', 'precip'):
        print(f'\n=== condition: {flag} ===')
        for lo, hi, name in ((2016, 2020, 'FIT  2016-20'), (2021, 2025, 'HOLD 2021-25')):
            x = df[df.season.between(lo, hi)]
            X = (x[flag] * x.rel_diff).to_numpy()
            n = int((x[flag] > 0).sum())
            for r in ('r_model', 'r_market'):
                b, se = fit_line(X, x[r].to_numpy())
                print(f'  {name}  n_bad={n:<4} {r:<9} slope {b:+7.2f} pts per unit  '
                      f'(se {se:5.2f}, t {b/se:+5.2f})')
            # contrast: same interaction in GOOD weather should be ~0
            Xg = ((1 - x[flag]) * x.rel_diff).to_numpy()
            b, se = fit_line(Xg, x.r_model.to_numpy())
            print(f'  {name}  good-weather control, r_model slope {b:+6.2f} (t {b/se:+5.2f})')

        # apply the FIT-period slope to the hold-out and score it
        f = df[df.season.between(2016, 2020)]
        b, _ = fit_line((f[flag] * f.rel_diff).to_numpy(), f.r_model.to_numpy())
        h = df[df.season.between(2021, 2025)].copy()
        h['adj'] = b * h[flag] * h.rel_diff
        h['proj2'] = h.projected_margin + h.adj
        hb = h[h[flag] > 0]
        m0 = (hb.result - hb.projected_margin).abs().mean()
        m1 = (hb.result - hb.proj2).abs().mean()
        print(f'  apply fit slope {b:+.2f} to hold-out {flag} games (n={len(hb)}): '
              f'MAE {m0:.3f} -> {m1:.3f}; mean |adj| {hb.adj.abs().mean():.2f} pts')
        e0 = hb.projected_margin - hb.spread_line
        e1 = hb.proj2 - hb.spread_line
        cov = hb.result > hb.spread_line
        g = hb.result != hb.spread_line
        for e, lab in ((e0, 'before'), (e1, 'after')):
            won = np.where(e > 0, cov, ~cov)
            s = g & (e.abs() >= 1.5)
            print(f'    ATS>=1.5 {lab}: {won[s].mean():.1%} on {int(s.sum())} bets')

    print('\n  pass-reliance spread (sd across teams):', round(df.home_rel.std(), 3))


if __name__ == '__main__':
    main()
