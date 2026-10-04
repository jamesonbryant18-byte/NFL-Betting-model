"""
The Bet Tracker is carried into a new workbook as the sheet itself.

Jameson, 2026-09-30: the tracker "should only be for you to observe not to
touch and meddle with". excel._start_workbook loads his newest workbook and
drops every other sheet; the model's sheets are rebuilt around it. These
tests pin that nothing on his sheet changes -- values, formulas, colours,
dropdowns, merged cells, a note typed past the last column -- and that the
builder that grabs the ACTIVE sheet (_sheet_lists) never lands on his.
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from nflmodel import excel
from nflmodel.betlog import TRACKER_SHEET, load_tracker, tracker_fingerprint


def _his_workbook(path):
    """A weekly workbook as Excel leaves it after he has typed into it."""
    wb = Workbook()
    wb.active.title = "Lists"
    wb.create_sheet("This Week's Bets")["A1"] = "old model sheet"
    ws = wb.create_sheet(TRACKER_SHEET)
    ws["A1"] = "BET TRACKER"
    ws.merge_cells("A1:P1")
    ws["B4"] = 1000
    ws["A11"] = "Date"
    ws["A12"] = datetime(2026, 9, 27)
    ws["B12"] = 3
    ws["C12"] = "TEN @ NY "
    ws["D12"] = "MONEYLINE"
    ws["E12"] = "HOME"
    ws["G12"] = -127
    ws["H12"] = 5
    ws["I12"] = "W"
    ws["J12"] = '=IF($I12="W",IF($G12<0,$H12*100/ABS($G12),$H12*$G12/100),"")'
    ws["Q12"] = "his own note"                         # past the last column
    ws["C12"].fill = PatternFill("solid", fgColor="FFFF00")
    dv = DataValidation(type="list", formula1='"W,L,Push"', allow_blank=True)
    dv.sqref = "I12:I500"
    ws.add_data_validation(dv)
    wb.create_sheet("Power Ratings")["A1"] = "old ratings"
    wb.create_sheet("My Notes")["A1"] = "a sheet he added himself"
    wb.create_sheet("Model Data").sheet_state = "hidden"
    wb.save(str(path))
    return path


def _cells(ws):
    return {(c.row, c.column): c.value
            for row in ws.iter_rows() for c in row if c.value not in (None, "")}


def test_tracker_is_carried_cell_for_cell(tmp_path):
    out = tmp_path / "output"
    out.mkdir()
    src = _his_workbook(out / "NFL_Model_2026_Week04.xlsx")
    tracker = load_tracker(out, tmp_path / "bet_log.csv")
    assert tracker.kind == "workbook"

    wb = excel._start_workbook(tracker)
    # Only his sheets survive, plus a new Lists that is ACTIVE.
    assert wb.sheetnames == ["Lists", TRACKER_SHEET, "My Notes"]
    assert wb.active.title == "Lists"

    excel._sheet_lists(wb, [(3.0, 0.08)])        # takes over the active sheet
    assert TRACKER_SHEET in wb.sheetnames, "_sheet_lists renamed his tracker"
    wb.create_sheet("This Week's Bets")["A1"] = "new model sheet"
    wb.create_sheet("Power Ratings")
    wb.create_sheet("Bet Log")
    excel._place_tracker(wb)
    assert wb.sheetnames == ["Lists", "This Week's Bets", "Power Ratings",
                             TRACKER_SHEET, "Bet Log", "My Notes"]
    dest = out / "NFL_Model_2026_Week05.xlsx"
    wb.save(str(dest))

    before = load_workbook(str(src))[TRACKER_SHEET]
    after_wb = load_workbook(str(dest))
    after = after_wb[TRACKER_SHEET]
    assert _cells(after) == _cells(before)
    assert tracker_fingerprint(dest) == tracker_fingerprint(src)
    assert after["Q12"].value == "his own note"
    assert after["J12"].value.startswith("=IF(")
    assert after["C12"].fill.fgColor.rgb.endswith("FFFF00")
    assert "A1:P1" in {str(r) for r in after.merged_cells.ranges}
    assert [str(d.sqref) for d in after.data_validations.dataValidation] == ["I12:I500"]
    # The old model sheets are gone, replaced by the new ones.
    assert after_wb["This Week's Bets"]["A1"].value == "new model sheet"
    assert "Model Data" not in after_wb.sheetnames
    assert after_wb["My Notes"]["A1"].value == "a sheet he added himself"


def test_every_sheet_the_builders_create_is_registered():
    # A model sheet missing from MODEL_SHEETS would be treated as HIS and
    # carried forward stale every week, next to its rebuilt twin.
    import re
    src = open(excel.__file__).read()
    created = set(re.findall(r'create_sheet\("([^"]+)"', src))
    created.discard("Bet Tracker")
    assert created <= excel.MODEL_SHEETS, created - excel.MODEL_SHEETS


def test_fresh_workbook_when_he_has_no_tracker(tmp_path):
    out = tmp_path / "output"
    out.mkdir()
    tracker = load_tracker(out, tmp_path / "bet_log.csv")
    assert tracker.kind == "none"
    wb = excel._start_workbook(tracker)
    assert wb.sheetnames == ["Sheet"]            # the builders take it from here
