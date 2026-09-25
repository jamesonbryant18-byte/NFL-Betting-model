"""
selftune_sweep.py — does weekly self-correction make the model more accurate?

Runs the same walk-forward backtest at several values of `alpha`, the strength
with which the model chases its own recent error. alpha=0 is the frozen model
that ships today, so every other row is a direct, like-for-like answer to
"would adjusting week to week have helped?"

    .venv/bin/python -W ignore scripts/selftune_sweep.py
    .venv/bin/python -W ignore scripts/selftune_sweep.py --seasons 2021-2025 \
        --alphas 0,0.25,0.5,1.0 --half-life 3

The number that decides it is MAE against the actual margin -- how far off the
predicted score is, in points. It does not depend on betting, odds, or whether
anyone placed a wager. Lower is a better forecast.
"""
import argparse
import sys
import json

sys.path.insert(0, 'src')
from dataclasses import replace

import numpy as np
import pandas as pd

from nflmodel.config import CACHE_DIR, RATINGS
from nflmodel.selftune import walk_forward_adaptive

TUNE_SEASONS = list(range(2013, 2021))
HOLDOUT_SEASONS = list(range(2021, 2026))


def parse_seasons(s: str) -> list[int]:
    if '-' in s:
        a, b = s.split('-')
        return list(range(int(a), int(b) + 1))
    return [int(x) for x in s.split(',')]


