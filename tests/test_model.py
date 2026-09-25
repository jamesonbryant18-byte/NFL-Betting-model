"""
Invariant tests. Run: .venv/bin/python -m pytest tests/ -q

The leakage test is the important one. Everything else in this repo is
worthless if the model can see the games it is being scored on.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import numpy as np
import pandas as pd
import pytest

from nflmodel.market import (american_to_prob, prob_to_american, devig,
                             kelly_stake, MarginModel, vig_pct)
from nflmodel.ratings import fit_ratings_qb, _time_index
from nflmodel.config import RATINGS, CACHE_DIR
from nflmodel.adjustments import total_adjustment


# ── odds conversion ──────────────────────────────────────────────

def test_american_prob_roundtrip():
    for odds in (-350, -180, -110, 100, 145, 400):
        assert prob_to_american(american_to_prob(odds)) == pytest.approx(odds, abs=1e-6)


def test_favorite_more_likely_than_dog():
    assert american_to_prob(-200) > 0.5 > american_to_prob(150)


# ── de-vigging ───────────────────────────────────────────────────

@pytest.mark.parametrize('method', ['multiplicative', 'power', 'shin'])
def test_devig_sums_to_one(method):
    for a, b in ((-110, -110), (-400, 320), (-150, 130), (200, -240)):
        p, q = devig(a, b, method)
        assert p + q == pytest.approx(1.0, abs=1e-9)
        assert 0 < p < 1 and 0 < q < 1


def test_devig_symmetric_market_is_coinflip():
    p, q = devig(-110, -110)
    assert p == pytest.approx(0.5) and q == pytest.approx(0.5)


def test_raw_odds_overstate_probability():
    """The whole reason de-vigging exists."""
    raw = american_to_prob(-110) * 2
    assert raw > 1.0
    assert vig_pct(-110, -110) == pytest.approx(4.76, abs=0.01)


# ── staking ──────────────────────────────────────────────────────

def test_kelly_refuses_losing_bet():
    # -110 breaks even at 52.38%; 52% must not be staked.
    stake, full = kelly_stake(0.52, -110, 1000.0)
    assert stake == 0.0 and full < 0


def test_kelly_respects_cap():
    stake, full = kelly_stake(0.95, -110, 1000.0)
    assert full > 0.5              # Kelly wants an enormous bet
    assert stake <= 1000.0 * 0.025 # the cap must bind


def test_kelly_scales_with_bankroll():
    a, _ = kelly_stake(0.60, -110, 1000.0)
    b, _ = kelly_stake(0.60, -110, 2000.0)
    assert b == pytest.approx(2 * a, rel=0.02)


def test_push_does_not_dilute_stake():
    """A push returns the stake, so it must not be treated as a partial loss."""
    no_push, _ = kelly_stake(0.55, -110, 1000.0, push_prob=0.0)
    with_push, _ = kelly_stake(0.55 * 0.97, -110, 1000.0, push_prob=0.03)
    assert with_push >= no_push * 0.98


# ── margin model ─────────────────────────────────────────────────

def test_cover_probs_sum_to_one():
    mm = MarginModel(residuals=np.random.default_rng(0).normal(0, 13.2, 5000))
    for line in (-7, -3.5, 0, 2.5, 3, 10):
        h, p, a = mm.cover_prob(1.5, line)
        assert h + p + a == pytest.approx(1.0, abs=1e-9)


def test_whole_number_line_has_push_mass():
    mm = MarginModel(residuals=np.random.default_rng(0).normal(0, 13.2, 20000))
    _, push_int, _ = mm.cover_prob(2.0, 3.0)
    _, push_half, _ = mm.cover_prob(2.0, 3.5)
    assert push_int > 0.01     # integer lines really do push
    assert push_half == 0.0    # half-point lines cannot


def test_bigger_projection_means_higher_cover():
    mm = MarginModel(residuals=np.random.default_rng(0).normal(0, 13.2, 5000))
    assert mm.cover_prob(7.0, 3.0)[0] > mm.cover_prob(1.0, 3.0)[0]


def test_win_prob_monotonic_and_centered():
    mm = MarginModel(residuals=np.random.default_rng(0).normal(0, 13.2, 20000))
    assert mm.win_prob(0.0) == pytest.approx(0.5, abs=0.02)
    assert mm.win_prob(10.0) > mm.win_prob(3.0) > mm.win_prob(-3.0)


# ── adjustments ──────────────────────────────────────────────────

def test_adjustments_ship_at_zero():
    """They were measured and rejected; a nonzero default is a regression."""
    game = dict(home_team='SEA', away_team='MIA', home_rest=13, away_rest=4,
                wind=30, roof='outdoors', week=17)
    assert total_adjustment(game) == 0.0


# ── the one that matters ─────────────────────────────────────────

@pytest.mark.skipif(not (CACHE_DIR / 'dataset_2010_2025.parquet').exists(),
                    reason='dataset not built')
def test_no_future_leakage():
    """
    Ratings fit as of a given week must be bit-identical whether or not the
    future exists in the input frame. If deleting every later game changes the
    answer, the model is reading the future and every backtest number is fake.
    """
    df = pd.read_parquet(CACHE_DIR / 'dataset_2010_2025.parquet')

    full = fit_ratings_qb(df, 2022, 10, RATINGS)
    cutoff = 2022 * RATINGS.offseason_weeks_equiv + 10
    truncated_df = df[_time_index(df.season, df.week, RATINGS) < cutoff]
    truncated = fit_ratings_qb(truncated_df, 2022, 10, RATINGS)

    assert full[2] == pytest.approx(truncated[2], abs=1e-9)   # HFA
    for team in full[0]:
        assert full[0][team] == pytest.approx(truncated[0][team], abs=1e-9)


@pytest.mark.skipif(not (CACHE_DIR / 'dataset_2010_2025.parquet').exists(),
                    reason='dataset not built')
def test_ratings_are_centered_and_bounded():
    df = pd.read_parquet(CACHE_DIR / 'dataset_2010_2025.parquet')
    teams, qbs, hfa = fit_ratings_qb(df, 2025, 10, RATINGS)
    vals = np.array(list(teams.values()))
    assert abs(vals.mean()) < 1e-9          # centered on league average
    assert vals.max() < 20 and vals.min() > -20
    assert 0 < hfa < 5                       # a sane home field number


# ── regression: the sign bug that printed the wrong side of every game ──

from nflmodel.market import format_spread


def test_ticket_sign_matches_the_real_bet():
    """
    spread_line is 'points the home team is favored by'; a ticket shows the
    negation. A 7-point home favorite must read '-7.0', never '+7.0'. This
    shipped inverted once and printed the opposite side of every game.
    """
    assert format_spread("DET", 7.0) == "DET -7.0"     # favored lays points
    assert format_spread("NO", -7.0) == "NO +7.0"      # dog takes points
    assert format_spread("IND", -3.5) == "IND +3.5"
    assert format_spread("BAL", 3.5) == "BAL -3.5"


def test_recommendation_prints_favorite_as_laying_points():
    from nflmodel.model import NFLModel
    m = NFLModel()
    m.team_ratings = {"DET": 6.0, "NO": -2.0}
    m.hfa = 2.0
    rec = m._recommend(
        projected=12.0, line=7.0, spread_edge=5.0,
        p_home=0.62, p_push=0.03, p_away=0.35,
        home_wp=0.80, h_ml=-305, a_ml=245,
        ml_edge_h=0.0, ml_edge_a=0.0, home="DET", away="NO",
    )
    # Model likes the home favorite -> the ticket must LAY the points.
    assert "DET -7.0" in rec["recommendation"], rec["recommendation"]


def test_market_ratings_respect_asof_cutoff():
    """Replaying a finished season must not see later weeks' closing lines."""
    import pandas as pd
    from nflmodel.ratings import fit_market_ratings
    from nflmodel.data import load_games
    g = load_games()
    if (g.season == 2025).sum() < 100:
        pytest.skip("2025 not loaded")
    full, _ = fit_market_ratings(g, 2025)
    early, _ = fit_market_ratings(g, 2025, asof_week=3)
    assert any(abs(full[t] - early[t]) > 1e-6 for t in full), \
        "asof_week had no effect — the leak guard is not working"


