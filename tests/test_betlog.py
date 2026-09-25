"""
Tests for betlog.py — the union of every copy of the Bet Tracker.

The scenario these pin is the one that lost data: Week 1's workbook was
edited AFTER data/bet_log.csv was last written, and the Week 2 workbook does
not exist yet. Every row the user ever typed has to come through, and where
two copies disagree the most recently saved file must win.

Run: .venv/bin/python -W ignore -m pytest tests/test_betlog.py -q
"""
import os
import sys
import time
from datetime import date, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import pytest
from openpyxl import Workbook

from nflmodel import betlog
from nflmodel.betlog import (BET_LOG_COLUMNS, bet_key, clv_for_row,
                             collect_preserved_bets, normalize_matchup,
                             parse_row, read_csv_rows, read_tracker_rows,
                             write_csv_rows)


# ── fixtures ───────────────────────────────────────────────────

def _write_tracker(path, rows, sheet="Bet Tracker"):
    """A workbook shaped like excel._sheet_tracker's: data from row 12,
    A..I hand-entered, L/M/P extras. Formula columns are left empty."""
    wb = Workbook()
    ws = wb.active
    ws.title = sheet
    ws.cell(row=11, column=1, value="Date")
    for i, rec in enumerate(rows):
        r = 12 + i
        for c, v in enumerate(rec[:9], start=1):
            ws.cell(row=r, column=c, value=v)
        for off, col in enumerate((12, 13, 16)):
            idx = 9 + off
            if len(rec) > idx and rec[idx] is not None:
                ws.cell(row=r, column=col, value=rec[idx])
    wb.save(str(path))
    return path


def _set_mtime(path, when: float):
    os.utime(str(path), (when, when))


# The same bet, at different points in its life.
SHARED_OLD = ["9/13/2026", 1, "MIA @ LV", "SPREAD", "MIA +3.5", 3.5, -110, 50, None,
              None, None, None]
SHARED_NEW = ["9/13/2026", 1, "MIA @ LV", "SPREAD", "MIA +3.5", 3.5, -110, 75, "W",
              1.5, -108, 2.1]
OLD_ONLY = ["9/14/2026", 1, "DEN @ KC", "MONEYLINE", "DEN +140", None, 140, 25, "L",
            None, 150, 0.04]
NEW_ONLY = ["9/20/2026", 2, "KC @ NYG", "SPREAD", "NYG +6.5", 6.5, -105, 40, None,
            None, None, None]
CSV_ONLY = ["9/13/2026", "1", "DAL @ NYG", "SPREAD", "NYG +3.0", "3.0", "-115", "50",
            "", "", "", ""]


@pytest.fixture
def stores(tmp_path):
    """Two workbooks and a CSV with controlled mtimes.

    newest:  Week02 workbook  — edited stake/result on the shared bet, + NEW_ONLY
    middle:  CSV mirror       — the shared bet as first logged, + CSV_ONLY
    oldest:  Week01 workbook  — the shared bet as first logged, + OLD_ONLY
    """
    out = tmp_path / "output"
    out.mkdir()
    wk1 = _write_tracker(out / "NFL_Model_2026_Week01.xlsx", [SHARED_OLD, OLD_ONLY])
    wk2 = _write_tracker(out / "NFL_Model_2026_Week02.xlsx", [SHARED_NEW, NEW_ONLY])
    csv_path = tmp_path / "data" / "bet_log.csv"
    write_csv_rows([SHARED_OLD, CSV_ONLY], csv_path)

    now = time.time()
    _set_mtime(wk1, now - 3 * 3600)
    _set_mtime(csv_path, now - 2 * 3600)
    _set_mtime(wk2, now - 1 * 3600)
    return {"out": out, "wk1": wk1, "wk2": wk2, "csv": csv_path}


# ── reading the stores ──────────────────────────────────────────

def test_read_tracker_rows_matches_sheet_layout(stores):
    rows = read_tracker_rows(stores["wk2"])
    assert len(rows) == 2
    assert all(len(r) == 12 for r in rows)
    shared = rows[0]
    assert shared[:9] == SHARED_NEW[:9]
    # L, M, P land in slots 9, 10, 11 — the same order the CSV uses.
    assert shared[9:] == [1.5, -108, 2.1]


