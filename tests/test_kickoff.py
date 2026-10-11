"""
A game in progress is never re-priced. 2026 Week 4: the Sunday 12:20 roster
run re-priced the 9:30 London game (IND@WAS) against an in-game line, because
"started" only looked at the day. Pinned here: kickoff time counts.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pandas as pd

from nflmodel.archive import kicked_off


def _slate():
    return pd.DataFrame({
        "game_id": ["tnf", "london", "early", "late", "mnf"],
        "gameday": ["2026-10-08", "2026-10-11", "2026-10-11", "2026-10-11", "2026-10-12"],
        "gametime": ["20:15", "09:30", "13:00", "16:25", "20:15"],
        "played": [True, False, False, False, False],
    })


def test_london_game_in_progress_counts_as_started():
    started = kicked_off(_slate(), now="2026-10-11 11:55")
    assert dict(zip(_slate().game_id, started)) == {
        "tnf": True, "london": True, "early": False, "late": False, "mnf": False}


def test_before_the_first_sunday_kickoff_only_thursday_is_started():
    started = kicked_off(_slate(), now="2026-10-11 09:29")
    assert list(started) == [True, False, False, False, False]


def test_missing_time_falls_back_to_the_day():
    g = _slate().assign(gametime=None)
    assert list(kicked_off(g, now="2026-10-11 23:00")) == [True, False, False, False, False]
    assert list(kicked_off(g.drop(columns="gametime"), now="2026-10-12 08:00")) == \
        [True, True, True, True, False]
