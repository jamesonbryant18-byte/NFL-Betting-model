"""
run_backtest.py — final validation and parameter freeze.

Two-stage discipline:
  TUNE seasons  (2013-2020) — scripts/tune.py searched the grid here
  HOLD-OUT      (2021-2025) — never touched during tuning; this is the number
                              that counts

Reporting the tuned result on the tuning seasons is how betting models fool
their authors. The hold-out figure is the honest one, and it is the one this
script leads with.

Outputs:
  data/fitted_params.json   parameters the weekly runner will use
  data/cache/residuals.npy  empirical residual distribution for probabilities
"""
import sys, json
sys.path.insert(0, 'src')
from dataclasses import replace, asdict

import numpy as np, pandas as pd

from nflmodel.config import (CACHE_DIR, PARAMS_FILE, RATINGS, MARKET,
                             MIN_ATS_WIN_RATE)
from nflmodel.ratings import fit_ratings_qb, qb_value
from nflmodel.backtest import evaluate, print_report
from nflmodel.market import devig, american_to_prob

TUNE_SEASONS = list(range(2013, 2021))
HOLDOUT_SEASONS = list(range(2021, 2026))


def run(df, seasons, params, qb_lambda):
    rows = []
    for season in seasons:
        for week in sorted(df.loc[df.season == season, 'week'].unique()):
            slate = df[(df.season == season) & (df.week == week)
                       & df.played & df.spread_line.notna()]
            if slate.empty:
                continue
            tr, qr, hfa = fit_ratings_qb(df, season, week, params, qb_lambda=qb_lambda)
            for _, g in slate.iterrows():
                proj = ((tr.get(g.home_team, 0.) + qb_value(qr, g.home_qb_name))
                        - (tr.get(g.away_team, 0.) + qb_value(qr, g.away_qb_name))
                        + (0. if g.neutral else hfa))
                rows.append(dict(
                    game_id=g.game_id, season=season, week=week,
                    home_team=g.home_team, away_team=g.away_team,
                    projected_margin=proj, adjustment=0.0,
                    spread_line=g.spread_line, result=g.result,
                    home_moneyline=g.home_moneyline, away_moneyline=g.away_moneyline,
                    neutral=g.neutral, hfa_used=hfa))
    return pd.DataFrame(rows)


def moneyline_eval(bt, min_edge=0.03):
    """Flat-stake ML performance, betting only where the de-vigged edge clears."""
    from nflmodel.market import MarginModel
    resid = (bt.result - bt.projected_margin).to_numpy()
    mm = MarginModel(residuals=resid)

    n = wins = 0
    profit = 0.0
    for _, g in bt.iterrows():
        if pd.isna(g.home_moneyline) or pd.isna(g.away_moneyline):
            continue
        wp = mm.win_prob(g.projected_margin)
        fh, fa = devig(g.home_moneyline, g.away_moneyline)
        for is_home, edge, ml in ((True, wp - fh, g.home_moneyline),
                                  (False, (1 - wp) - fa, g.away_moneyline)):
            if edge < min_edge or ml < -350 or ml > 600:
                continue
            won = (g.result > 0) if is_home else (g.result < 0)
            n += 1
            wins += int(won)
            profit += (ml / 100 if ml > 0 else 100 / -ml) if won else -1.0
    return dict(n_bets=n, wins=wins,
                win_rate=wins / n if n else float('nan'),
                roi=profit / n if n else float('nan'))


