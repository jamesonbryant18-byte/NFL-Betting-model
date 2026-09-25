"""
grade.py — the model grades its own past predictions.

Run this every week. It answers one question: how accurate has this model
been, and is it wrong in a *pattern* that can be fixed?

Betting is irrelevant here. Every prediction the model has ever published is
graded whether or not a dollar was ever placed on it. Accuracy is the product;
wagering is a downstream decision.

    .venv/bin/python -W ignore scripts/grade.py              # this season
    .venv/bin/python -W ignore scripts/grade.py --diagnose   # + error hunt
    .venv/bin/python -W ignore scripts/grade.py --diagnose --scope all

Three sections:

  SEASON SCORECARD   every published pick this season, graded. Straight-up
                     record, average error in points against the closing line
                     as benchmark, calibration by confidence tier, and how the
                     value picks did.

  SYSTEMATIC ERROR   the part that can actually drive an improvement. Splits
                     every prediction into segments (favorites, dogs, road
                     teams, divisional games, QB changes, spread buckets,
                     early/late season) and asks whether the model is biased
                     inside any of them. Corrected for multiple comparisons,
                     because testing twenty segments guarantees one "finding"
                     at p<0.05 by chance alone.

  VERDICT            what, if anything, the evidence supports changing.

The bar for a change is deliberately high and it is not this script's to
waive: a candidate must survive Benjamini-Hochberg here, then improve
out-of-sample accuracy in scripts/selftune_sweep.py or scripts/run_backtest.py
on seasons it was not discovered in. See IMPROVEMENT.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, 'src')

import numpy as np
import pandas as pd

from nflmodel.config import CACHE_DIR, RATINGS, CURRENT_SEASON
from nflmodel.data import load_games
from nflmodel.selftune import walk_forward_adaptive

PICKS_DIR = Path('picks')
SCORECARD = Path('data/scorecard.json')


# ── helpers ──────────────────────────────────────────────────────────────

def benjamini_hochberg(pvals: list[float], q: float = 0.05) -> list[bool]:
    """Which p-values survive at false-discovery rate q. Order preserved."""
    n = len(pvals)
    if n == 0:
        return []
    order = np.argsort(pvals)
    passed = np.zeros(n, dtype=bool)
    crit = 0
    for rank, idx in enumerate(order, start=1):
        if pvals[idx] <= q * rank / n:
            crit = rank
    for rank, idx in enumerate(order, start=1):
        if rank <= crit:
            passed[idx] = True
    return passed.tolist()


def _t_and_p(x: np.ndarray) -> tuple[float, float]:
    """One-sample t against zero, with a normal-approximation p-value."""
    x = x[~np.isnan(x)]
    if len(x) < 8 or x.std(ddof=1) == 0:
        return float('nan'), float('nan')
    t = x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))
    # two-sided, normal approximation (n is large in every segment we report)
    from math import erfc, sqrt
    p = erfc(abs(t) / sqrt(2))
    return float(t), float(p)


# ── season scorecard ─────────────────────────────────────────────────────

def season_scorecard(season: int) -> dict | None:
    """Grade every pick published this season, from the picks/ archive."""
    games = load_games()
    games = games[(games.season == season) & games.result.notna()]
    if games.empty:
        return None

    rows, lean_rows = [], []
    for pf in sorted((PICKS_DIR / str(season)).glob('week*_picks.csv')):
        week = int(pf.stem.split('_')[0].replace('week', ''))
        picks = pd.read_csv(pf)
        for _, r in picks.iterrows():
            g = games[((games.home_team == r.winner) & (games.away_team == r.loser))
                      | ((games.home_team == r.loser) & (games.away_team == r.winner))]
            if g.empty:
                continue
            g = g.iloc[0]
            # margin from the PICKED team's perspective
            actual = g.result if g.home_team == r.winner else -g.result
            market = -g.spread_line if g.home_team == r.winner else g.spread_line
            rows.append(dict(week=week, pick=r.winner, opp=r.loser,
                             proj=float(r.proj_margin), actual=float(actual),
                             market=float(-market), win_prob=float(r.win_prob),
                             confidence=r.confidence, won=bool(actual > 0)))

        lf = pf.with_name(pf.name.replace('_picks', '_leans'))
        if lf.exists():
            leans = pd.read_csv(lf)
            for _, r in leans.iterrows():
                g = games[games.game_id == r.game_id]
                if g.empty:
                    continue
                g = g.iloc[0]
                side = str(r.bet_side).split()[0]
                if side not in (g.home_team, g.away_team):
                    continue
                margin = g.result if side == g.home_team else -g.result
                if str(r.bet_market).upper() == 'SPREAD':
                    try:
                        line = float(str(r.bet_side).split()[1])
                    except (IndexError, ValueError):
                        continue
                    cover = margin + line
                    res = 'W' if cover > 0 else ('P' if cover == 0 else 'L')
                else:
                    res = 'W' if margin > 0 else ('P' if margin == 0 else 'L')
                lean_rows.append(dict(week=week, side=r.bet_side,
                                      market=r.bet_market, result=res))

    if not rows:
        return None

    d = pd.DataFrame(rows)
    d['model_err'] = (d.proj - d.actual).abs()
    d['market_err'] = (d.market - d.actual).abs()
    d['signed_err'] = d.proj - d.actual

    tiers = []
    for lo, hi, name in [(.50, .55, 'coin flip'), (.55, .60, 'slight'),
                         (.60, .65, 'lean'), (.65, .70, 'solid'),
                         (.70, 1.01, 'strong')]:
        s = d[(d.win_prob >= lo) & (d.win_prob < hi)]
        if len(s):
            tiers.append(dict(tier=name, n=len(s), said=float(s.win_prob.mean()),
                              actual=float(s.won.mean())))

    lean = pd.DataFrame(lean_rows)
    lean_rec = dict(n=0, w=0, l=0, p=0)
    if len(lean):
        lean_rec = dict(n=int(len(lean)), w=int((lean.result == 'W').sum()),
                        l=int((lean.result == 'L').sum()),
                        p=int((lean.result == 'P').sum()))

    return dict(season=season, n=len(d), weeks=sorted(d.week.unique().tolist()),
                su_w=int(d.won.sum()), su_l=int((~d.won).sum()),
                su_pct=float(d.won.mean()),
                model_mae=float(d.model_err.mean()),
                market_mae=float(d.market_err.mean()),
                bias=float(d.signed_err.mean()),
                tiers=tiers, leans=lean_rec,
                worst=d.nlargest(5, 'model_err')[
                    ['week', 'pick', 'proj', 'actual', 'market']
                ].to_dict('records'))


# ── systematic error hunt ────────────────────────────────────────────────

def build_history(scope: str) -> pd.DataFrame:
    """Walk-forward predictions to diagnose. Leak-free by construction."""
    df = pd.read_parquet(CACHE_DIR / 'dataset_2010_2025.parquet') \
           .sort_values(['season', 'week']).reset_index(drop=True)
    tuning = json.loads((CACHE_DIR / 'tuning_results.json').read_text())[0]
    params = replace(RATINGS, **{k: v for k, v in tuning.items()
                                 if k in RATINGS.__dataclass_fields__})
    seasons = list(range(2010, 2026)) if scope == 'all' else list(range(2021, 2026))
    bt = walk_forward_adaptive(df, seasons, params=params,
                               qb_lambda=tuning['qb_lambda'], alpha=0.0)
    meta = df[['game_id', 'div_game', 'roof', 'home_rest', 'away_rest',
               'home_qb_name', 'away_qb_name', 'temp', 'wind']]
    return bt.merge(meta, on='game_id', how='left')


def segments(bt: pd.DataFrame) -> list[dict]:
    """Signed error by segment. Positive = model projects the home side too high."""
    bt = bt.copy()
    bt['err'] = bt.projected_margin - bt.result       # signed, home perspective
    bt['edge'] = bt.projected_margin - bt.spread_line
    bt['absline'] = bt.spread_line.abs()

    out = []

    def seg(name, mask):
        s = bt[mask]
        if len(s) < 30:
            return
        t, p = _t_and_p(s.err.to_numpy())
        out.append(dict(segment=name, n=int(len(s)),
                        mean_err=float(s.err.mean()), t=t, p=p))

    seg('all games', bt.index == bt.index)
    seg('home favorite', bt.spread_line < 0)
    seg('home underdog', bt.spread_line > 0)
    seg('pick-em (|line| <= 3)', bt.absline <= 3)
    seg('mid (3 < |line| <= 7)', (bt.absline > 3) & (bt.absline <= 7))
    seg('big (|line| > 7)', bt.absline > 7)
    seg('divisional', bt.div_game == 1)
    seg('non-divisional', bt.div_game == 0)
    seg('dome', bt.roof.isin(['dome', 'closed']))
    seg('outdoors', bt.roof.isin(['outdoors', 'open']))
    seg('week 1-4', bt.week <= 4)
    seg('week 5-12', (bt.week > 4) & (bt.week <= 12))
    seg('week 13+', bt.week > 12)
    seg('model likes home', bt.edge > 0)
    seg('model likes away', bt.edge < 0)
    seg('model disagrees 3+ pts', bt.edge.abs() >= 3)
    seg('short rest home', bt.home_rest <= 4)
    seg('short rest away', bt.away_rest <= 4)
    seg('home off bye', bt.home_rest >= 10)
    seg('away off bye', bt.away_rest >= 10)
    seg('cold (< 32F)', bt.temp < 32)
    seg('windy (>= 15mph)', bt.wind >= 15)

    pvals = [s['p'] for s in out if not np.isnan(s['p'])]
    flags = benjamini_hochberg(pvals, q=0.05)
    it = iter(flags)
    for s in out:
        s['survives_fdr'] = (next(it) if not np.isnan(s['p']) else False)
    return out


# ── output ───────────────────────────────────────────────────────────────

def print_scorecard(sc: dict) -> None:
    print()
    print('=' * 78)
    print(f"  MODEL SCORECARD — {sc['season']}, weeks "
          f"{min(sc['weeks'])}-{max(sc['weeks'])}, {sc['n']} games graded")
    print('=' * 78)
    print()
    print('  PREDICTION ACCURACY  (this is the product)')
    print(f"    straight up            {sc['su_w']}-{sc['su_l']}  "
          f"({sc['su_pct']*100:.1f}%)")
    print(f"    average error          {sc['model_mae']:.2f} pts")
    print(f"    closing line error     {sc['market_mae']:.2f} pts   <-- benchmark")
    delta = sc['model_mae'] - sc['market_mae']
    verdict = 'MODEL IS SHARPER' if delta < 0 else 'market is sharper'
    print(f"    difference             {delta:+.2f} pts   <-- {verdict}")
    print(f"    directional bias       {sc['bias']:+.2f} pts "
          f"({'favors home too much' if sc['bias'] > 0 else 'favors away too much'})")
    print()
    print('  CALIBRATION  (does a stated confidence mean anything?)')
    print(f"    {'tier':<12} {'n':>4} {'said':>8} {'actual':>8}")
    for t in sc['tiers']:
        print(f"    {t['tier']:<12} {t['n']:>4} {t['said']*100:>7.1f}% "
              f"{t['actual']*100:>7.1f}%")
    print()
    lr = sc['leans']
    if lr['n']:
        pct = lr['w'] / (lr['w'] + lr['l']) * 100 if (lr['w'] + lr['l']) else 0
        print(f"  VALUE PICKS            {lr['w']}-{lr['l']}"
              f"{'-' + str(lr['p']) if lr['p'] else ''}  ({pct:.0f}%)")
        print('    these are mostly underdog prices; a low hit rate is their')
        print('    expected shape, not by itself evidence of anything')
        print()
    print('  BIGGEST MISSES')
    for w in sc['worst']:
        print(f"    wk{w['week']} {w['pick']:<4} projected {w['proj']:+5.1f}, "
              f"actual {w['actual']:+5.1f}  (line said {w['market']:+5.1f})")
    print('=' * 78)


def print_segments(segs: list[dict], scope_label: str) -> None:
    print()
    print('=' * 78)
    print(f'  SYSTEMATIC ERROR HUNT — {scope_label}')
    print('=' * 78)
    print('  Is the model biased inside any segment? Positive mean error means')
    print('  it projects the home side too high there.')
    print()
    print(f"    {'segment':<26} {'n':>6} {'mean err':>9} {'t':>7} {'p':>7}  flag")
    print('    ' + '-' * 66)
    for s in segs:
        star = ' **' if s.get('survives_fdr') else ''
        p = '   n/a' if np.isnan(s['p']) else f"{s['p']:>6.3f}"
        t = '   n/a' if np.isnan(s['t']) else f"{s['t']:>6.2f}"
        print(f"    {s['segment']:<26} {s['n']:>6,} {s['mean_err']:>+9.3f} "
              f"{t} {p}{star}")
    print('    ' + '-' * 66)
    n_flag = sum(1 for s in segs if s.get('survives_fdr'))
    print(f'    ** survives Benjamini-Hochberg at FDR 5% '
          f'({n_flag} of {len(segs)} segments)')
    print()
    if n_flag == 0:
        print('  NOTHING SURVIVED. The model has no directional bias in any')
        print('  segment tested that exceeds what chance produces across this')
        print('  many tests. There is no correction here to make.')
    else:
        print('  A segment is flagged. That is a CANDIDATE, not a fix. Next step')
        print('  is IMPROVEMENT.md: state the correction, then test it on seasons')
        print('  where it was not discovered. A bias found in-sample that does not')
        print('  replicate out-of-sample is noise wearing a t-statistic.')
    print('=' * 78)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--season', type=int, default=CURRENT_SEASON)
    ap.add_argument('--diagnose', action='store_true',
                    help='run the systematic error hunt over historical games')
    ap.add_argument('--scope', choices=['holdout', 'all'], default='holdout',
                    help='which seasons the error hunt uses (default: 2021-25)')
    ap.add_argument('--save', action='store_true',
                    help=f'append the scorecard to {SCORECARD}')
    args = ap.parse_args()

    sc = season_scorecard(args.season)
    if sc is None:
        print(f'no graded predictions yet for {args.season}')
    else:
        print_scorecard(sc)
        if args.save:
            hist = json.loads(SCORECARD.read_text()) if SCORECARD.exists() else []
            hist = [h for h in hist if not (h['season'] == sc['season']
                                            and h['weeks'] == sc['weeks'])]
            hist.append(sc)
            SCORECARD.parent.mkdir(exist_ok=True)
            SCORECARD.write_text(json.dumps(hist, indent=2))
            print(f'\n  scorecard saved to {SCORECARD}')

    if args.diagnose:
        label = ('2010-2025, every game' if args.scope == 'all'
                 else '2021-2025 hold-out')
        print(f'\n  building walk-forward history ({label})...', flush=True)
        bt = build_history(args.scope)
        print_segments(segments(bt), label)


if __name__ == '__main__':
    main()