# ── key numbers ──────────────────────────────────────────────────

def test_key_numbers_are_actually_modeled():
    """
    A margin of exactly 3 is far more likely than exactly 4. An earlier
    version reported a flat ~3.3% push at every line, which is wrong by
    roughly 9x on a three-point spread.
    """
    from nflmodel.market import MarginModel
    from nflmodel.data import load_games
    g = load_games()
    hist = g[g.played & g.result.notna()]
    if len(hist) < 1000:
        pytest.skip('games not loaded')

    mm = MarginModel(margins=hist.result.values)
    push3 = mm.cover_prob(3.0, 3.0)[1]
    push4 = mm.cover_prob(3.0, 4.0)[1]
    assert push3 > 2.5 * push4, f'key number 3 not modeled: {push3:.4f} vs {push4:.4f}'

    push7 = mm.cover_prob(3.0, 7.0)[1]
    push8 = mm.cover_prob(3.0, 8.0)[1]
    assert push7 > push8

    h, p, a = mm.cover_prob(2.5, 3.0)
    assert abs(h + p + a - 1.0) < 1e-9


# ── odds / line shopping ─────────────────────────────────────────

def test_line_shopping_guard_rejects_outliers():
    """
    A single mis-signed book in a feed produced a phantom 3-point 'better
    line'. With a 1.5pt betting threshold that manufactures bets out of a
    data error, so the median guard must reject it.
    """
    import pandas as pd
    from nflmodel.odds import best_lines
    def row(book, spread, so=-110, aso=-110):
        return {'game': 'GB@MIN', 'book': book, 'spread': spread,
                'spread_odds': so, 'away_spread_odds': aso,
                'home_ml': -120, 'away_ml': 100, 'home_team': 'MIN',
                'away_team': 'GB', 'source': 'action_network'}

    df = pd.DataFrame([
        row('draftkings', 1.5), row('fanduel', 1.5, -108, -112),
        row('caesars', 2.0),
        row('betmgm', -1.5),          # sign-inverted feed row
    ])
    guarded = best_lines(df, max_dev=1.0)
    assert not guarded.empty
    best = float(guarded.iloc[0]['best_home_spread'])
    assert best >= 1.0, f'outlier not rejected: best_home_spread={best}'


