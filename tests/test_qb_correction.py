"""
data.correct_stale_qbs: nflverse leaves pre-game "probable starter" entries
uncorrected (2026 Week 3 listed Jayden Daniels for WAS; Mariota threw every
pass). Only a listed QB with zero attempts may be replaced.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import numpy as np
import pandas as pd

from nflmodel.data import correct_stale_qbs


def _games():
    return pd.DataFrame({
        'game_id':      ['g1', 'g2', 'g3', 'g4'],
        'season':       [2026, 2026, 2026, 2026],
        'week':         [3, 1, 4, 5],
        'home_team':    ['WAS', 'ARI', 'CHI', 'NYG'],
        'away_team':    ['SEA', 'SEA', 'MIN', 'DAL'],
        'result':       [2.0, -6.0, 7.0, np.nan],
        'home_qb_id':   ['daniels', 'murray', 'caleb', 'dart'],
        'home_qb_name': ['Jayden Daniels', 'Kyler Murray', 'Caleb Williams', 'Jaxson Dart'],
        'away_qb_id':   ['lock', 'darnold', 'kyler', 'dak'],
        'away_qb_name': ['Drew Lock', 'Sam Darnold', 'Kyler Murray', 'Dak Prescott'],
    })


def _attempts():
    return pd.DataFrame([
        # Week 3: the listed QBs never threw -- both stale.
        (2026, 3, 'WAS', 'mariota', 'Marcus Mariota', 31),
        (2026, 3, 'SEA', 'darnold', 'Sam Darnold', 45),
        # Week 1: Darnold hurt early, threw 2; Lock threw most. Darnold started.
        (2026, 1, 'SEA', 'darnold', 'Sam Darnold', 2),
        (2026, 1, 'SEA', 'lock', 'Drew Lock', 22),
        (2026, 1, 'ARI', 'murray', 'Kyler Murray', 30),
        # Week 4: no stats published yet for this game.
    ], columns=['season', 'week', 'team', 'player_id',
                'player_display_name', 'attempts'])


def test_listed_qb_with_no_attempts_is_replaced_by_attempts_leader():
    out = correct_stale_qbs(_games(), _attempts()).set_index('game_id')
    assert out.at['g1', 'home_qb_name'] == 'Marcus Mariota'
    assert out.at['g1', 'home_qb_id'] == 'mariota'
    # The replacement takes the games file's own spelling of that player.
    assert out.at['g1', 'away_qb_name'] == 'Sam Darnold'
    assert out.at['g1', 'away_qb_id'] == 'darnold'


def test_starter_who_threw_even_one_pass_is_kept():
    out = correct_stale_qbs(_games(), _attempts()).set_index('game_id')
    assert out.at['g2', 'away_qb_name'] == 'Sam Darnold'
    assert out.at['g2', 'home_qb_name'] == 'Kyler Murray'


def test_games_without_stats_and_unplayed_games_are_untouched():
    g = _games()
    out = correct_stale_qbs(g, _attempts()).set_index('game_id')
    for gid in ('g3', 'g4'):
        for col in ('home_qb_name', 'away_qb_name', 'home_qb_id', 'away_qb_id'):
            assert out.at[gid, col] == g.set_index('game_id').at[gid, col]


def test_no_stats_at_all_is_a_no_op():
    g = _games()
    empty = _attempts().iloc[0:0]
    pd.testing.assert_frame_equal(correct_stale_qbs(g, empty), g)