def test_read_tracker_rows_is_empty_for_missing_file_or_sheet(tmp_path):
    assert read_tracker_rows(tmp_path / "nope.xlsx") == []
    other = _write_tracker(tmp_path / "other.xlsx", [SHARED_OLD], sheet="Not It")
    assert read_tracker_rows(other) == []
    junk = tmp_path / "junk.xlsx"
    junk.write_bytes(b"this is not a workbook")
    assert read_tracker_rows(junk) == []


def test_csv_roundtrip_pads_and_truncates(tmp_path):
    p = tmp_path / "log.csv"
    write_csv_rows([SHARED_OLD[:5], SHARED_NEW + ["extra"]], p)
    rows = read_csv_rows(p)
    assert len(rows) == 2 and all(len(r) == 12 for r in rows)
    assert rows[0][:5] == [str(v) for v in SHARED_OLD[:5]]
    assert rows[0][5:] == [""] * 7
    assert p.read_text().splitlines()[0] == ",".join(BET_LOG_COLUMNS)
    assert read_csv_rows(tmp_path / "missing.csv") == []


# ── identity ────────────────────────────────────────────────────

def test_normalize_matchup_only_touches_separator_case_and_spacing():
    for s in ("MIA @ LV", "MIA@LV", "mia at lv", "  mia   @  lv "):
        assert normalize_matchup(s) == "MIA @ LV"
    assert normalize_matchup("LV vs MIA") == "LV VS MIA"
    assert normalize_matchup(None) == ""
    # 'AT' must be the separator, not part of a team code (ATL).
    assert normalize_matchup("ATL @ PIT") == "ATL @ PIT"
    assert normalize_matchup("atl at pit") == "ATL @ PIT"


def test_bet_key_ignores_the_editable_fields_and_the_date_type():
    assert bet_key(SHARED_OLD) == bet_key(SHARED_NEW)
    typed = list(SHARED_OLD)
    typed[0] = datetime(2026, 9, 13)              # what openpyxl hands back
    typed[2], typed[3], typed[4] = "mia@lv", "spread", "mia  +3.5"
    assert bet_key(typed) == bet_key(SHARED_OLD)
    assert bet_key(SHARED_OLD) != bet_key(OLD_ONLY)


# ── the union ───────────────────────────────────────────────────

def test_collect_unions_every_store_newest_edit_winning(stores):
    # Week 3 is being run for the first time: its workbook does not exist.
    rows = collect_preserved_bets(stores["out"] / "NFL_Model_2026_Week03.xlsx",
                                  stores["out"], stores["csv"])
    keys = [bet_key(r) for r in rows]
    assert len(keys) == len(set(keys)), "a bet was duplicated"

    by_key = {bet_key(r): r for r in rows}
    shared = by_key[bet_key(SHARED_NEW)]
    assert shared[7] == 75 and shared[8] == "W", "newest edit did not win"
    assert shared[9:] == [1.5, -108, 2.1], "closing line/odds/edge were lost"
    assert bet_key(OLD_ONLY) in by_key, "row only in the older workbook was dropped"
    assert bet_key(CSV_ONLY) in by_key, "row only in the CSV mirror was dropped"
    assert bet_key(NEW_ONLY) in by_key

    # Newest source first in its own order, then unseen rows from older
    # sources in mtime order (CSV before Week01).
    assert keys == [bet_key(SHARED_NEW), bet_key(NEW_ONLY),
                    bet_key(CSV_ONLY), bet_key(OLD_ONLY)]
    # Values come back exactly as read: the CSV row is still strings.
    assert by_key[bet_key(CSV_ONLY)][7] == "50"


def test_collect_prefers_the_current_workbook_when_it_is_newest(stores):
    # Second run of the same week: the current workbook was just edited.
    _set_mtime(stores["wk1"], time.time())
    rows = collect_preserved_bets(stores["wk1"], stores["out"], stores["csv"])
    shared = {bet_key(r): r for r in rows}[bet_key(SHARED_OLD)]
    assert shared[7] == 50 and shared[8] is None
    assert [bet_key(r) for r in rows][:2] == [bet_key(SHARED_OLD), bet_key(OLD_ONLY)]
    assert len(rows) == 4


def test_collect_is_empty_when_nothing_exists(tmp_path):
    assert collect_preserved_bets(tmp_path / "x.xlsx", tmp_path / "output",
                                  tmp_path / "bet_log.csv") == []
    (tmp_path / "output").mkdir()
    assert collect_preserved_bets(tmp_path / "x.xlsx", tmp_path / "output",
                                  tmp_path / "bet_log.csv") == []


