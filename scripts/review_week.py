"""
review_week.py — grade last week's picks before making new ones.

Run this FIRST every week. It scores the picks exactly as they were published
(from the tracked picks/ archive, never a rebuild) and tells you the one thing
that actually matters: whether the week's result means anything.

The trap this script exists to defend against:

    A 16-game slate is far too small to tell you anything about a model. A
    good model goes 5-11 straight up regularly. If you tune after a bad week
    you are fitting noise, and you will do it in the direction that felt worst
    -- which is how a working model gets destroyed one reasonable-sounding
    adjustment at a time.

So every number below is printed with the range you would expect from an
unchanged model. If the result sits inside that band, the correct action is to
change nothing at all. That is not an evasion; it is the finding.

What SHOULD trigger a change is a process error -- the wrong starting
quarterback, a stale line, a game the model never saw. Those are real defects
regardless of whether the pick won, and this script hunts for them separately
from the scoreboard.

Run: .venv/bin/python -W ignore scripts/review_week.py [--week N]
"""
import sys, argparse, json
from pathlib import Path
sys.path.insert(0, 'src')
import numpy as np, pandas as pd

from nflmodel.config import CURRENT_SEASON
from nflmodel.data import load_games
from nflmodel.archive import load_archived, lock_week, ARCHIVE_DIR
from nflmodel.history import grade_lean


def band(expected, variance, label, actual, unit=''):
    """Print a result next to the range an unchanged model would produce."""
    sd = np.sqrt(max(variance, 1e-9))
    lo, hi = expected - 1.96 * sd, expected + 1.96 * sd
    z = (actual - expected) / sd if sd > 0 else 0.0
    verdict = 'NOISE' if abs(z) < 1.96 else 'outside expectation'
    print(f'  {label:<30}{actual:>7.1f}{unit}   expected {expected:>5.1f} '
          f'(95% band {lo:>5.1f} to {hi:>5.1f})   z={z:+.2f}  {verdict}')
    return abs(z) >= 1.96


def _grade_bet(b, g):
    """(result, pnl, close_for_side, clv_pts) for one parsed tracker row.

    Scores come from nflverse. When the tracker's Closing Line cell is blank
    the close is filled from nflverse's spread_line (the DraftKings close),
    turned to the bet side's ticket number. Moneyline CLV is left to the
    workbook, which has the closing price; nflverse has no closing ML.
    """
    side = b['bet_side'].split()[0] if b['bet_side'] else ''
    if side not in (g.home_team, g.away_team) or pd.isna(g.result):
        return '', None, None, None
    at_home = side == g.home_team
    margin = g.result if at_home else -g.result
    close = b['closing_line']
    if close is None and pd.notna(g.spread_line):
        close = float(-g.spread_line if at_home else g.spread_line)
    line, clv = b['line_taken'], None
    if b['market'] == 'SPREAD':
        if line is None:
            try:
                line = float(b['bet_side'].split()[1])
            except (IndexError, ValueError):
                return '', None, close, None
        cover = margin + line
        res = 'W' if cover > 0 else ('P' if cover == 0 else 'L')
        clv = line - close if close is not None else None
    elif b['market'] == 'MONEYLINE':
        res = 'W' if margin > 0 else ('P' if margin == 0 else 'L')
    else:
        return '', None, close, None
    stake, odds = b['stake'] or 0.0, b['odds'] or -110.0
    win = stake * (100 / abs(odds) if odds < 0 else odds / 100)
    pnl = win if res == 'W' else (-stake if res == 'L' else 0.0)
    return res, pnl, close, clv