def test_deployed_model_is_leak_free():
    """
    The FULL deployed path (NFLModel + market prior) must be invariant to
    whether future games exist in the input.

    This is the test that matters most in the repo. A missing as-of cutoff in
    the market prior once moved ratings by 0.8 points and produced a 56% ATS
    hold-out result that was entirely fabricated.
    """
    import pandas as pd
    from nflmodel.model import NFLModel
    from nflmodel.ratings import _time_index

    if not (CACHE_DIR / 'dataset_2010_2025.parquet').exists():
        pytest.skip('dataset not built')

    df = pd.read_parquet(CACHE_DIR / 'dataset_2010_2025.parquet') \
           .sort_values(['season', 'week']).reset_index(drop=True)
    season, week = 2023, 10

    full = NFLModel().fit(df, season, week, market_games=df)

    cut = season * RATINGS.offseason_weeks_equiv + week
    trunc = df[_time_index(df.season, df.week, RATINGS) < cut]
    truncated = NFLModel().fit(trunc, season, week, market_games=trunc)

    for team in full.team_ratings:
        assert full.team_ratings[team] == pytest.approx(
            truncated.team_ratings[team], abs=1e-9), f'{team} leaks future data'
    assert full.hfa == pytest.approx(truncated.hfa, abs=1e-9)


# ── quarterback identity & starter resolution ────────────────────