# ── typed view ──────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    "9/13/2026", "09/13/2026", "2026-09-13", "2026-09-13 00:00:00",
    datetime(2026, 9, 13, 0, 0), date(2026, 9, 13),
])
def test_parse_row_accepts_every_date_form(raw):
    row = list(SHARED_NEW)
    row[0] = raw
    assert parse_row(row)["date"] == date(2026, 9, 13)


def test_parse_row_types_and_blanks():
    p = parse_row(CSV_ONLY)
    assert p["date"] == date(2026, 9, 13)
    assert p["week"] == 1
    assert p["matchup"] == "DAL @ NYG" and p["market"] == "SPREAD"
    assert p["line_taken"] == 3.0 and p["odds"] == -115.0 and p["stake"] == 50.0
    assert p["result"] == ""
    assert p["closing_line"] is None and p["closing_odds"] is None
    assert p["model_edge"] is None

    p = parse_row(SHARED_NEW)
    assert p["result"] == "W" and p["closing_line"] == 1.5
    assert parse_row(["", "", "", "", "", "", "", "", "Push"])["result"] == "PUSH"
    assert parse_row(["not a date", "wk 2"])["date"] is None
    assert parse_row(["not a date", "wk 2"])["week"] == 2


# ── CLV ─────────────────────────────────────────────────────────

FAKE_PTS = [(0.0, 0.01), (1.5, 0.02), (2.5, 0.03), (3.5, 0.081), (7.5, 0.06)]


def test_clv_spread_crossing_three_uses_the_line_taken_rate():
    parsed = parse_row(["9/13/2026", 1, "MIA @ LV", "SPREAD", "MIA +3.5",
                        3.5, -110, 50, "", 2.5, -110, ""])
    pts, prob = clv_for_row(parsed, FAKE_PTS)
    assert pts == pytest.approx(1.0)
    # One point gained at a taken line of 3.5 is worth the crossing-3 rate.
    assert prob == pytest.approx(0.081)

    # Negative CLV: took -3.5, closed -2.5 (both from the bettor's side).
    parsed = parse_row(["9/13/2026", 1, "MIA @ LV", "SPREAD", "LV -3.5",
                        -3.5, -110, 50, "", -2.5, -110, ""])
    pts, prob = clv_for_row(parsed, FAKE_PTS)
    assert pts == pytest.approx(-1.0)
    assert prob == pytest.approx(-0.081)      # lookup is on |line|


def test_clv_falls_back_to_three_percent_and_handles_missing():
    parsed = parse_row(["", "", "X @ Y", "SPREAD", "X +4", 4.0, -110, 10, "", 2.0])
    assert clv_for_row(parsed, FAKE_PTS) == (pytest.approx(2.0), pytest.approx(0.06))
    assert clv_for_row(parsed, None) == (pytest.approx(2.0), pytest.approx(0.06))
    no_close = parse_row(["", "", "X @ Y", "SPREAD", "X +4", 4.0, -110, 10])
    assert clv_for_row(no_close, FAKE_PTS) == (None, None)


def test_clv_moneyline_is_the_price_difference():
    parsed = parse_row(["", "", "X @ Y", "MONEYLINE", "X +140", "", 140, 10, "",
                        "", 120, ""])
    pts, prob = clv_for_row(parsed, FAKE_PTS)
    assert pts is None
    # +140 -> 41.67%, +120 -> 45.45%: the close was shorter, CLV positive.
    assert prob == pytest.approx(100 / 220 - 100 / 240)
    assert clv_for_row(parse_row(["", "", "X @ Y", "MONEYLINE", "X", "", 140]),
                       FAKE_PTS) == (None, None)


def test_home_away_side_resolves_to_team():
    from nflmodel.betlog import parse_row
    home = parse_row(["2026-09-20", 2, "CAR @ ATL", "SPREAD", "HOME", 2.5, "", 5])
    away = parse_row(["2026-09-17", 2, "DET @ BUF", "MONEYLINE", "away", "", "", 5])
    team = parse_row(["2026-09-20", 2, "CLE @ TB", "SPREAD", "CLE +8.5", "", "", 5])
    assert home["bet_side"] == "ATL"
    assert away["bet_side"] == "DET"
    assert team["bet_side"] == "CLE +8.5"
