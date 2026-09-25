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

from nflmodel.config import (ADVISORY_MODE, CURRENT_SEASON, MY_BOOK, OUTPUT_DIR,
                             PARAMS_FILE, RATINGS, SELFTUNE, STAKING,
                             TRAIN_SEASON_START)
from nflmodel.data import build_dataset, load_games
from nflmodel.model import NFLModel
from nflmodel.excel import build_workbook
from nflmodel.ratings import qb_value
from nflmodel.depth import resolve_starters, SOURCE_DEPTH_CHART
from nflmodel.market import format_spread
from nflmodel.report import straight_up_ranking, format_ranking
from nflmodel.archive import archive_week
from nflmodel.teamstats import team_stats_bundle


def load_fitted():
    """Apply backtest-fitted parameters if run_backtest.py has been run."""
    from dataclasses import replace
    if not PARAMS_FILE.exists():
        return RATINGS, 40.0, None
    p = json.loads(PARAMS_FILE.read_text())
    # Only apply keys the grid search actually optimized. Anything else in the
    # file is a stale copy of a config value and must not win over config.py.
    tuned = p.get('tuned_keys') or list(p['ratings'])
    ratings = replace(RATINGS, **{k: v for k, v in p['ratings'].items()
                                  if k in tuned and k in RATINGS.__dataclass_fields__})
    return ratings, p.get('qb_lambda', 40.0), p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--season', type=int, default=CURRENT_SEASON)
    ap.add_argument('--week', type=int, default=None)
    ap.add_argument('--refresh', action='store_true')
    ap.add_argument('--qb', action='append', default=[],
                    metavar='TEAM=Name',
                    help='override the resolved starter, e.g. --qb KC="Patrick Mahomes". '
                         'Repeatable. Beats the depth chart, for news it has not caught up to.')
    ap.add_argument('--no-live-odds', action='store_true',
                    help='skip the live multi-book pull and use the stored '
                         'nflverse line (one book). Live odds are the default: '
                         'the consensus of six books is a better market number '
                         'than any single one, and the best available price is '
                         'worth more than the ratings.')
    ap.add_argument('--no-depth-chart', action='store_true',
                    help='ignore published depth charts and carry the previous starter '
                         'forward instead (the pre-2026 behaviour)')
    ap.add_argument('--starters', action='store_true',
                    help='print the resolved starting quarterback for all 32 teams')
    ap.add_argument('--archive-anyway', action='store_true',
                    help='archive the picks even for a week that has already kicked off. '
                         'Off by default: a replayed week was never published and never '
                         'risked anything, so letting it into picks/ would manufacture a '
                         'track record out of hindsight.')
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

    # A mid-week re-run (after TNF) only re-prices games that have not started.
    # The published pick for a game already played stays exactly as archived.
    today = pd.Timestamp.now().normalize()
    started = slate_games.played.fillna(False).astype(bool) | \
        (pd.to_datetime(slate_games.gameday, errors='coerce') < today)
    if started.any() and not args.archive_anyway:
        gone = slate_games[started]
        print(f'already kicked off, left as published: '
              f"{', '.join(gone.away_team + '@' + gone.home_team)}")
        slate_games = slate_games[~started].copy()
        if slate_games.empty:
            print('every game this week has started')
            return

    # nflverse only fills QB names for PLAYED games, so an upcoming slate has
    # none and the QB term collapses to replacement on both sides, cancelling
    # out. resolve_starters fills it from the published depth chart, falling
    # back to the previous starter and then to any --qb override.
    overrides = {}
    for ov in args.qb:
        if '=' in ov:
            team, name = ov.split('=', 1)
            overrides[team.strip().upper()] = name.strip()

    # nflverse pre-fills the starters for the upcoming week, so the slate
    # usually arrives with them already set. Feed those in as a layer rather
    # than trusting them blindly -- the depth chart is stamped and fresher.
    slate_names = {}
    for _, g in slate_games.iterrows():
        for side in ('home', 'away'):
            nm = g[f'{side}_qb_name']
            if isinstance(nm, str) and nm:
                slate_names[g[f'{side}_team']] = nm

    starters, qb_source, qb_snapshot, qb_notes = resolve_starters(
        hist, games, args.season, week,
        slate_names=slate_names,
        overrides=overrides,
        use_depth_chart=not args.no_depth_chart,
        refresh=args.refresh,
    )

    if qb_snapshot:
        n_dc = sum(1 for v in qb_source.values() if v == SOURCE_DEPTH_CHART)
        print(f'starters: {n_dc}/32 from depth chart published {qb_snapshot}')
        # 2026 Week 1: picks were built Wednesday off that morning's chart and
        # ATL's starter changed before Sunday. Flag a chart that predates the
        # main Sunday slate by more than a day and a half.
        sunday = pd.to_datetime(slate_games.loc[slate_games.weekday == 'Sunday', 'gameday'],
                                errors='coerce').min()
        snap = pd.to_datetime(qb_snapshot, utc=True, errors='coerce')
        if pd.notna(sunday) and pd.notna(snap):
            gap_h = (sunday.tz_localize('UTC') + pd.Timedelta(hours=17) - snap).total_seconds() / 3600
            if gap_h > 36:
                print(f'WARNING: depth chart is {gap_h:.0f}h older than Sunday kickoff. '
                      'Starters can still change (Week 1: ATL). Re-run with --refresh '
                      'Sunday morning before placing bets.')
    elif not args.no_depth_chart:
        print('WARNING: depth charts unavailable — falling back to the game file '
              'and then to carry-forward starters.')

    # Teams whose starter is genuinely in doubt, with the reason. Only these
    # get priced in the QB RISK table below -- listing all 32 teams' backup
    # swing buries the two that matter under thirty that do not.
    qb_uncertain: dict[str, str] = {}

    for team, note in qb_notes:
        print(f'WARNING: {team} — {note}')
        qb_uncertain[team] = 'sources disagree'

    for team in overrides:
        qb_uncertain.setdefault(team, 'set by hand')

    # 2026 Week 2: Kyler Murray was concussed in Week 1 and listed Questionable,
    # but the depth chart still had him QB1 and Wentz's number was never used.
    # The resolver only skips IR/reserve-type statuses, so surface any resolved
    # starter who is on ESPN's injury report. Warning only; never blocks a run.
    try:
        from nflmodel.espn import fetch_injuries
        inj = fetch_injuries(refresh=args.refresh)
        def _norm(n):
            n = str(n).lower().replace('.', '').replace("'", '')
            return ' '.join(w for w in n.split() if w not in ('jr', 'sr', 'ii', 'iii', 'iv'))
        inj = inj[inj.position == 'QB']
        for _, r in inj[inj.status.isin(['Out', 'Doubtful', 'Questionable'])].iterrows():
            if _norm(starters.get(r.team, '')) == _norm(r.player):
                print(f'WARNING: {r.team} starter {r.player} is {r.status} ({r.injury}). '
                      f'If the backup starts, re-run with --qb {r.team}="Backup Name".')
                qb_uncertain[r.team] = f'{r.status} ({r.injury})'
    except Exception as e:
        print(f'WARNING: QB injury check skipped ({e})')

    if args.starters:
        print()
        print(f"  {'team':<6}{'starting QB':<24}source")
        print('  ' + '-' * 46)
        for t in sorted(starters):
            print(f'  {t:<6}{starters[t]:<24}{qb_source.get(t, "—")}')
        print()
        # Listing only. Falling through rebuilt the workbook and re-archived
        # the week without the --qb overrides already published (2026 Week 2).
        return

    # Assign, do not fillna. The game file now arrives already populated, so a
    # fillna silently discarded every resolved starter -- including overrides.
    for side in ('home', 'away'):
        resolved = slate_games[f'{side}_team'].map(starters)
        slate_games[f'{side}_qb_name'] = resolved.fillna(
            slate_games[f'{side}_qb_name'])

    missing = (slate_games['home_qb_name'].isna().sum()
               + slate_games['away_qb_name'].isna().sum())
    if missing:
        print(f'WARNING: {missing} starting QB(s) unknown — those teams use '
              f'replacement level. Override with --qb TEAM="Name".')

    # Live multi-book prices. The consensus becomes the number the model is
    # measured against; the best available price per side rides along for the
    # fill. Falls back to the stored line if the feed is down -- a dead odds
    # source must never take the week down.
    odds_report = {'ok': False, 'reason': 'disabled with --no-live-odds',
                   'source': 'nflverse'}
    if not args.no_live_odds:
        from nflmodel.shop import attach_live_odds
        slate_games, odds_report = attach_live_odds(
            slate_games, args.season, week, book=MY_BOOK)
        if not odds_report['ok']:
            print(f"WARNING: live odds unavailable ({odds_report['reason']}) — "
                  f"falling back to the stored nflverse line (DraftKings only). "
                  f"Line shopping is off for this run.")

    model = NFLModel(params=params, qb_lambda=qb_lambda)
    model.fit(hist, args.season, week, market_games=games)

    # Weekly self-tune: nudge each team by a fraction of how far this season's
    # published projections have missed it. Gentle by design (config.SELFTUNE).
    tune_used = None
    if SELFTUNE.get('alpha', 0) > 0:
        from nflmodel.selftune import live_corrections
        corr, tune_used = live_corrections(
            games, args.season, week, alpha=SELFTUNE['alpha'],
            half_life=SELFTUNE['half_life'], cap=SELFTUNE['cap'],
            resid_clip=SELFTUNE.get('resid_clip'))
        model.team_adjust = corr
        model.max_tune = SELFTUNE.get('max_game_adj')
        print(f"self-tune: alpha {SELFTUNE['alpha']}, max "
              f"{SELFTUNE.get('max_game_adj')} pt/game, from "
              f"{len(tune_used)} graded game(s) this season")

    from nflmodel.config import CACHE_DIR
    rp = CACHE_DIR / 'residuals.npy'
    hist_margins = hist.loc[hist.played & hist.result.notna(), 'result'].to_numpy()
    if rp.exists():
        model.set_residuals(np.load(rp), margins=hist_margins)
        print(f'using empirical residuals (n={len(np.load(rp)):,}) and '
              f'key-number margin distribution (n={len(hist_margins):,})')
    else:
        print('WARNING: no residuals cached — run scripts/run_backtest.py first. '
              'Falling back to a normal approximation, which misprices key numbers.')

    # A quarterback below the min-starts threshold has no parameter of his own
    # and silently becomes replacement level. That is a defensible prior for
    # someone with five career starts, but it is a large, invisible assumption
    # -- replacement sits well below every rated backup -- and it can be what
    # is actually driving a bet. Say so out loud.
    from nflmodel.ratings import REPLACEMENT_QB
    repl = model.qb_ratings.get(REPLACEMENT_QB, 0.0)
    unrated = sorted({
        g[f'{side}_qb_name']
        for _, g in slate_games.iterrows() for side in ('home', 'away')
        if isinstance(g[f'{side}_qb_name'], str)
        and g[f'{side}_qb_name'] not in model.qb_ratings
    })
    for name in unrated:
        team = next((g[f'{s}_team'] for _, g in slate_games.iterrows()
                     for s in ('home', 'away')
                     if g[f'{s}_qb_name'] == name), '?')
        print(f'WARNING: {team} — {name} has too few prior starts to be rated; '
              f'the model is using replacement level ({repl:+.2f} pts). Any bet '
              f'on this game rests on that assumption.')

    slate = model.project_slate(slate_games)

    # Display and explanation columns, joined on game_id so the slate's
    # edge-sorted order is untouched. None of this feeds the projection: the
    # schedule fields come straight from the game file, and components() is
    # the projection's own terms shown unblended so the workbook can say WHY
    # a game is made what it is (team rating, QB, home field, market prior).
    display_cols = ['game_id', 'gameday', 'weekday', 'gametime', 'total_line',
                    'home_spread_odds', 'away_spread_odds', 'over_odds',
                    'under_odds', 'stadium', 'roof', 'neutral',
                    'home_qb_name', 'away_qb_name', 'div_game',
                    # live-odds columns; absent when --no-live-odds or the
                    # feed failed, so every consumer must tolerate missing
                    'stored_spread_line', 'odds_source', 'n_books',
                    'best_home_spread', 'best_home_spread_book',
                    'best_away_spread', 'best_away_spread_book',
                    'best_home_ml', 'best_home_ml_book',
                    'best_away_ml', 'best_away_ml_book']
    slate = slate.merge(
        slate_games[[c for c in display_cols if c in slate_games.columns]],
        on='game_id', how='left')
    parts = pd.DataFrame([dict(game_id=g['game_id'], **model.components(g))
                          for _, g in slate_games.iterrows()])
    slate = slate.merge(parts, on='game_id', how='left')

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
              f"{format_spread(g.home_team, g.fair_spread):>10}"
              f"{format_spread(g.home_team, g.spread_line).split()[1]:>9}"
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

    # ── the bets, split by whether they agree with the model's winner ──
    from nflmodel.model import WITH_PICK, AGAINST_PICK
    active = slate[slate.recommendation.str.match(r'^(LEAN|BET) ')]
    for title, kind, blurb in (
        ("BETS ON THE MODEL'S PICK", WITH_PICK,
         "the team the model expects to win, at a price it likes"),
        ("VALUE BETS AGAINST THE PICK", AGAINST_PICK,
         "the model still expects the OTHER team to win, but thinks this price is too generous"),
    ):
        group = active[active.bet_type == kind]
        print()
        print(f'  {title}  ({blurb})')
        if group.empty:
            print('    none this week')
        for _, g in group.iterrows():
            stake = f'${g.stake:.0f}' if g.stake else '$0'
            print(f"    {g.bet_side:<14} {g.bet_market.lower():<10} {stake:>5}   {g.bet_why}")
    print()

    # ── where to actually place them ──
    if odds_report.get('single_book'):
        print(f"  ALL LINES AND PRICES ABOVE ARE {odds_report['single_book'].upper()}'S.")
        print()
    elif odds_report.get('ok'):
        from nflmodel.shop import shopping_value
        sv = shopping_value(slate)
        if len(sv):
            print('  WHERE TO BET IT  (best of six books — this is worth more '
                  'than the ratings)')
            print(f"    {'bet':<14} {'book':<12} {'best':>8} {'consensus':>10} {'you gain':>10}")
            for _, r in sv.iterrows():
                print(f"    {r.bet:<14} {r.book:<12} {r.best:>8} "
                      f"{r.consensus:>10} {r.gain:>10}")
            print()

    # ── QB risk: which uncertain starters actually move a line ──
    #
    # The largest prediction error of the 2026 season was ATL in Week 2 --
    # projected +0.2, actual -31 -- and the ratings were not at fault: the
    # model had Cooper Rush and Tua Tagovailoa started. A generic "starter is
    # Doubtful" warning did not stop it, because every week has several and
    # they all read the same. This prices them instead, so the two worth a
    # phone call are obvious and the rest can be ignored.
    try:
        from nflmodel.depth import qb_depth_order
        from nflmodel.ratings import qb_value
        order = qb_depth_order(args.season, week, refresh=args.refresh)
        risks = []
        for _, g in slate_games.iterrows():
            for side in ('home', 'away'):
                team = g[f'{side}_team']
                if team not in qb_uncertain:
                    continue
                used = g[f'{side}_qb_name']
                alts = [n for _, n in order.get(team, []) if n != used]
                if not alts:
                    continue
                swing = abs(qb_value(model.qb_ratings, used)
                            - qb_value(model.qb_ratings, alts[0]))
                risks.append((swing, team, used, alts[0],
                              g.away_team + ' @ ' + g.home_team,
                              qb_uncertain[team]))
        risks.sort(reverse=True)
        if risks:
            print('  QB RISK  (only teams whose starter is genuinely in doubt)')
            print(f"    {'team':<6}{'model assumes':<20}{'if instead':<20}"
                  f"{'swing':>7}   why")
            for swing, team, used, alt, game, why in risks:
                print(f"    {team:<6}{str(used):<20}{str(alt):<20}"
                      f"{swing:>6.1f}p   {why}")
            print('    verify these before betting; override with --qb TEAM="Name"')
            print()
    except Exception as e:
        print(f'  [qb risk] skipped ({e})')

    # ── self-tune: what last weeks' misses changed ──
    if 'selftune_adj' in slate.columns and slate.selftune_adj.abs().max() > 0:
        print('  SELF-TUNE  (points added to the home side from recent misses)')
        for _, g in slate.reindex(slate.selftune_adj.abs()
                                  .sort_values(ascending=False).index).iterrows():
            if abs(g.selftune_adj) < 0.05:
                continue
            fav = g.home_team if g.selftune_adj > 0 else g.away_team
            print(f"    {g.away_team + ' @ ' + g.home_team:<14}"
                  f"{g.selftune_adj:+5.1f}  (toward {fav})")
        print()

    # ── straight-up winners, ranked by confidence ──
    ranked = straight_up_ranking(slate)
    print()
    print(format_ranking(ranked))

    # Archive the picks into the repo, not just output/. output/ is gitignored
    # and regenerable; this archive is neither. It is the record of what the
    # model said WHEN IT SAID IT, at the numbers actually available, which is
    # the only thing that can ever settle whether the model is any good. A
    # rebuild later would silently score it against numbers it never saw.
    # It runs BEFORE the workbook so the Bet Log / History sheet can include
    # this week's picks alongside every earlier week's.
    archive_week(ranked, slate, starters, qb_source, args.season, week,
                 force=args.archive_anyway, games=games)

    # Rosters, injuries and records for the Team Stats sheet. Reporting only;
    # nothing here reaches the ratings. A feed outage degrades to an empty
    # sheet with a warning and never blocks the slate.
    print('team stats (rosters, injuries, records)...', flush=True)
    team_stats = team_stats_bundle(games, args.season, week,
                                   ratings=model.power_ratings(),
                                   starters=starters, qb_source=qb_source,
                                   refresh=args.refresh)
    src_ = team_stats.get('sources', {})
    print(f"  rosters: {src_.get('roster', '?')}  injuries: {src_.get('injuries', '?')}")

    # ── workbook ──
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f'NFL_Model_{args.season}_Week{week:02d}.xlsx'
    summary = fitted.get('backtest') if fitted else None
    from nflmodel.market import points_to_prob_table
    model_meta = {
        'hfa': float(model.hfa),
        'market_prior_weight': float(model.market_prior_weight_used),
        'qb_snapshot': qb_snapshot,
        'advisory': bool(ADVISORY_MODE),
        'deployed': fitted.get('deployed') if fitted else None,
        'residual_sd': fitted.get('residual_sd') if fitted else None,
    }
    build_workbook(slate, model.power_ratings(), args.season, week,
                   backtest_summary=summary, path=str(path),
                   pts_table=points_to_prob_table(model.margin_model),
                   ranked=ranked, starters=starters, qb_source=qb_source,
                   team_stats=team_stats, games=games, model_meta=model_meta)
    print(f'\n  workbook: {path}')

    slate.to_csv(OUTPUT_DIR / f'slate_{args.season}_wk{week:02d}.csv', index=False)
    ranked.to_csv(OUTPUT_DIR / f'picks_{args.season}_wk{week:02d}.csv', index=False)


if __name__ == '__main__':
    main()