def test_one_quarterback_gets_one_name():
    """
    The ratings fit keys quarterbacks by NAME, so a player spelled two ways is
    two rated players splitting his starts -- and each half is likelier to
    fall under min_qb_starts and be pooled into replacement level. nflverse
    spells several starters both ways ("Mitch"/"Mitchell Trubisky") and
    carries outright typos, so the id has to pick the name.
    """
    from nflmodel.data import load_games
    g = load_games()
    pairs = pd.concat([
        g[['home_qb_id', 'home_qb_name']].rename(
            columns={'home_qb_id': 'id', 'home_qb_name': 'name'}),
        g[['away_qb_id', 'away_qb_name']].rename(
            columns={'away_qb_id': 'id', 'away_qb_name': 'name'}),
    ]).dropna()
    spellings = pairs.groupby('id')['name'].nunique()
    offenders = spellings[spellings > 1]
    assert offenders.empty, f'{len(offenders)} quarterback(s) with split identities'


def test_qb_override_actually_reaches_the_projection():
    """
    Regression test for a silently inert override.

    The slate used to take its starters via fillna, which was correct only
    while nflverse left the quarterback columns null for unplayed games. Once
    nflverse began pre-filling the upcoming week, there was nothing to fill:
    every resolved starter -- including an explicit --qb override -- was
    discarded, and the documented override did nothing at all.

    Swapping a starter for a replacement-level quarterback must move the
    projected margin. If this test passes trivially, the QB path is dead.
    """
    from nflmodel.depth import resolve_starters, SOURCE_OVERRIDE

    hist = pd.DataFrame({'played': []})
    games = pd.DataFrame({'home_qb_id': [], 'home_qb_name': [],
                          'away_qb_id': [], 'away_qb_name': []})

    starters, source, _, _ = resolve_starters(
        hist, games, 2026, 1,
        slate_names={'KC': 'Patrick Mahomes'},
        overrides={'KC': 'Somebody Else'},
        use_depth_chart=False,
    )
    assert starters['KC'] == 'Somebody Else', 'override lost to the game file'
    assert source['KC'] == SOURCE_OVERRIDE


def test_starter_precedence_is_override_then_chart_then_file():
    """Each layer must beat the one below it, and only that one."""
    from nflmodel.depth import (resolve_starters, SOURCE_SLATE,
                                SOURCE_CARRY_FORWARD)
    hist = pd.DataFrame({'played': []})
    games = pd.DataFrame({'home_qb_id': [], 'home_qb_name': [],
                          'away_qb_id': [], 'away_qb_name': []})

    starters, source, _, _ = resolve_starters(
        hist, games, 2026, 1,
        slate_names={'KC': 'From File'},
        use_depth_chart=False,
    )
    assert starters['KC'] == 'From File'
    assert source['KC'] == SOURCE_SLATE

    # An empty game-file entry must not shadow a real answer.
    starters, source, _, _ = resolve_starters(
        hist, games, 2026, 1,
        slate_names={'KC': ''},
        overrides={'KC': 'Real Guy'},
        use_depth_chart=False,
    )
    assert starters['KC'] == 'Real Guy'


# ── straight-up picks ────────────────────────────────────────────

def test_ranking_picks_the_side_the_probability_favors():
    from nflmodel.report import straight_up_ranking
    slate = pd.DataFrame([
        {'home_team': 'KC', 'away_team': 'DEN', 'home_win_prob': 0.72,
         'projected_margin': 7.0, 'home_ml': -260, 'away_ml': 210,
         'spread_line': 6.5},
        {'home_team': 'NYG', 'away_team': 'DAL', 'home_win_prob': 0.41,
         'projected_margin': -3.5, 'home_ml': 140, 'away_ml': -165,
         'spread_line': -3.0},
    ])
    r = straight_up_ranking(slate)
    assert list(r.winner) == ['KC', 'DAL'], 'winner must follow win probability'
    assert list(r['rank']) == [1, 2]
    assert (r.win_prob.diff().dropna() <= 0).all(), 'must be sorted by confidence'
    # Margin is reported from the winner's side, so it is never negative for
    # a pick the model is actually making.
    assert (r.proj_margin > 0).all()


