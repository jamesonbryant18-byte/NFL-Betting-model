"""
miss_report.py — why is the model missing, and what should it correct?

Run every week after the week is graded (review_week.py), BEFORE building
the next week. It re-checks every candidate reason against all graded games
(2013 onward plus this season's published picks), prints what it found, and
writes the model's learned state to data/trends.json -- which run_week.py
applies and which is tracked in git.

    .venv/bin/python -W ignore scripts/miss_report.py
    .venv/bin/python -W ignore scripts/miss_report.py --no-save   # look only

The rule (Jameson, 2026-09-25): fix the model when a REASON keeps causing
misses, never because of one game. See src/nflmodel/trends.py.
"""
import argparse
import json
import sys

sys.path.insert(0, 'src')

from nflmodel.config import CURRENT_SEASON
from nflmodel import trends

STATUS = {"confirmed": "FIXED", "watching": "watch", "absorbed": "covered",
          "rejected": "failed", "no pattern": "-"}


def fmt(v, spec="+.1f"):
    return "  n/a" if v is None else format(v, spec)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--season', type=int, default=CURRENT_SEASON)
    ap.add_argument('--no-save', action='store_true', help='print only; do not update data/trends.json')
    args = ap.parse_args()

    before = trends.load_active()
    state = trends.run_all(args.season)
    h = state['history']

    print()
    print('=' * 78)
    print(f"  MISS REPORT — {h['n_games']:,} graded games, {h['first_season']}-{h['last_season']}"
          f" ({h['current_season_graded']} from this season)")
    print('=' * 78)
    print('  A reason is FIXED only if it shows up in 2013-2020 AND again in 2021+.')
    print('  Effects are points vs the projection, for the team the reason is about.')
    print()
    print(f"  {'reason':<56}{'13-20':>7}{'21+':>7}{'now':>6}  status")
    print('  ' + '-' * 76)
    order = {"confirmed": 0, "absorbed": 1, "watching": 2, "rejected": 3, "no pattern": 4}
    for r in sorted(state['margin_trends'], key=lambda r: order.get(r['status'], 9)):
        fix = f" {r['live_shift']:+.1f}" if r['status'] == 'confirmed' else ''
        print(f"  {r['text']:<56}{fmt(r['effect_disc']):>7}{fmt(r['effect_conf']):>7}"
              f"{r['n_season']:>6}  {STATUS.get(r['status'], r['status'])}{fix}")
    j = state['joint']
    print('  ' + '-' * 76)
    print(f"  together, fit on 2013-2020 and tested on 2021+: average miss "
          f"{j['conf_mae_before']:.2f} -> {j['conf_mae_after']:.2f} pts ({j['status']})")

    c = state['calibration']
    print()
    print('  LONGSHOTS — how often underdogs actually won')
    print(f"    {'':<10}{'price':<15}{'games':>6}{'won':>7}{'market':>8}{'model':>7}"
          f"{'+margin':>8}{'+calib':>7}")
    for t in c['table']:
        print(f"    {t['block']:<10}{t['bucket']:<15}{t['n']:>6}{t['actual']:>7.1%}"
              f"{t['market']:>8.1%}{t['model']:>7.1%}{t['model_margin_fixed']:>8.1%}"
              f"{t['model_fixed']:>7.1%}")
    ll = c['conf_logloss']
    z = c.get('tail_overrated_z', {})
    print(f"    dogs +151 and longer overrated by the model: "
          + ", ".join(f"{k} z={v:+.1f}" for k, v in z.items()))
    print(f"    win-% recalibration: {c['status']} (2021+ log loss {ll['raw']:.4f} raw, "
          f"{ll['margin_fixed']:.4f} margin-fixed, {ll['fixed']:.4f} recalibrated)")

    print()
    print('  BETS THE MODEL MAKES (replayed on every game, 1 unit each)')
    for label, key in (('before fixes', 'bets_before'), ('after fixes', 'bets_after')):
        for blk, b in state[key].items():
            print(f"    {label:<13}{blk:<10} {b['n']:>5} bets, {b['underdog_share']:.0%} on underdogs, "
                  f"{b['ml_longshots']:>3} moneylines longer than +250, return {b['roi']:+.1%}")

    flagged = [b for b in state['bet_types'] if b['status'] != 'no pattern']
    if flagged:
        print('    bet types losing more than the rest in both periods:')
        for b in flagged:
            print(f"      {b['group']:<38} {b['roi_disc']:+.0%} / {b['roi_conf']:+.0%}  ({b['status']})")

    if state['misses']:
        print()
        print("  THIS SEASON'S MISSES (picked the wrong winner)")
        for m in state['misses']:
            print(f"    wk{m['week']} {m['matchup']:<11} picked {m['pick']:<4} "
                  f"proj {m['projected']:+5.1f}  actual {m['actual']:+5.0f}   {m['luck']}")

    # What changed since the last check
    now = {r['key'] for r in state['margin_trends'] if r['status'] == 'confirmed'}
    was = {r['key'] for r in (before.get('margin') or [])}
    print()
    if before:
        added, dropped = now - was, was - now
        if added or dropped:
            for k in sorted(added):
                print(f"  NEW FIX: {trends.CANDIDATE_TEXT[k]}")
            for k in sorted(dropped):
                print(f"  FIX REMOVED (no longer consistent): {trends.CANDIDATE_TEXT[k]}")
        else:
            print('  No change to the fixes since the last check.')
    print('=' * 78)

    if not args.no_save:
        trends.save(state)
        print(f'  saved {trends.TRENDS_FILE.relative_to(trends.REPO_ROOT)} — run_week.py applies it. '
              f'Commit it: it is the model\'s learned state.')


if __name__ == '__main__':
    main()
