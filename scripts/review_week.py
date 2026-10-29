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
from nflmodel.closing import (record_closing, load_closing, close_for, side_close,
                              card_clv, summarize_clv)
from nflmodel.market import closing_line_value
from nflmodel.teamstats import normalize_name
from nflmodel.scorecard import (straight_up, summarize_straight_up, model_bets,
                                summarize_bets)


def _fmt_close(market, close):
    if close is None:
        return '—'
    return f'{close:+.1f}' if market == 'SPREAD' else f'{close:+.0f}'


def _fmt_clv(market, clv):
    if clv is None:
        return '—'
    return f'{clv:+.1f}' if market == 'SPREAD' else f'{clv:+.1%}'


def band(expected, variance, label, actual, unit=''):
    """Print a result next to the range an unchanged model would produce."""
    sd = np.sqrt(max(variance, 1e-9))
    lo, hi = expected - 1.96 * sd, expected + 1.96 * sd
    z = (actual - expected) / sd if sd > 0 else 0.0
    verdict = 'NOISE' if abs(z) < 1.96 else 'outside expectation'
    print(f'  {label:<30}{actual:>7.1f}{unit}   expected {expected:>5.1f} '
          f'(95% band {lo:>5.1f} to {hi:>5.1f})   z={z:+.2f}  {verdict}')
    return abs(z) >= 1.96


def _grade_bet(b, g, close_row=None):
    """(result, pnl, close_for_side, clv) for one parsed tracker row.

    Scores come from nflverse. The close is what he typed in the tracker if
    he typed one; otherwise the recorded closing line for the game
    (picks/{season}/weekNN_closing.csv, FanDuel first), and failing that
    nflverse's DraftKings close. clv is in points for a spread and in
    implied-probability points for a moneyline.
    """
    side = b['bet_side'].split()[0] if b['bet_side'] else ''
    if side not in (g.home_team, g.away_team) or pd.isna(g.result):
        return '', None, None, None
    at_home = side == g.home_team
    margin = g.result if at_home else -g.result
    close = b['closing_line']
    if close is None:
        close = side_close(close_row, 'SPREAD', side)
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
        close = b['closing_odds'] if b['closing_odds'] is not None \
            else side_close(close_row, 'MONEYLINE', side)
        if close is not None and b['odds'] is not None:
            clv = closing_line_value(b['odds'], close)
    else:
        return '', None, close, None
    stake, odds = b['stake'] or 0.0, b['odds'] or -110.0
    win = stake * (100 / abs(odds) if odds < 0 else odds / 100)
    pnl = win if res == 'W' else (-stake if res == 'L' else 0.0)
    return res, pnl, close, clv


def clv_review(season, week):
    """Closing line value of the model's card: this week, then the season."""
    print()
    print("  CLOSING LINE VALUE  (the model's bets vs the closing number; + = beat it;")
    print("                       moneylines in de-vigged win %)")
    this = card_clv(season, week)
    if this.empty:
        print('    no closing lines recorded for this week')
        return
    print(f"    measured from the {this.card_source.iloc[0]} number")
    for _, r in this.iterrows():
        print(f"    {r.bet_side:<16}{'took':>5} {_fmt_close(r.market, r.taken):>6}"
              f"   close {_fmt_close(r.market, r.close):>6}"
              f"   CLV {_fmt_clv(r.market, r.clv_pts if r.market == 'SPREAD' else r.clv_prob):>6}"
              + ('' if r.source is None or 'fanduel' in str(r.source).lower()
                 else f"   (close from {str(r.source).split()[0]}, not FanDuel)"))
    season_rows = pd.concat([card_clv(season, w) for w in range(1, week + 1)],
                            ignore_index=True)
    s = summarize_clv(season_rows)
    for name, unit in (('spread', 'pts'), ('moneyline', '')):
        x = s[name]
        if x['n']:
            avg = f"{x['avg']:+.2f} pts" if unit else f"{x['avg']:+.1%}"
            print(f"    season, {name}s: {x['n']} bets, avg CLV {avg}, beat the close "
                  f"{x['beat']}, matched {x['same']}, worse {x['worse']}")
    print('    CLV near zero = the model is not beating the market; consistently')
    print('    positive over 40-50 bets is the first real evidence of an edge.')