def tracker_review(games, season, week, leans):
    """Grade what Jameson actually logged in the Bet Tracker.

    Reads his tracker exactly as he last saved it -- the most recently saved
    weekly workbook, the same copy the next workbook carries forward. Read
    only: nothing here writes to it.
    """
    from nflmodel.betlog import load_tracker, parse_row
    from nflmodel.history import match_bets
    from nflmodel.config import OUTPUT_DIR

    print()
    print('  YOUR BETS  (from the Bet Tracker)')
    try:
        rows = load_tracker(OUTPUT_DIR, Path('data') / 'bet_log.csv').rows
    except Exception as e:
        print(f'    could not read the tracker ({e})')
        return
    bets = [parse_row(r) for r in rows]

    model_sides = {}
    if leans is not None and not leans.empty:
        for _, l in leans.iterrows():
            model_sides[f'{l.away_team} @ {l.home_team}'] = str(l.bet_side).upper()

    season_g = games[(games.season == season) & games.played & (games.week <= week)]
    tot = {'n': 0, 'w': 0, 'l': 0, 'p': 0, 'stake': 0.0, 'pnl': 0.0, 'clv': []}
    this_week = []
    for _, g in season_g.iterrows():
        matchup = f'{g.away_team} @ {g.home_team}'
        for b in match_bets(bets, season, int(g.week), matchup, g.gameday):
            res, pnl, close, clv = _grade_bet(b, g)
            if not res:
                continue
            tot['n'] += 1
            tot[{'W': 'w', 'L': 'l', 'P': 'p'}[res]] += 1
            tot['stake'] += b['stake'] or 0.0
            tot['pnl'] += pnl
            if clv is not None:
                tot['clv'].append(clv)
            if int(g.week) == week:
                this_week.append((b, g, res, pnl, close, clv))

    if not this_week:
        print(f'    no bets logged for week {week}.')
    else:
        print(f"    {'bet':<18}{'stake':>7}{'result':>8}{'P&L':>9}{'close':>8}{'CLV':>7}  model")
        for b, g, res, pnl, close, clv in this_week:
            ms = model_sides.get(f'{g.away_team} @ {g.home_team}', '')
            follow = ('same side' if ms and ms.split()[0] == b['bet_side'].split()[0]
                      else ('OPPOSITE' if ms else 'no model bet'))
            print(f"    {b['bet_side']:<18}{('$%.0f' % (b['stake'] or 0)):>7}{res:>8}"
                  f"{pnl:>+9.2f}{(f'{close:+.1f}' if close is not None else '—'):>8}"
                  f"{(f'{clv:+.1f}' if clv is not None else '—'):>7}  {follow}")
    if tot['n']:
        roi = tot['pnl'] / tot['stake'] if tot['stake'] else 0.0
        clv = (f"avg CLV {np.mean(tot['clv']):+.2f} pts on {len(tot['clv'])}"
               if tot['clv'] else 'no CLV yet')
        print(f"    season to date: {tot['w']}-{tot['l']}-{tot['p']}, "
              f"P&L ${tot['pnl']:+,.2f} ({roi:+.1%} ROI), {clv}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--season', type=int, default=CURRENT_SEASON)
    ap.add_argument('--week', type=int, default=None,
                    help='week to grade (default: the most recent completed week)')
    args = ap.parse_args()

    games = load_games()
    season = games[games.season == args.season]

    if args.week is None:
        played = season[season.played]
        if played.empty:
            print(f'no completed games in {args.season} yet — nothing to review.')
            print('Run scripts/run_week.py to publish this week\'s picks.')
            return
        week = int(played.week.max())
    else:
        week = args.week

    picks, leans = load_archived(args.season, week)
    if picks is None:
        print(f'no archived picks for {args.season} week {week}.')
        print(f'Nothing was published that week, so there is nothing to grade —')
        print(f'expected at {ARCHIVE_DIR}/{args.season}/week{week:02d}_picks.csv')
        return

    wk = season[(season.week == week) & season.played]
    if wk.empty:
        print(f'{args.season} week {week} has not been played yet.')
        return

    # Score straight-up picks against the actual results.
    res = {}
    for _, g in wk.iterrows():
        if pd.isna(g.result) or g.result == 0:
            continue
        res[(g.home_team, g.away_team)] = g.home_team if g.result > 0 else g.away_team

    rows = []
    for _, p in picks.iterrows():
        key = (p.loser, p.winner) if not p.at_home else (p.winner, p.loser)
        actual = res.get(key)
        if actual is None:
            continue
        rows.append({'pick': p.winner, 'won': actual == p.winner,
                     'prob': float(p.win_prob), 'tier': p.confidence,
                     'matchup': p.matchup})
    d = pd.DataFrame(rows)

    print('=' * 78)
    print(f'  REVIEW — {args.season} WEEK {week}'.ljust(78))
    print('=' * 78)

    if d.empty:
        print('  no scoreable games (ties or missing results).')
        return

    correct = int(d.won.sum())
    exp = float(d.prob.sum())
    var = float((d.prob * (1 - d.prob)).sum())
    print(f'  {len(d)} games graded\n')
    print('  STRAIGHT UP')
    flag_su = band(exp, var, 'correct picks', correct)

    # Calibration: does 60% actually mean 60%? This converges much faster than
    # a win rate does, which is why it is worth reading after one week.
    print()
    print('  CALIBRATION BY TIER  (does the stated confidence mean anything?)')
    print(f"  {'tier':<14}{'n':>4}{'said':>8}{'actual':>9}{'band':>18}")
    for tier in ['strong', 'solid', 'lean', 'slight', 'coin flip']:
        t = d[d.tier == tier]
        if t.empty:
            continue
        e, v = t.prob.sum(), (t.prob * (1 - t.prob)).sum()
        sd = np.sqrt(max(v, 1e-9))
        print(f'  {tier:<14}{len(t):>4}{t.prob.mean():>7.1%}{t.won.mean():>9.1%}'
              f'{f"{max(0,e-1.96*sd):.1f}-{min(len(t),e+1.96*sd):.1f} of {len(t)}":>18}')

    # Leans are the only picks that would have cost money.
    if leans is not None and not leans.empty:
        print()
        print('  LEANS  (where the model disagreed with a price)')
        graded = wins = pushes = 0
        for _, l in leans.iterrows():
            g = wk[(wk.home_team == l.home_team) & (wk.away_team == l.away_team)]
            if g.empty or pd.isna(g.iloc[0].result):
                continue
            # Same grading as the workbook's Bet Log: landing exactly on the
            # number is a PUSH (stake returned), not a loss.
            res = grade_lean(l, g.iloc[0])
            if not res:
                continue
            graded += 1
            wins += res == 'WIN'
            pushes += res == 'PUSH'
            print(f'    {str(l.bet_side):<16}{res if res != "LOSS" else "loss"}')
        decided = graded - pushes
        if decided:
            push_txt = f'-{pushes}' if pushes else ''
            print(f'    record {wins}-{decided - wins}{push_txt} ({wins/decided:.0%} of decided)')
            print(f'    a coin flip on {graded} picks lands anywhere from '
                  f'{max(0, int(graded/2 - 1.96*np.sqrt(graded)/2))} to '
                  f'{int(graded/2 + 1.96*np.sqrt(graded)/2)} wins')

    tracker_review(games, args.season, week, leans)

    # Process errors are real defects whether or not the picks won.
    print()
    print('  PROCESS CHECK  (these are worth fixing regardless of the scoreboard)')
    meta_path = ARCHIVE_DIR / str(args.season) / f'week{week:02d}_meta.json'
    problems = []
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        assumed = meta.get('starters', {})
        for _, g in wk.iterrows():
            for side in ('home', 'away'):
                team, actual_qb = g[f'{side}_team'], g[f'{side}_qb_name']
                if isinstance(actual_qb, str) and team in assumed:
                    if assumed[team] != actual_qb:
                        problems.append(f'{team}: assumed {assumed[team]}, '
                                        f'actually started {actual_qb}')
    missing = len(wk) - len(d)
    if missing:
        problems.append(f'{missing} played game(s) had no archived pick')
    if problems:
        for p in problems:
            print(f'    WRONG INPUT — {p}')
    else:
        print('    no input errors: every starter and game matched what was assumed')

    print()
    print('=' * 78)
    print('  WHAT TO DO')
    print('=' * 78)
    if problems:
        print('  Fix the input errors above. Those are defects in the pipeline,')
        print('  not in the ratings, and they are worth fixing immediately.')
    if flag_su:
        print('  The straight-up result fell outside the 95% band. That is worth')
        print('  a look — but ONE week outside a 95% band happens 1 time in 20')
        print('  by chance, so check for a leak or a bad input before concluding')
        print('  the model is wrong.')
    if not problems and not flag_su:
        print('  Nothing here justifies a model change. The result is inside the')
        print('  range an unchanged model produces. Do not tune on it.')
    print()
    print('  Reminder on sample size: at a true 53% ATS rate it takes roughly')
    print('  1,100 bets for the win rate to separate from 50% at 95% confidence.')
    print('  At ~9 leans a week that is over six seasons. Weekly win/loss records')
    print('  will never settle whether this model works. CLV will, in about six')
    print('  weeks — that is what the Bet Tracker is for.')
    print('=' * 78)

    lock_week(args.season, week)
    print(f'\n  week {week} locked — its picks can no longer be rewritten.')


if __name__ == '__main__':
    main()
