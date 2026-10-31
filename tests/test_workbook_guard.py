"""Game-day runs reach the record (expert review round 2, fix 9)."""
import os
import subprocess
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pandas as pd

from nflmodel import workbook_guard as wg


def _norm(n):
    return str(n).lower().replace('.', '').replace(' jr', '')


def test_side_path_never_names_his_file_and_still_counts_as_a_weekly_workbook(tmp_path):
    from fnmatch import fnmatch
    from nflmodel.betlog import WORKBOOK_GLOB
    his = tmp_path / "NFL_Model_2026_Week08.xlsx"
    side = wg.side_path(his, datetime(2026, 11, 1, 12, 5))
    assert side != his and side.parent == his.parent
    assert side.name == "NFL_Model_2026_Week08 (new Sun 1205).xlsx"
    assert fnmatch(side.name, WORKBOOK_GLOB)      # the next week's carry can read it


def test_open_workbook_found_from_excel_or_its_owner_file(tmp_path, monkeypatch):
    p = tmp_path / "NFL_Model_2026_Week08.xlsx"
    ran = lambda out, rc=0: (lambda *a, **k: subprocess.CompletedProcess(a, rc, out, ""))
    monkeypatch.setattr(subprocess, "run", ran("Other.xlsx\tfalse\nNFL_Model_2026_Week08.xlsx\tfalse\n"))
    assert wg.excel_state(p) == dict(open=True, saved=False, how="asked Excel")
    monkeypatch.setattr(subprocess, "run", ran("NOT RUNNING"))
    assert wg.excel_state(p)["open"] is False
    monkeypatch.setattr(subprocess, "run", ran("", rc=1))       # Excel would not answer
    assert wg.excel_state(p)["open"] is False
    (tmp_path / "~$NFL_Model_2026_Week08.xlsx").write_text("")
    assert wg.excel_state(p) == dict(open=True, saved=None, how="Excel owner file")


def test_card_changes_lists_added_dropped_and_new_numbers():
    before = pd.DataFrame([
        dict(game_id="a", bet_side="PHI +5.5", bet_market="SPREAD", bet_odds=-110),
        dict(game_id="b", bet_side="BUF -168", bet_market="MONEYLINE", bet_odds=-168),
        dict(game_id="c", bet_side="SEA -3.0", bet_market="SPREAD", bet_odds=-114),
        dict(game_id="z", bet_side="GB -6.5", bet_market="SPREAD", bet_odds=-110),  # played
    ])
    after = pd.DataFrame([
        dict(game_id="a", bet_side="PHI +4.5", bet_market="SPREAD", bet_odds=-105),
        dict(game_id="b", bet_side="", bet_market="", bet_odds=0.0),
        dict(game_id="c", bet_side="SEA -3.0", bet_market="SPREAD", bet_odds=-114),
        dict(game_id="d", bet_side="LV +1.5", bet_market="SPREAD", bet_odds=-110),
    ])
    assert wg.card_changes(before, after) == [
        "changed  PHI +5.5 -110  ->  PHI +4.5 -105", "dropped  BUF -168", "added    LV +1.5 -110"]
    assert wg.card_changes(before, before[before.game_id != "z"]) == []


def test_override_over_a_healthy_charted_starter_is_flagged_stale():
    inj = pd.DataFrame([dict(team="BAL", player="Lamar Jackson", status="Out")])
    chart = {"TB": "Baker Mayfield", "BAL": "Lamar Jackson", "PHI": "Tanner McKee"}
    lines = wg.stale_overrides({"TB": "Jalon Daniels", "BAL": "Tyler Huntley",
                                "PHI": "Tanner McKee"}, chart, inj, _norm)
    assert len(lines) == 2
    assert lines[0].startswith('WARNING: --qb TB="Jalon Daniels" may be STALE')
    assert "Out on the injury report" in lines[1] and "BAL" in lines[1]
    assert "unavailable" in wg.stale_overrides({"TB": "Jalon Daniels"}, chart, None, _norm)[0]