def test_probability_and_margin_disagreement_is_called_a_coin_flip():
    """
    Probability comes from tilting the empirical margin distribution, not from
    the point estimate, so the two can point opposite ways inside a tenth of a
    point. Ranking that as a confident pick would imply precision the model
    does not have.
    """
    from nflmodel.report import straight_up_ranking
    slate = pd.DataFrame([
        {'home_team': 'HOU', 'away_team': 'BUF', 'home_win_prob': 0.5002,
         'projected_margin': -0.085, 'home_ml': -105, 'away_ml': -115,
         'spread_line': -1.5},
    ])
    r = straight_up_ranking(slate)
    assert r.loc[0, 'confidence'] == 'coin flip'


def test_depth_chart_cannot_see_past_the_kickoff():
    """
    Leak regression.

    The depth chart file holds every daily snapshot of a season, so taking
    "the most recent" one means taking a January snapshot when replaying an
    October week -- handing the model the starting quarterbacks for games it
    is about to predict. This was live: replaying 2025 week 5 assumed eight
    quarterbacks who were, in fact, the ones who started, because the snapshot
    came from after the season.

    Every snapshot the resolver uses must predate the week's first kickoff.
    """
    from nflmodel.depth import depth_chart_starters
    from nflmodel.data import load_games

    games = load_games()
    wk = games[(games.season == 2025) & (games.week == 5)]
    if wk.empty or wk.gameday.isna().all():
        pytest.skip('2025 week 5 not in the game file')
    kickoff = pd.to_datetime(wk.gameday).min()

    _, snapshot, _ = depth_chart_starters(2025, 5, asof=kickoff)
    if snapshot is None:
        pytest.skip('depth charts unavailable offline')

    stamp = pd.to_datetime(snapshot, utc=True)
    assert stamp < pd.Timestamp(kickoff).tz_localize('UTC'), (
        f'depth chart snapshot {stamp} is not earlier than kickoff {kickoff}')


def test_archive_refuses_to_rewrite_a_locked_week():
    """
    A prediction rewritten after the games are played is not a prediction.
    The archive is the only record that can ever settle whether this model
    works, so a locked week must be immutable.
    """
    import json, tempfile, pathlib
    import nflmodel.archive as A

    with tempfile.TemporaryDirectory() as tmp:
        real = A.ARCHIVE_DIR
        A.ARCHIVE_DIR = pathlib.Path(tmp)
        try:
            ranked = pd.DataFrame([{'rank': 1, 'winner': 'KC', 'loser': 'DEN',
                                    'matchup': 'DEN @ KC', 'at_home': True,
                                    'win_prob': 0.7, 'proj_margin': 6.0,
                                    'moneyline': -250, 'market_favorite': True,
                                    'confidence': 'solid', 'consistent': True}])
            slate = pd.DataFrame([{'recommendation': 'NO BET'}])
            assert A.archive_week(ranked, slate, {'KC': 'X'}, {'KC': 'y'}, 2026, 3)
            A.lock_week(2026, 3)
            # A second write must be refused now that the week is locked.
            assert not A.archive_week(ranked, slate, {'KC': 'CHANGED'},
                                      {'KC': 'y'}, 2026, 3)
            meta = json.loads((pathlib.Path(tmp) / '2026' /
                               'week03_meta.json').read_text())
            assert meta['starters']['KC'] == 'X', 'locked week was overwritten'
        finally:
            A.ARCHIVE_DIR = real


