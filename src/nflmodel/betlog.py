"""
betlog.py — reading and typing the hand-entered Bet Tracker. Read only.

The Bet Tracker is Jameson's. He types his bets and results into the "Bet
Tracker" sheet of the weekly workbook; the model reads it (to grade what he
actually bet, and to show "Your Bet" next to the model's picks) and never
edits it. See "THE TRACKER IS JAMESON'S" below for how a new week's workbook
inherits the sheet without the model touching a cell, and why the old
merge-every-copy approach was removed on 2026-09-30.

data/bet_log.csv is a backup of his rows, committed so a dead laptop does
not take the record with it. It is written from the tracker being carried
forward and read only when no weekly workbook has a tracker.

This module also owns the typed view of a tracker row (parse_row) and the
CLV arithmetic (clv_for_row), so that history.py can grade bets in Python
exactly the way the workbook's formulas grade them in Excel. Typing a row
for grading never writes anything back.
"""

from __future__ import annotations

import csv
import math
import re
from datetime import date, datetime
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Optional

from .market import closing_line_value

# Identical to the header excel.py writes. excel.py will import it from here.
BET_LOG_COLUMNS = [
    "date", "week", "matchup", "market", "bet_side", "line_taken", "odds",
    "stake", "result", "closing_line", "closing_odds", "model_edge",
]

# Layout of the Bet Tracker sheet, as first built by excel._sheet_tracker.
# Headers sit on row 11; he types into rows 12..500. Columns A..I are the
# hand-entered fields, J/K/N/O are the sheet's own formulas, and L, M, P
# (closing line, closing odds, model edge) are hand-entered too. After the
# first build the model never rewrites any of it -- the sheet is carried
# forward as he left it.
TRACKER_SHEET = "Bet Tracker"
TRACKER_FIRST_ROW = 12
TRACKER_LAST_ROW = 500
_USER_COLS = tuple(range(1, 10))      # A..I
_EXTRA_COLS = (12, 13, 16)            # L, M, P

# Every weekly workbook the runner writes matches this.
WORKBOOK_GLOB = "NFL_Model_*_Week*.xlsx"

# Probability value of one point of spread when the line is not in the
# per-line table. Matches the IFERROR(...,0.03) fallback in the tracker's
# CLV (%) formula so Python and Excel agree.
DEFAULT_PER_PT = 0.03


# ─────────────────────────────────────────────
# READING AND WRITING THE THREE STORES
# ─────────────────────────────────────────────

def _pad(row: list) -> list:
    """A row is always 12 wide, whatever the source gave us."""
    row = list(row)[:len(BET_LOG_COLUMNS)]
    return row + [None] * (len(BET_LOG_COLUMNS) - len(row))