def favorite_review(games, season, week):
    """
    Straight up against simply taking the favorite (expert review 2026-10-29).
    The model only beats the favorite on the games where it picks against it,
    so those are listed with why each loss happened.
    """
    su = straight_up(season, range(1, week + 1), games)
    if su.empty:
        return
    print()
    print('  VS THE FAVORITE  (would taking every favorite have done as well?)')
    for label, x in ((f'week {week}', su[su.week == week]), ('season', su)):
        s = summarize_straight_up(x)
        if not s.get('n'):
            continue
        close = (f"{s['fav_close']}-{s['n_close'] - s['fav_close']}" if s['n_close'] == s['n']
                 else f"{s['fav_close']} of {s['n_close']}")
        print(f"    {label:<8} model {s['model']}-{s['n'] - s['model']},  favorite at publication "
              f"{s['fav_pub']}-{s['n'] - s['fav_pub']},  at the close {close}")
    s = summarize_straight_up(su)
    gap, noise = s['diff_per_game'] * s['n'], 1.96 * s['diff_se'] * s['n']
    print(f"    season: model {gap:+.0f} picks vs the favorite"
          + (f" (anything inside +/-{noise:.0f} is noise)" if noise == noise else ''))
    print(f"    expected wins: {s['expected_model']:.1f} by the model's own odds, "
          f"{s['expected_market']:.1f} by FanDuel's closing odds ({s['n_market']} games); "
          f"actual {s['model']}")
    print(f"    picks against the favorite this season: {s['against_won']}-"
          f"{s['against'] - s['against_won']}")
    wk = su[(su.week == week) & su.against_pub]
    if wk.empty:
        return
    try:
        from nflmodel.trends import miss_luck, pbp_team_stats
        st = pbp_team_stats([season]).set_index(['game_id', 'team'])
    except Exception:                                        # noqa: BLE001
        miss_luck, st = None, None
    for _, r in wk.iterrows():
        why = ''
        if not r.model_right and miss_luck is not None:
            why = miss_luck(st, r.game_id, r.pick, r.opp)
        print(f"      {r.matchup:<14} picked {r.pick} ({r.said:.0%}) over favorite {r.fav_pub}: "
              f"{'RIGHT' if r.model_right else 'wrong'}{'  -- ' + why if why else ''}")


