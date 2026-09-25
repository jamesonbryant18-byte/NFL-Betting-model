"""
adjust_lab.py — which kinds of weekly adjustment actually help?

The score-based self-tune double-counts: the ratings are re-fit every week on
every game, so last Sunday's score is already in them. An adjustment can only
help if it learns from something the ratings do NOT use. This lab tests
several such signals on top of the frozen walk-forward projections
(build_base_projections.py), each at several strengths.

Each variant feeds a per-game residual into a per-team memory, and the next
week's projection moves by alpha * (memory[home] - memory[away]), capped at
max_adj points per game. Discipline: choose on 2013-2020, confirm on the
2021-2025 hold-out. A variant only counts if it helps on BOTH.

    .venv/bin/python -W ignore scripts/adjust_lab.py
"""
import sys
sys.path.insert(0, 'src')
from collections import defaultdict
import numpy as np
import pandas as pd
from nflmodel.config import CACHE_DIR
from nflmodel.data import load_pbp

TUNE = (2013, 2020)
HOLD = (2021, 2025)


def team_game_stats(seasons):
    rows = []
    for s in seasons:
        p = load_pbp(s)
        sc = p[p.play_type.isin(['pass', 'run']) & p.posteam.notna() & p.epa.notna()]
        g = sc.groupby(['game_id', 'posteam']).agg(
            off_epa_sum=('epa', 'sum'), plays=('epa', 'size'),
            ints=('interception', 'sum'), fl=('fumble_lost', 'sum')).reset_index()
        rows.append(g.rename(columns={'posteam': 'team'}))
    return pd.concat(rows, ignore_index=True)


def attach(base, tg):
    t = tg.set_index(['game_id', 'team'])
    out = base.copy()
    for side in ('home', 'away'):
        k = list(zip(out.game_id, out[f'{side}_team']))
        sub = t.reindex(k)
        for c in ('off_epa_sum', 'ints', 'fl'):
            out[f'{side}_{c}'] = sub[c].to_numpy()
    out['epa_margin'] = out.home_off_epa_sum - out.away_off_epa_sum
    out['to_margin'] = (out.away_ints + out.away_fl) - (out.home_ints + out.home_fl)
    out['fl_margin'] = out.away_fl - out.home_fl
    return out


# signal(game, shipped_projection) -> residual credited to the home team
SIGNALS = {
    'score':        lambda g, p: g.result - p,
    'score_noTO':   lambda g, p: (g.result - 4.0 * g.to_margin) - p,
    'score_noFumb': lambda g, p: (g.result - 4.0 * g.fl_margin) - p,
    'epa':          lambda g, p: g.epa_margin - p,
    'epa_score':    lambda g, p: 0.5 * (g.epa_margin + g.result) - p,
    'vs_market':    lambda g, p: g.result - g.spread_line,
}


def run(df, signal, alpha, half_life=3.0, clip=7.0, max_adj=1.0, prior=0.0):
    """Closed-loop walk-forward. prior>0 shrinks a team's memory toward 0 as
    if it had `prior` extra games of zero residual (Bayesian shrinkage)."""
    decay = 0.5 ** (1.0 / half_life)
    f = SIGNALS[signal]
    adj_all = np.zeros(len(df))
    df = df.reset_index(drop=True)
    for season, sdf in df.groupby('season', sort=True):
        mem = defaultdict(list)
        for wk, wdf in sdf.groupby('week', sort=True):
            def corr(team):
                obs = mem.get(team)
                if not obs:
                    return 0.0
                w = np.array([decay ** (wk - t) for t, _ in obs])
                v = np.array([r for _, r in obs])
                return float((w * v).sum() / (w.sum() + prior))
            new = []
            for i, g in wdf.iterrows():
                a = alpha * (corr(g.home_team) - corr(g.away_team))
                a = float(np.clip(a, -max_adj, max_adj)) if max_adj else a
                adj_all[i] = a
                shipped = g.projected_margin + a
                r = f(g, shipped)
                if pd.notna(r):
                    r = float(np.clip(r, -clip, clip)) if clip else float(r)
                    new.append((g.home_team, g.away_team, r))
            for h, aw, r in new:
                mem[h].append((wk, r))
                mem[aw].append((wk, -r))
    out = df.copy()
    out['proj'] = out.projected_margin + adj_all
    out['adj'] = adj_all
    return out


def score(bt, lo, hi):
    x = bt[bt.season.between(lo, hi)]
    err = (x.result - x.proj).abs()
    base_err = (x.result - x.projected_margin).abs()
    d = err - base_err
    t = d.mean() / (d.std(ddof=1) / np.sqrt(len(d))) if d.std() > 0 else 0.0
    edge = x.proj - x.spread_line
    graded = x.result != x.spread_line
    home_cov = x.result > x.spread_line
    won = np.where(edge > 0, home_cov, ~home_cov)
    sel = graded & (edge.abs() >= 1.5)
    su_g = x.result != 0
    su = (np.sign(x.proj) == np.sign(x.result))[su_g].mean()
    return dict(mae=err.mean(), d_mae=d.mean(), t=t,
                su=su, ats15=won[sel].mean(), n15=int(sel.sum()),
                mean_adj=x.adj.abs().mean())


def main():
    base = pd.read_parquet(CACHE_DIR / 'base_projections_2013_2025.parquet')
    tg = team_game_stats(range(2013, 2026))
    df = attach(base, tg).sort_values(['season', 'week']).reset_index(drop=True)
    print(f'games: {len(df)}; epa coverage {df.epa_margin.notna().mean():.1%}')

    zero = run(df, 'score', 0.0)
    ref = {k: score(zero, *k) for k in (TUNE, HOLD)}
    print(f"frozen  tune MAE {ref[TUNE]['mae']:.3f} ATS {ref[TUNE]['ats15']:.2%} | "
          f"hold MAE {ref[HOLD]['mae']:.3f} ATS {ref[HOLD]['ats15']:.2%}")

    grid = []
    for sig in SIGNALS:
        for prior in (0.0, 3.0):
            for max_adj in (1.0, 3.0, None):
                for alpha in (0.1, 0.25, 0.5, 0.75, 1.0):
                    bt = run(df, sig, alpha, prior=prior, max_adj=max_adj)
                    a, b = score(bt, *TUNE), score(bt, *HOLD)
                    grid.append(dict(signal=sig, prior=prior, max_adj=max_adj,
                                     alpha=alpha,
                                     tune_dmae=a['d_mae'], tune_t=a['t'],
                                     tune_ats=a['ats15'] - ref[TUNE]['ats15'],
                                     hold_dmae=b['d_mae'], hold_t=b['t'],
                                     hold_ats=b['ats15'] - ref[HOLD]['ats15'],
                                     hold_su=b['su'] - ref[HOLD]['su'],
                                     adj=b['mean_adj']))
    g = pd.DataFrame(grid)
    g.to_csv(CACHE_DIR / 'adjust_lab.csv', index=False)
    pd.set_option('display.width', 200)
    fmt = g.copy()
    for c in ('tune_ats', 'hold_ats', 'hold_su'):
        fmt[c] = (fmt[c] * 100).round(2)
    for c in ('tune_dmae', 'hold_dmae', 'tune_t', 'hold_t', 'adj'):
        fmt[c] = fmt[c].round(3)
    print(fmt.to_string(index=False))


if __name__ == '__main__':
    main()
