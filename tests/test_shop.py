"""
Tests for live multi-book pricing (src/nflmodel/shop.py).

The load-bearing one is test_devig_pair_is_never_mixed_across_books. De-vig
assumes a matched pair from one book; combining the best home price from one
book with the best away price from another produces an overround below 1.0,
which inflates both fair probabilities and manufactures edge on every game.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pandas as pd
import pytest

from nflmodel import odds
from nflmodel.shop import attach_live_odds, shopping_value, _key
from nflmodel.market import devig


def _raw(rows):
    return pd.DataFrame(rows, columns=odds.COLUMNS)


@pytest.fixture
def two_book_slate():
    """One game, two books disagreeing, plus an explicit consensus row."""
    base = dict(game='SEA@WAS', commence_time='2026-09-28T17:00:00Z',
                home_team='WAS', away_team='SEA', espn_id=None,
                source='action_network', away_spread_odds=-110)
    return _raw([
        {**base, 'book': 'bet365',     'spread': -7.0, 'spread_odds': -110,
         'home_ml': 250, 'away_ml': -310},
        {**base, 'book': 'unibet',     'spread': -6.5, 'spread_odds': -110,
         'home_ml': 270, 'away_ml': -345},
        {**base, 'book': 'consensus',  'spread': -7.0, 'spread_odds': -110,
         'home_ml': 255, 'away_ml': -319},
    ])


@pytest.fixture
def slate_games():
    return pd.DataFrame([dict(
        game_id='2026_03_SEA_WAS', season=2026, week=3,
        home_team='WAS', away_team='SEA',
        spread_line=-9.0, home_moneyline=245, away_moneyline=-305)])


# ── the de-vig trap ──────────────────────────────────────────────

def test_devig_pair_is_never_mixed_across_books(two_book_slate, slate_games,
                                                monkeypatch):
    """The fair-probability pair must be matched, not best-of-both-sides."""
    monkeypatch.setattr(odds, 'live_odds', lambda *a, **k: two_book_slate)
    out, rep = attach_live_odds(slate_games, 2026, 3, verbose=False)
    assert rep['ok']

    r = out.iloc[0]
    # The pair fed to the model is the consensus pair, NOT (+270, -310).
    assert r.home_moneyline == 255
    assert r.away_moneyline == -319

    fair_h, fair_a = devig(r.home_moneyline, r.away_moneyline)
    assert fair_h + fair_a == pytest.approx(1.0, abs=1e-9)

    # The trap, stated precisely. Mixing the best price from each side does
    # not usually drive the overround below 1.0 -- real vig is too wide for
    # six books to erase. What it does do is SHRINK the overround, and a
    # smaller overround de-vigs to smaller fair probabilities, which inflates
    # (model - fair) on both sides of every game.
    from nflmodel.market import american_to_prob
    matched = american_to_prob(255) + american_to_prob(-319)
    mixed = american_to_prob(270) + american_to_prob(-305)
    assert mixed < matched, 'mixing books understates the vig'

    fair_mixed_h, _ = devig(270, -305)
    assert fair_mixed_h < fair_h, (
        'the mixed pair makes the home side look less likely than the market '
        'really prices it, which is free edge the model did not earn')


def test_best_prices_are_still_reported(two_book_slate, slate_games, monkeypatch):
    """Shopping must improve the fill even though it cannot touch the edge."""
    monkeypatch.setattr(odds, 'live_odds', lambda *a, **k: two_book_slate)
    out, _ = attach_live_odds(slate_games, 2026, 3, verbose=False)
    r = out.iloc[0]
    assert r.best_home_ml == 270
    assert r.best_home_ml_book == 'unibet'


# ── consensus replaces the stored line ───────────────────────────

def test_consensus_replaces_a_stale_stored_line(two_book_slate, slate_games,
                                                monkeypatch):
    monkeypatch.setattr(odds, 'live_odds', lambda *a, **k: two_book_slate)
    out, rep = attach_live_odds(slate_games, 2026, 3, verbose=False)
    assert out.iloc[0].spread_line == pytest.approx(-6.75)   # median of -7, -6.5
    assert out.iloc[0].stored_spread_line == -9.0
    assert rep['moved'], 'a 2.25pt disagreement must be reported, not silent'


def test_open_and_consensus_are_excluded_from_the_median(slate_games, monkeypatch):
    """A stale opener must not drag the market number around."""
    base = dict(game='SEA@WAS', commence_time='2026-09-28T17:00:00Z',
                home_team='WAS', away_team='SEA', espn_id=None,
                source='action_network', away_spread_odds=-110,
                home_ml=250, away_ml=-310, spread_odds=-110)
    raw = _raw([
        {**base, 'book': 'bet365', 'spread': -7.0},
        {**base, 'book': 'unibet', 'spread': -7.0},
        {**base, 'book': 'open',   'spread': -3.5},
    ])
    monkeypatch.setattr(odds, 'live_odds', lambda *a, **k: raw)
    out, _ = attach_live_odds(slate_games, 2026, 3, verbose=False)
    assert out.iloc[0].spread_line == pytest.approx(-7.0)


# ── failure must never take the week down ────────────────────────

def test_dead_feed_falls_back_to_stored_line(slate_games, monkeypatch):
    def boom(*a, **k):
        raise ConnectionError('network down')
    monkeypatch.setattr(odds, 'live_odds', boom)
    out, rep = attach_live_odds(slate_games, 2026, 3, verbose=False)
    assert rep['ok'] is False
    assert 'ConnectionError' in rep['reason']
    assert out.iloc[0].spread_line == -9.0, 'must keep the stored number'


def test_empty_feed_falls_back(slate_games, monkeypatch):
    monkeypatch.setattr(odds, 'live_odds', lambda *a, **k: _raw([]))
    out, rep = attach_live_odds(slate_games, 2026, 3, verbose=False)
    assert rep['ok'] is False
    assert out.iloc[0].spread_line == -9.0


def test_unmatched_game_keeps_its_stored_numbers(two_book_slate, monkeypatch):
    """A game the feed does not carry must not be blanked out."""
    sg = pd.DataFrame([dict(game_id='2026_03_KC_MIA', season=2026, week=3,
                            home_team='MIA', away_team='KC',
                            spread_line=-11.5, home_moneyline=575,
                            away_moneyline=-850)])
    monkeypatch.setattr(odds, 'live_odds', lambda *a, **k: two_book_slate)
    out, rep = attach_live_odds(sg, 2026, 3, verbose=False)
    assert out.iloc[0].spread_line == -11.5
    assert out.iloc[0].odds_source == 'nflverse'
    assert rep['n_matched'] == 0


# ── shopping value ───────────────────────────────────────────────

def test_shopping_value_reports_moneyline_gain():
    """Regression: this row silently vanished when the column was home_ml."""
    slate = pd.DataFrame([dict(
        home_team='WAS', away_team='SEA', bet_side='WAS +255',
        bet_market='MONEYLINE', recommendation='BET WAS +255',
        home_ml=255, away_ml=-319,
        best_home_ml=270, best_home_ml_book='unibet',
        best_away_ml=-305, best_away_ml_book='draftkings')])
    sv = shopping_value(slate)
    assert len(sv) == 1
    assert sv.iloc[0].book == 'unibet'
    assert sv.iloc[0].gain == '+15'


def test_shopping_value_spread_gain_direction():
    """A home backer gains from a SMALLER number, an away backer a larger one."""
    slate = pd.DataFrame([dict(
        home_team='CHI', away_team='PHI', bet_side='CHI +4.5',
        bet_market='SPREAD', recommendation='BET CHI +4.5',
        spread_line=4.5, best_home_spread=4.0, best_home_spread_book='bet365',
        best_away_spread=5.0, best_away_spread_book='fanduel')])
    sv = shopping_value(slate)
    assert sv.iloc[0].gain == '+0.5 pts'


def test_no_bets_gives_empty_table():
    slate = pd.DataFrame([dict(home_team='CHI', away_team='PHI',
                               recommendation='NO BET', bet_side=None,
                               bet_market=None)])
    assert len(shopping_value(slate)) == 0


def test_key_is_away_at_home():
    assert _key('SEA', 'WAS') == 'SEA@WAS'