def bets_review(games, season, week):
    """
    The model's own bets (the archive / Bet Log, never his tracker): good or
    lucky? Record vs break-even, vs what the model expected, vs what the
    closing market expected, and the value at the price taken -- the expected
    return if FanDuel's de-vigged close is the truth. Luck moves the record;
    it cannot move the value at the price taken.
    """
    from nflmodel.trends import margin_model_for_history
    b = model_bets(season, range(1, week + 1), games, margin_model_for_history())
    if b.empty:
        return
    print()
    print("  THE MODEL'S BETS: GOOD OR LUCKY?  (its published card, graded at FanDuel's close)")
    for label, x in ((f'week {week}', b[b.week == week]), ('season', b)):
        s = summarize_bets(x)
        if not s.get('n'):
            continue
        push = f"-{s['push']}" if s['push'] else ''
        print(f"    {label:<8} {s['won']}-{s['lost']}{push}, {s['units']:+.2f} units "
              f"({s['roi']:+.1%} a bet), won {s['win_pct']:.0%} vs break-even {s['break_even']:.0%}")
        print(f"             expected wins: {s['expected_model']:.1f} by the model, "
              f"{s['expected_close']:.1f} +/- {s['expected_close_sd']:.1f} by the closing market; "
              f"value at the price taken {s['value']:+.1%} a bet"
              + (f" (+/- {1.96 * s['value_se']:.1%})" if s['value_se'] == s['value_se'] else ''))
    s = summarize_bets(b)
    if s['not_fanduel']:
        print(f"    {s['not_fanduel']} close(s) not from FanDuel (flagged; FanDuel's was not recorded)")
    verdict = ('the prices it took were WORSE than the close: the record is running ahead of the bets'
               if s['value'] + 1.96 * s['value_se'] < 0 else
               'the prices it took BEAT the close: that is what a real edge looks like'
               if s['value'] - 1.96 * s['value_se'] > 0 else
               'value at the price taken is not clearly different from zero yet')
    print(f"    season verdict: {verdict}")
    wk = b[b.week == week]
    if len(wk):
        print(f"    {'bet':<16}{'price':>7}{'result':>8}{'model':>8}{'close':>8}{'value':>8}")
        for _, r in wk.iterrows():
            val = '' if pd.isna(r.value_at_close) else f'{r.value_at_close:+.1%}'
            pc = '' if pd.isna(r.p_close) else f'{r.p_close:.0%}'
            flag = '  (not FanDuel)' if r.not_fanduel else ''
            print(f"    {r.bet:<16}{r.odds:>+7.0f}{r.out:>8}{r.p_model:>8.0%}{pc:>8}{val:>8}{flag}")


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
    tot = {'n': 0, 'w': 0, 'l': 0, 'p': 0, 'stake': 0.0, 'pnl': 0.0,
           'clv': [], 'clv_ml': []}
    this_week = []
    closes = {}
    for _, g in season_g.iterrows():
        matchup = f'{g.away_team} @ {g.home_team}'
        wk_ = int(g.week)
        if wk_ not in closes:
            closes[wk_] = load_closing(season, wk_)
        close_row = close_for(closes[wk_], g.home_team, g.away_team)
        for b in match_bets(bets, season, wk_, matchup, g.gameday):
            res, pnl, close, clv = _grade_bet(b, g, close_row)
            if not res:
                continue
            tot['n'] += 1
            tot[{'W': 'w', 'L': 'l', 'P': 'p'}[res]] += 1
            tot['stake'] += b['stake'] or 0.0
            tot['pnl'] += pnl
            if clv is not None:
                tot['clv' if b['market'] == 'SPREAD' else 'clv_ml'].append(clv)
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
                  f"{pnl:>+9.2f}{_fmt_close(b['market'], close):>8}"
                  f"{_fmt_clv(b['market'], clv):>7}  {follow}")
    if tot['n']:
        roi = tot['pnl'] / tot['stake'] if tot['stake'] else 0.0
        parts = []
        if tot['clv']:
            parts.append(f"spread CLV {np.mean(tot['clv']):+.2f} pts avg on {len(tot['clv'])}, "
                         f"beat the close {sum(c > 0 for c in tot['clv'])}")
        if tot['clv_ml']:
            parts.append(f"moneyline CLV {np.mean(tot['clv_ml']):+.1%} avg on {len(tot['clv_ml'])}, "
                         f"beat the close {sum(c > 0 for c in tot['clv_ml'])}")
        clv = '; '.join(parts) if parts else 'no CLV yet' 
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

    # The week's closing lines, recorded once all its games are final.
    closing = record_closing(args.season, week, games)
    if closing is not None:
        src = closing.close_source.str.split().str[0].value_counts()
        print(f"  closing lines: {len(closing)} games recorded "
              f"({', '.join(f'{n} {b}' for b, n in src.items())}) -> "
              f"picks/{args.season}/week{week:02d}_closing.csv")
    else:
        print('  closing lines: not recorded yet (week not final)')

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

    favorite_review(games, args.season, week)
    bets_review(games, args.season, week)
    clv_review(args.season, week)
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
                    # 'Michael Penix' vs 'Michael Penix Jr.' is the same QB
                    # (2026 Week 7 flagged it as a wrong input).
                    if normalize_name(assumed[team]) != normalize_name(actual_qb):
                        problems.append(f'{team}: assumed {assumed[team]}, '
                                        f'actually started {actual_qb}')
    # A tie has no straight-up winner, so it is never in `d`; that is not a
    # missing pick (2026 Week 5, NYG @ WAS 27-27, was reported as one).
    archived = {(p.loser, p.winner) if not p.at_home else (p.winner, p.loser)
                for _, p in picks.iterrows()}
    missing = sum((g.home_team, g.away_team) not in archived for _, g in wk.iterrows())
    if missing:
        problems.append(f'{missing} played game(s) had no archived pick')
    ties = [f'{g.away_team} @ {g.home_team}' for _, g in wk.iterrows() if g.result == 0]
    if ties:
        print(f"    tie, no straight-up winner to grade: {', '.join(ties)}")
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
    print('  weeks: the CLOSING LINE VALUE section above, recorded every Wednesday.')
    print('=' * 78)

    lock_week(args.season, week)
    print(f'\n  week {week} locked — its picks can no longer be rewritten.')


if __name__ == '__main__':
    main()