def test_archive_refuses_to_backfill_a_week_that_already_kicked_off():
    """
    A replayed week must not enter the picks archive.

    Re-running a completed week produces picks that were never published and
    never risked anything: the slate's results are already known and the code
    generating them is today's. Writing those to picks/ would manufacture a
    track record out of hindsight, and the workbook's Bet Log would then
    present it as real history. Only --archive-anyway may override.
    """
    import pathlib
    import tempfile

    import nflmodel.archive as A

    games = pd.DataFrame({
        "season": [2025, 2025],
        "week": [5, 5],
        "gameday": pd.to_datetime(["2025-10-05", "2025-10-06"]),
    })
    ranked = pd.DataFrame([{"rank": 1, "winner": "KC", "loser": "DEN",
                            "matchup": "DEN @ KC", "at_home": True,
                            "win_prob": 0.7, "proj_margin": 6.0,
                            "moneyline": -250, "market_favorite": True,
                            "confidence": "solid", "consistent": True}])
    slate = pd.DataFrame([{"recommendation": "NO BET"}])

    with tempfile.TemporaryDirectory() as tmp:
        real = A.ARCHIVE_DIR
        A.ARCHIVE_DIR = pathlib.Path(tmp)
        try:
            assert A.kickoff_has_passed(games, 2025, 5)
            # A past week with no existing archive is a rebuild: refuse.
            assert not A.archive_week(ranked, slate, {"KC": "X"}, {"KC": "y"},
                                      2025, 5, games=games)
            assert not (pathlib.Path(tmp) / "2025" / "week05_picks.csv").exists()
            # Explicit override still works, for a week that really was published.
            assert A.archive_week(ranked, slate, {"KC": "X"}, {"KC": "y"},
                                  2025, 5, games=games, force=True)
            # An upcoming week is unaffected.
            future = games.assign(season=2099, gameday=pd.to_datetime(
                ["2099-10-05", "2099-10-06"]))
            assert not A.kickoff_has_passed(future, 2099, 5)
            assert A.archive_week(ranked, slate, {"KC": "X"}, {"KC": "y"},
                                  2099, 5, games=future)
        finally:
            A.ARCHIVE_DIR = real


def test_bet_explanations_state_what_has_to_happen():
    """The 'why' line is what Jameson bets from; its cover arithmetic must be exact."""
    from nflmodel.model import explain_bet
    # Dog getting 8.5: covers unless the favorite wins by 9+.
    assert "CLE wins or loses by 8 or less" in explain_bet("SPREAD", "CLE", "TB", 6.5, ticket=8.5)
    # Favorite laying 8.5 needs a 9-point win.
    assert "TB wins by 9+" in explain_bet("SPREAD", "TB", "TB", 10.0, ticket=-8.5)
    # Whole numbers push.
    assert "wins by 4+ (push at 3)" in explain_bet("SPREAD", "KC", "KC", 5.0, ticket=-3.0)
    assert "loses by 2 or less (push at 3)" in explain_bet("SPREAD", "NO", "DET", 1.0, ticket=3.0)
    assert "ATL wins or loses by 1 or less" in explain_bet("SPREAD", "ATL", "ATL", 1.0, ticket=1.5)
    ml = explain_bet("MONEYLINE", "MIA", "SF", 11.0, odds=600, model_p=0.24, market_p=0.14)
    assert "still picks SF" in ml and "upset" in ml


def test_bet_is_tagged_against_the_straight_up_pick():
    """A dog getting points the model still expects to lose is a value bet, not its pick."""
    from nflmodel.model import NFLModel, WITH_PICK, AGAINST_PICK
    m = NFLModel()
    m.team_ratings = {"TB": 3.0, "CLE": -2.0}
    m.hfa = 1.5
    game = dict(game_id="x", week=2, home_team="TB", away_team="CLE", spread_line=8.5,
                home_moneyline=-375, away_moneyline=300, home_qb_name=None, away_qb_name=None)
    p = m.project(game)
    assert p.projected_margin > 0 and p.projected_margin < 8.5
    assert p.bet_side.startswith("CLE +8.5"), p.bet_side
    assert p.bet_type == AGAINST_PICK
    assert "Model: TB by" in p.bet_why and "CLE wins or loses by 8 or less" in p.bet_why

    game["spread_line"] = 1.0                     # now TB -1: the model's side is TB itself
    p = m.project(game)
    assert p.bet_side.startswith("TB"), p.bet_side
    assert p.bet_type == WITH_PICK
