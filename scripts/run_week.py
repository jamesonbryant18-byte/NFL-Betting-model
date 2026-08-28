"""
run_week.py — produce the week's slate, workbook, and terminal report.

Usage:
    python scripts/run_week.py                # current season, next unplayed week
    python scripts/run_week.py --week 5
    python scripts/run_week.py --season 2026 --week 1 --refresh
"""
import sys, argparse, json
sys.path.insert(0, 'src')
import numpy as np, pandas as pd

from nflmodel.config import (ADVISORY_MODE, CURRENT_SEASON, OUTPUT_DIR,
                             PARAMS_FILE, RATINGS, STAKING, TRAIN_SEASON_START)
from nflmodel.data import build_dataset, load_games
from nflmodel.model import NFLModel
from nflmodel.excel import build_workbook
from nflmodel.ratings import qb_value


def load_fitted():
    """Apply backtest-fitted parameters if run_backtest.py has been run."""
    from dataclasses import replace
    if not PARAMS_FILE.exists():
        return RATINGS, 40.0, None
    p = json.loads(PARAMS_FILE.read_text())
    ratings = replace(RATINGS, **{k: v for k, v in p['ratings'].items()
                                  if k in RATINGS.__dataclass_fields__})
    return ratings, p.get('qb_lambda', 40.0), p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--season', type=int, default=CURRENT_SEASON)
    ap.add_argument('--week', type=int, default=None)
    ap.add_argument('--refresh', action='store_true')
    args = ap.parse_args()

    params, qb_lambda, fitted = load_fitted()

    seasons = list(range(TRAIN_SEASON_START, args.season + 1))
    print('loading data...', flush=True)
    hist = build_dataset(seasons, refresh=args.refresh)
    games = load_games(refresh=args.refresh)

    season_games = games[games.season == args.season]
    if args.week is None:
        unplayed = season_games[~season_games.played]
        if unplayed.empty:
            print(f'no unplayed games left in {args.season}')
            return
        week = int(unplayed.week.min())
    else:
        week = args.week

    slate_games = season_games[
        (season_games.week == week) & season_games.spread_line.notna()
    ].copy()

    if slate_games.empty:
        print(f'no games with posted lines for {args.season} week {week}')
        return

    model = NFLModel(params=params, qb_lambda=qb_lambda)
    model.fit(hist, args.season, week, market_games=games)

    from nflmodel.config import CACHE_DIR
    rp = CACHE_DIR / 'residuals.npy'
    if rp.exists():
        model.set_residuals(np.load(rp))
        print(f'using empirical residual distribution (n={len(np.load(rp)):,})')
    else:
        print('WARNING: no residuals cached — run scripts/run_backtest.py first. '
              'Falling back to a normal approximation, which misprices key numbers.')

    slate = model.project_slate(slate_games)

    # ── terminal report ──
    print()
    print('=' * 78)
    print(f'  NFL MODEL — {args.season} WEEK {week}'.ljust(60) + f'HFA {model.hfa:+.2f}'.rjust(16))
    print('=' * 78)
    print(f"  {'matchup':<20}{'model':>10}{'vegas':>9}{'edge':>8}{'cover':>8}  {'recommendation':<22}{'stake':>7}")
    print('  ' + '-' * 74)
    for _, g in slate.iterrows():
        cover = g.home_cover_prob if g.spread_edge_pts > 0 else g.away_cover_prob
        mark = ' *' if g.stake > 0 else '  '
        print(f"  {g.away_team + ' @ ' + g.home_team:<20}"
              f"{g.home_team + ' ' + format(g.fair_spread, '+.1f'):>10}"
              f"{format(g.spread_line, '+.1f'):>9}"
              f"{format(g.spread_edge_pts, '+.1f'):>8}"
              f"{cover:>7.1%}  {g.recommendation:<22}"
              f"{('$%.0f' % g.stake) if g.stake else '—':>7}{mark}")
    bets = slate[slate.stake > 0]
    print('  ' + '-' * 74)
    if ADVISORY_MODE:
        leans = slate[slate.recommendation.str.startswith('LEAN')]
        print(f"  ADVISORY MODE — {len(leans)} lean(s), $0 staked.")
        print(f"  The hold-out backtest found no edge vs closing lines, so the model")
        print(f"  stakes nothing by default. Set ADVISORY_MODE=False in config.py to bet.")
    else:
        print(f"  {len(bets)} qualifying bet(s), ${bets.stake.sum():,.0f} staked "
              f"({bets.stake.sum()/STAKING.bankroll:.1%} of bankroll, "
              f"cap {STAKING.max_weekly_exposure_pct:.0%})")
    print('=' * 78)

    # ── workbook ──
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f'NFL_Model_{args.season}_Week{week:02d}.xlsx'
    summary = fitted.get('backtest') if fitted else None
    build_workbook(slate, model.power_ratings(), args.season, week,
                   backtest_summary=summary, path=str(path))
    print(f'\n  workbook: {path}')

    slate.to_csv(OUTPUT_DIR / f'slate_{args.season}_wk{week:02d}.csv', index=False)


if __name__ == '__main__':
    main()