def _is_blank(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and math.isnan(v):
        return True
    return str(v).strip() == ""


def read_tracker_rows(workbook_path) -> list[list]:
    """
    Hand-entered rows from one workbook's Bet Tracker, as 12-element lists.

    Loads with formulas intact (not data_only) so the hand-entered cells come
    back as typed; the formula columns are skipped because they are rewritten
    every run. A row counts if anything in A..I is filled. Returns [] for a
    missing file, a missing sheet, or a file openpyxl cannot read -- a bad
    workbook must never abort a run, it just contributes nothing.
    """
    try:
        from openpyxl import load_workbook

        wb = load_workbook(str(workbook_path))
        if TRACKER_SHEET not in wb.sheetnames:
            return []
        ws = wb[TRACKER_SHEET]
        rows = []
        for r in range(TRACKER_FIRST_ROW, TRACKER_LAST_ROW + 1):
            vals = [ws.cell(row=r, column=c).value for c in _USER_COLS]
            if all(_is_blank(v) for v in vals):
                continue
            extras = [ws.cell(row=r, column=c).value for c in _EXTRA_COLS]
            rows.append(vals + extras)
        return rows
    except Exception:
        return []


def read_csv_rows(csv_path) -> list[list]:
    """
    Rows from the CSV mirror, padded or truncated to 12 columns.

    The header is recognised by its first cell rather than assumed, so a file
    that lost its header still yields its rows. Blank lines are dropped.
    """
    p = Path(csv_path)
    if not p.exists():
        return []
    try:
        with p.open(newline="") as fh:
            raw = list(csv.reader(fh))
    except Exception:
        return []
    out = []
    for i, r in enumerate(raw):
        if i == 0 and r and str(r[0]).strip().lower() == "date":
            continue
        if all(_is_blank(v) for v in r):
            continue
        out.append(_pad(r))
    return out


def write_csv_rows(rows: list[list], csv_path) -> None:
    """
    Back up tracker rows to the CSV under version control.

    output/ is gitignored because everything in it regenerates -- except the
    tracker. This copy is what survives a lost machine, so it is rewritten
    from the carried-forward tracker on every run and committed weekly. It
    is never merged back into the tracker.
    """
    p = Path(csv_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(BET_LOG_COLUMNS)
        for r in rows:
            w.writerow(["" if v is None else v for v in _pad(list(r))])


# ─────────────────────────────────────────────
# IDENTITY OF A BET
# ─────────────────────────────────────────────

_AT_RE = re.compile(r"^(\S+)\s+AT\s+(\S+)$")


def _text(v: Any) -> str:
    return "" if _is_blank(v) else str(v).strip()


def normalize_matchup(s) -> str:
    """
    'MIA @ LV', 'MIA@LV' and 'mia at lv' all become 'MIA @ LV'.

    Only case, spacing and the '@'/'at' separator are normalised. A 'vs'
    form is left alone (beyond case and spacing) because 'LV vs MIA' does
    not say who is at home, and guessing would silently mis-key the bet.
    """
    text = " ".join(_text(s).split()).upper()
    if not text:
        return ""
    if "@" in text:
        away, _, home = text.partition("@")
        return f"{away.strip()} @ {home.strip()}"
    m = _AT_RE.match(text)
    if m:
        return f"{m.group(1)} @ {m.group(2)}"
    return text


def _date_key(v: Any) -> str:
    """
    The date part of a bet's identity.

    A date typed into Excel comes back from openpyxl as a datetime, while the
    same date read from the CSV is a string; str() of the two differs, which
    would make one bet look like two. Parse first and key on ISO form; fall
    back to the trimmed text when the date does not parse.
    """
    d = _parse_date(v)
    return d.isoformat() if d is not None else _text(v)


def bet_key(row) -> tuple:
    """
    What makes a logged bet *that* bet: date, matchup, market and side.

    Two rows with the same key from different copies of the tracker are the
    same bet at different points in its life (logged, closed, settled), and
    the newer copy wins. Stake, odds and result are deliberately not part of
    the key -- they are exactly the fields that get edited.
    """
    if isinstance(row, dict):
        d, m, k, s = (row.get("date"), row.get("matchup"),
                      row.get("market"), row.get("bet_side"))
    else:
        r = _pad(list(row))
        d, m, k, s = r[0], r[2], r[3], r[4]
    return (
        _date_key(d),
        normalize_matchup(m),
        _text(k).upper(),
        " ".join(_text(s).split()).upper(),
    )


def _key_is_empty(key: tuple) -> bool:
    return all(part == "" for part in key)


# ─────────────────────────────────────────────
# THE TRACKER IS JAMESON'S: READ IT, NEVER EDIT IT
# ─────────────────────────────────────────────
#
# 2026-09-30, his words: the Bet Tracker "should only be for you to observe
# not to touch and meddle with ... it's more for me to update on my own."
#
# What this replaced: every run used to UNION every copy of the tracker (all
# weekly workbooks + the CSV mirror), newest edit winning per bet. A union
# cannot see a deletion or a correction. He deleted his Week 2 rows in the
# Week 3 workbook; the Week 4 run put them back from the Week 2 workbook and
# the CSV; he deleted them again by hand in the Week 4 workbook (Excel,
# 2026-09-30 10:36). A matchup fix ("TEN @ NY" -> "TEN @ NYG") would have
# come back as a second row.
#
# Now the tracker in the most recently saved weekly workbook IS the tracker.
# excel.build_workbook loads that file and rebuilds every other sheet around
# the tracker sheet, so it reaches the next workbook cell for cell: no row
# added, removed, reordered, merged or retyped. The CSV mirror is a backup
# that is written, never read back, unless no weekly workbook exists at all.
#
# The model still protects what he typed. A workbook about to be overwritten
# whose tracker he edited, and which is not the copy being carried forward,
# is backed up to output/backup/ first. An older week's workbook edited after
# its tracker was carried forward is reported with its rows -- the run never
# guesses which copy he meant and never merges them.

TRACKER_STATE_FILE = ".tracker_state.json"     # in output/, beside the workbooks
BACKUP_DIRNAME = "backup"                      # output/backup/


@dataclass
class TrackerSource:
    """The one copy of the tracker a run reads, and where it came from."""
    path: Optional[Path]          # the workbook (or CSV) the rows came from
    kind: str                     # "workbook", "csv" or "none"
    rows: list                    # read_tracker_rows / read_csv_rows output
    fingerprint: Optional[str]    # tracker_fingerprint(path) for a workbook


def _has_tracker(path: Path) -> bool:
    try:
        from openpyxl import load_workbook
        wb = load_workbook(str(path), read_only=True)
        try:
            return TRACKER_SHEET in wb.sheetnames
        finally:
            wb.close()
    except Exception:
        return False


def tracker_workbooks(output_dir) -> list[Path]:
    """Weekly workbooks that have a Bet Tracker sheet, most recently saved first."""
    if output_dir is None or not Path(output_dir).is_dir():
        return []
    found = [p for p in Path(output_dir).glob(WORKBOOK_GLOB)
             if not p.name.startswith("~$") and _has_tracker(p)]
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def _cell_text(v: Any) -> str:
    """A stable text form of a cell value (array formulas have no stable repr)."""
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    text = getattr(v, "text", None)             # ArrayFormula / DataTableFormula
    if text is not None:
        return f"{type(v).__name__}:{getattr(v, 'ref', '')}:{text}"
    return repr(v)


def tracker_fingerprint(path) -> Optional[str]:
    """
    A hash of every non-empty cell on the tracker sheet -- header area, the
    formula columns and anything he added past column P included. Used only
    to tell whether a copy changed; None when the file has no tracker.
    """
    import hashlib
    try:
        from openpyxl import load_workbook
        wb = load_workbook(str(path), read_only=True)
        try:
            if TRACKER_SHEET not in wb.sheetnames:
                return None
            h = hashlib.sha1()
            for r, row in enumerate(wb[TRACKER_SHEET].iter_rows(values_only=True), 1):
                for c, v in enumerate(row, 1):
                    if v is None or (isinstance(v, str) and v == ""):
                        continue
                    h.update(f"{r},{c}={_cell_text(v)}\n".encode())
            return h.hexdigest()
        finally:
            wb.close()
    except Exception:
        return None


def load_tracker(output_dir, log_path, announce: bool = True) -> TrackerSource:
    """
    The tracker as he last left it: the most recently saved weekly workbook
    that has one. Only when no workbook has a tracker (first run, lost
    output/) does the CSV backup stand in.
    """
    books = tracker_workbooks(output_dir)
    if books:
        src = books[0]
        rows = read_tracker_rows(src)
        kind, fp = "workbook", tracker_fingerprint(src)
    elif log_path is not None and Path(log_path).exists():
        src, rows, kind, fp = Path(log_path), read_csv_rows(log_path), "csv", None
    else:
        return TrackerSource(None, "none", [], None)
    if announce:
        stamp = datetime.fromtimestamp(src.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        how = "read only" if kind == "workbook" else "BACKUP -- no workbook has a tracker"
        print(f"  bet tracker: {src.name} (saved {stamp}) — {len(rows)} row(s), {how}")
    return TrackerSource(src, kind, rows, fp)


def _load_state(output_dir) -> dict:
    import json
    p = Path(output_dir) / TRACKER_STATE_FILE
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _save_state(output_dir, state: dict) -> None:
    import json
    try:
        (Path(output_dir) / TRACKER_STATE_FILE).write_text(
            json.dumps(state, indent=1, sort_keys=True))
    except Exception:
        pass


def _rows_missing(rows: list, reference: list) -> list:
    """Rows of `rows` that do not appear, exactly, in `reference`."""
    have = {tuple(_cell_text(v) for v in _pad(r)) for r in reference}
    return [r for r in rows if tuple(_cell_text(v) for v in _pad(r)) not in have]


def _describe(row) -> str:
    r = _pad(list(row))
    return " | ".join(_text(v) for v in (r[0], r[2], r[3], r[4], r[7], r[8]) if _text(v))


def protect_tracker_copies(source: TrackerSource, target, output_dir) -> list[str]:
    """
    Warnings, and backups, before `target` is written.

    Two cases lose nothing silently:
      * target exists, is not the copy being carried forward, and holds a
        tracker he edited (or one the model has no record of that differs
        from the source): copied to output/backup/ before it is replaced.
      * any other workbook whose tracker changed since the model last read or
        wrote it: named, with the rows that are not in the carried copy.
    Nothing is merged either way. Returns the warning lines to print.
    """
    if source.kind != "workbook" or output_dir is None:
        return []
    state = _load_state(output_dir)
    known = state.setdefault("known", {})
    target = Path(target)
    warnings_: list[str] = []
    reported: dict = {}
    for w in tracker_workbooks(output_dir):
        if w.resolve() == source.path.resolve():
            continue
        fp = tracker_fingerprint(w)
        edited = w.name in known and fp != known[w.name]
        overwriting = target.exists() and w.resolve() == target.resolve()
        if overwriting and (edited or (w.name not in known and fp != source.fingerprint)):
            backup_dir = Path(output_dir) / BACKUP_DIRNAME
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.fromtimestamp(w.stat().st_mtime).strftime("%Y%m%d-%H%M%S")
            dest = backup_dir / f"{w.stem}.{stamp}{w.suffix}"
            import shutil
            shutil.copy2(w, dest)
            warnings_.append(
                f"{w.name} is being rebuilt, but its Bet Tracker differs from the one "
                f"carried forward ({source.path.name}). Saved it untouched to "
                f"output/{BACKUP_DIRNAME}/{dest.name}; nothing was merged.")
        elif edited:
            extra = _rows_missing(read_tracker_rows(w), source.rows)
            msg = (f"the Bet Tracker in {w.name} was edited after the model last "
                   f"read it; this workbook carries {source.path.name} instead, "
                   f"and nothing was merged.")
            if extra:
                msg += " Rows only in " + w.name + ": " + "; ".join(
                    _describe(r) for r in extra[:6]) + (" ..." if len(extra) > 6 else "")
            warnings_.append(msg)
            # Said once per edit: the file stays different forever, and a
            # warning that repeats every run is a warning nobody reads.
            reported[w.name] = fp
    if reported:
        known.update(reported)
        _save_state(output_dir, state)
    return warnings_


def record_tracker_state(output_dir, source: TrackerSource, written) -> None:
    """Remember what each copy held when the model last read or wrote it."""
    if output_dir is None or source.kind != "workbook":
        return
    state = _load_state(output_dir)
    known = state.setdefault("known", {})
    known[source.path.name] = source.fingerprint
    fp = tracker_fingerprint(written)
    if fp is not None:
        known[Path(written).name] = fp
    # Baseline every other copy the first time it is seen, so a later edit
    # to an older week's file is noticed (protect_tracker_copies).
    for w in tracker_workbooks(output_dir):
        if w.name not in known:
            known[w.name] = tracker_fingerprint(w)
    _save_state(output_dir, state)


# ─────────────────────────────────────────────
# TYPED VIEW OF A ROW
# ─────────────────────────────────────────────

_DATE_FORMATS = (
    "%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y",
    "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%Y/%m/%d", "%m-%d-%Y",
)


def _parse_date(v: Any) -> Optional[date]:
    """M/D/YYYY, YYYY-MM-DD (with or without a time), or a date object."""
    if _is_blank(v):
        return None
    if isinstance(v, datetime):          # pandas Timestamp is a subclass
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s[:10]).date()
    except ValueError:
        return None


def _parse_float(v: Any) -> Optional[float]:
    """'-110', '+3.5', '$50', '2.5%' -> float; anything unparseable -> None."""
    if _is_blank(v):
        return None
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("−", "-")     # unicode minus
    s = s.replace("$", "").replace(",", "").replace("%", "").replace(" ", "")
    try:
        return float(s)
    except ValueError:
        return None


def _parse_int(v: Any) -> Optional[int]:
    f = _parse_float(v)
    if f is not None and math.isfinite(f):
        return int(f)
    m = re.search(r"\d+", _text(v))
    return int(m.group()) if m else None


_RESULT_ALIASES = {
    "W": "W", "WIN": "W", "WON": "W",
    "L": "L", "LOSS": "L", "LOST": "L", "LOSE": "L",
    "P": "PUSH", "PUSH": "PUSH", "TIE": "PUSH",
}


def _parse_result(v: Any) -> str:
    return _RESULT_ALIASES.get(_text(v).upper(), "")


def _resolve_side(side: str, matchup: str) -> str:
    """
    'HOME' / 'AWAY' typed as the Bet Side becomes the team, from 'AWAY @ HOME'.

    Every grader keys on the first word of the side being a team code; a bare
    HOME silently fell through to the away branch and graded the wrong team.
    """
    word, _, rest = side.partition(" ")
    if word not in ("HOME", "AWAY") or " @ " not in matchup:
        return side
    away, _, home = matchup.partition(" @ ")
    team = home if word == "HOME" else away
    return f"{team} {rest}".strip()


def parse_row(row) -> dict:
    """
    A tracker row with real types.

    The raw rows are kept exactly as he typed them (see load_tracker);
    this is the one place the strings become dates, ints and floats, so
    grading and CLV never have to guess.
    """
    r = _pad(list(row))
    matchup = normalize_matchup(r[2])
    return {
        "date": _parse_date(r[0]),
        "week": _parse_int(r[1]),
        "matchup": matchup,
        "market": _text(r[3]).upper(),
        "bet_side": _resolve_side(" ".join(_text(r[4]).split()).upper(), matchup),
        "line_taken": _parse_float(r[5]),
        "odds": _parse_float(r[6]),
        "stake": _parse_float(r[7]),
        "result": _parse_result(r[8]),
        "closing_line": _parse_float(r[9]),
        "closing_odds": _parse_float(r[10]),
        "model_edge": _parse_float(r[11]),
    }


# ─────────────────────────────────────────────
# CLOSING LINE VALUE
# ─────────────────────────────────────────────

def _per_point(line: float, pts_table) -> float:
    """Probability value of one point at this line; exact match on |line|."""
    if pts_table:
        target = abs(float(line))
        for entry in pts_table:
            try:
                L, per_pt = float(entry[0]), float(entry[1])
            except (TypeError, ValueError, IndexError):
                continue
            if abs(L - target) < 1e-9:
                return per_pt
    return DEFAULT_PER_PT


def clv_for_row(parsed: dict, pts_table=None) -> tuple:
    """
    (clv_pts, clv_prob) for one parsed tracker row, matching the workbook.

    Spread: both numbers are quoted from the bettor's side, so taken minus
    close is signed correctly (+3.5 taken vs +1.5 close = +2.0). Points
    convert to probability through the per-line table because the point
    that crosses 3 is worth about four times a point at 2; the lookup is on
    the line taken, exactly as the sheet's VLOOKUP is.

    Moneyline: points are meaningless, so clv_pts is None and clv_prob is
    the difference in implied probability between the close and the price
    taken. (None, None) whenever an input is missing.
    """
    market = str(parsed.get("market") or "").upper()
    if market == "SPREAD":
        taken, close = parsed.get("line_taken"), parsed.get("closing_line")
        if taken is None or close is None:
            return (None, None)
        pts = float(taken) - float(close)
        return (pts, pts * _per_point(taken, pts_table))
    if market == "MONEYLINE":
        odds, close = parsed.get("odds"), parsed.get("closing_odds")
        if odds is None or close is None:
            return (None, None)
        return (None, float(closing_line_value(odds, close)))
    return (None, None)