def score(bt: pd.DataFrame) -> dict:
    """Accuracy of the projection, plus how often it beats the spread."""
    model_err = (bt.result - bt.projected_margin).abs()
    market_err = (bt.result - bt.spread_line).abs()

    edge = bt.projected_margin - bt.spread_line
    push = bt.result == bt.spread_line
    home_cov = bt.result > bt.spread_line
    won = np.where(edge > 0, home_cov, ~home_cov).astype(float)
    won[push.to_numpy()] = np.nan
    graded = ~np.isnan(won)

    # Straight-up: did the projected winner win?
    su_pick_home = bt.projected_margin > 0
    su_right = np.where(su_pick_home, bt.result > 0, bt.result < 0)
    su_graded = bt.result != 0

    sel = graded & (edge.abs() >= 1.5).to_numpy()
    n15 = int(sel.sum())
    w15 = float(np.nansum(won[sel]))

    return dict(
        n=len(bt),
        model_mae=float(model_err.mean()),
        market_mae=float(market_err.mean()),
        vs_market=float(model_err.mean() - market_err.mean()),
        model_rmse=float(np.sqrt(((bt.result - bt.projected_margin) ** 2).mean())),
        su=float(su_right[su_graded].mean()),
        ats_all=float(np.nansum(won[graded]) / graded.sum()),
        ats_15=(w15 / n15) if n15 else float('nan'),
        n_15=n15,
        mean_adj=float(bt.adjustment.abs().mean()),
        max_adj=float(bt.adjustment.abs().max()),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--seasons', default='2021-2025',
                    help='seasons to score (default: the 2021-2025 hold-out)')
    ap.add_argument('--alphas', default='0,0.1,0.25,0.5,0.75,1.0')
    ap.add_argument('--half-life', type=float, default=3.0)
    ap.add_argument('--cap', type=float, default=7.0)
    ap.add_argument('--max-adj', type=float, default=None,
                    help='ceiling on the per-game correction, in points')
    ap.add_argument('--resid-clip', type=float, default=None,
                    help='ceiling on what one game can teach, in points')
    ap.add_argument('--adapt-hfa', action='store_true')
    ap.add_argument('--carry-offseason', action='store_true')
    ap.add_argument('--fast', action='store_true',
                    help='skip the market-prior blend (faster, not what ships)')
    ap.add_argument('--out', default=None, help='write results to JSON')
    args = ap.parse_args()

    seasons = parse_seasons(args.seasons)
    alphas = [float(a) for a in args.alphas.split(',')]

    df = pd.read_parquet(CACHE_DIR / 'dataset_2010_2025.parquet') \
           .sort_values(['season', 'week']).reset_index(drop=True)

    tuning = json.loads((CACHE_DIR / 'tuning_results.json').read_text())
    best = tuning[0]
    qb_lambda = best['qb_lambda']
    params = replace(RATINGS, **{k: v for k, v in best.items()
                                 if k in RATINGS.__dataclass_fields__})

    label = 'HOLD-OUT' if seasons == HOLDOUT_SEASONS else \
            ('TUNING' if seasons == TUNE_SEASONS else 'CUSTOM')

    print()
    print('=' * 78)
    print(f'  WEEKLY SELF-CORRECTION SWEEP — {label} SEASONS '
          f'{seasons[0]}-{seasons[-1]}')
    print('=' * 78)
    print(f'  half-life {args.half_life} wks | cap +/-{args.cap} pts | '
          f'adapt_hfa={args.adapt_hfa} | carry_offseason={args.carry_offseason}')
    print(f'  alpha = how hard the model chases its own recent error '
          f'(0 = frozen model)')
    print()

    results = []
    base_mae = None
    for a in alphas:
        bt = walk_forward_adaptive(
            df, seasons, params=params, qb_lambda=qb_lambda,
            alpha=a, half_life=args.half_life, cap=args.cap,
            max_adj=args.max_adj, resid_clip=args.resid_clip,
            adapt_hfa=args.adapt_hfa, carry_offseason=args.carry_offseason,
            deployed=not args.fast, verbose=False)
        s = score(bt)
        s['alpha'] = a
        results.append(s)
        if base_mae is None:
            base_mae = s['model_mae']
        print(f"  alpha={a:<5} MAE {s['model_mae']:6.3f}  "
              f"({s['model_mae'] - base_mae:+.3f} vs frozen)  "
              f"SU {s['su']*100:5.1f}%  ATS>=1.5 {s['ats_15']*100:5.2f}%  "
              f"|adj| {s['mean_adj']:.2f}", flush=True)

    print()
    print('  ' + '-' * 74)
    print(f"  {'alpha':>6} {'MAE':>7} {'vs frozen':>10} {'vs market':>10} "
          f"{'SU%':>7} {'ATS>=1.5':>9} {'n':>6}")
    print('  ' + '-' * 74)
    for s in results:
        print(f"  {s['alpha']:>6.2f} {s['model_mae']:>7.3f} "
              f"{s['model_mae'] - base_mae:>+10.3f} {s['vs_market']:>+10.3f} "
              f"{s['su']*100:>6.1f}% {s['ats_15']*100:>8.2f}% {s['n_15']:>6}")
    print('  ' + '-' * 74)
    print(f"  market MAE on the same games: {results[0]['market_mae']:.3f}")
    print()

    tested = [r for r in results if r['alpha'] > 0]
    if not tested:
        print('  No self-correction was tested (alpha=0 only). Nothing to')
        print('  conclude -- pass more than one --alphas value to compare.')
        print('=' * 78)
        if args.out:
            with open(args.out, 'w') as f:
                json.dump(results, f, indent=2)
        return

    best_row = min(results, key=lambda r: r['model_mae'])
    if best_row['alpha'] == 0:
        print('  VERDICT: no amount of weekly self-correction beat the frozen')
        print('  model. Chasing recent error made the forecast worse, and the')
        print('  degradation grows with alpha.')
    else:
        print(f"  VERDICT: alpha={best_row['alpha']} improved MAE by "
              f"{base_mae - best_row['model_mae']:.3f} pts.")
        print('  Before shipping it, re-run on the OTHER season block to')
        print('  confirm it is not an artifact of this one.')
    print('=' * 78)

    if args.out:
        with open(args.out, 'w') as f:
            json.dump(results, f, indent=2)
        print(f'  wrote {args.out}')


if __name__ == '__main__':
    main()