def main():
    df = pd.read_parquet(CACHE_DIR / 'dataset_2010_2025.parquet') \
           .sort_values(['season', 'week']).reset_index(drop=True)

    tuning = json.loads((CACHE_DIR / 'tuning_results.json').read_text())
    best = tuning[0]
    qb_lambda = best['qb_lambda']
    params = replace(RATINGS, **{k: v for k, v in best.items()
                                 if k in RATINGS.__dataclass_fields__})

    print('BEST PARAMETERS (fit on %d-%d only)' % (TUNE_SEASONS[0], TUNE_SEASONS[-1]))
    for k in ('ridge_lambda', 'recency_decay', 'epa_margin_weight',
              'offseason_weeks_equiv'):
        print(f'  {k:<24} {getattr(params, k)}')
    print(f'  {"qb_lambda":<24} {qb_lambda}')
    print(f'  tuning-season MAE        {best["train_mae"]:.4f}')

    bt_tune = run(df, TUNE_SEASONS, params, qb_lambda)
    bt_hold = run(df, HOLDOUT_SEASONS, params, qb_lambda)
    bt_all = pd.concat([bt_tune, bt_hold], ignore_index=True)

    res_tune = evaluate(bt_tune)
    res_hold = evaluate(bt_hold)

    print_report(res_tune, f'TUNING seasons {TUNE_SEASONS[0]}-{TUNE_SEASONS[-1]} (optimistic)')
    print_report(res_hold, f'HOLD-OUT seasons {HOLDOUT_SEASONS[0]}-{HOLDOUT_SEASONS[-1]} (honest)')

    ml = moneyline_eval(bt_hold)
    print()
    print('  MONEYLINE, hold-out, flat stakes, 3%+ de-vigged edge')
    print(f'    bets {ml["n_bets"]}   win rate {ml["win_rate"]:.2%}   ROI {ml["roi"]:+.2%}')

    # ── verdict ──
    beats_market = res_hold['market_mae'] - res_hold['model_mae'] > 0
    best_ats = max((r for r in res_hold['by_threshold']), key=lambda r: r['win_rate'])
    clears_bar = best_ats['win_rate'] >= MIN_ATS_WIN_RATE and best_ats['z_vs_breakeven'] > 1.65

    print()
    print('=' * 72)
    print('  VERDICT')
    print('=' * 72)
    if beats_market and clears_bar:
        verdict = ('Model beat the closing line out of sample and cleared the '
                   '52.38% bar with statistical significance. Bettable, at small stakes.')
    elif beats_market:
        verdict = ('Model predicted margins better than the closing line out of '
                   'sample, but no edge threshold cleared 52.38% significantly. '
                   'Promising, not yet proven. Paper trade it.')
    else:
        gap = res_hold['model_mae'] - res_hold['market_mae']
        verdict = (f'Model did NOT beat the closing line out of sample '
                   f'({gap:+.2f} pts worse per game). No demonstrated edge. '
                   f'Do not bet real money on its disagreements with the market. '
                   f'Use it as a second opinion and a bet-tracking system.')
    print('  ' + '\n  '.join(__import__('textwrap').wrap(verdict, 68)))
    print('=' * 72)

    # ── freeze ──
    resid = (bt_all.result - bt_all.projected_margin).to_numpy()
    np.save(CACHE_DIR / 'residuals.npy', resid)

    PARAMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PARAMS_FILE.write_text(json.dumps({
        'ratings': {k: getattr(params, k) for k in RATINGS.__dataclass_fields__},
        'qb_lambda': qb_lambda,
        'backtest': {
            'seasons': f'{HOLDOUT_SEASONS[0]}-{HOLDOUT_SEASONS[-1]} (hold-out)',
            'n_games': res_hold['n_games'],
            'model_mae': res_hold['model_mae'],
            'market_mae': res_hold['market_mae'],
            'best_ats_win_rate': best_ats['win_rate'],
            'best_ats_threshold': best_ats['min_edge_pts'],
            'beats_market': bool(beats_market),
            'verdict': verdict,
        },
        'residual_sd': float(resid.std()),
    }, indent=2))
    bt_all.to_parquet(CACHE_DIR / 'backtest_final.parquet', index=False)

    print(f'\n  residuals saved (n={len(resid):,}, sd={resid.std():.2f})')
    print(f'  parameters frozen -> {PARAMS_FILE}')


if __name__ == '__main__':
    main()
