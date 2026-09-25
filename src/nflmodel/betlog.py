"""
betlog.py — reading, merging and typing the hand-entered Bet Tracker.

The Bet Tracker is the one thing in this repo that cannot be regenerated.
Everything else rebuilds from nflverse; the numbers Jameson actually saw, the
stakes he would have risked and the results he settled exist nowhere else.
And it lives in several places at once: the "Bet Tracker" sheet of every
weekly workbook under output/, plus the CSV mirror at data/bet_log.csv that
is committed so a dead laptop does not take the record with it.

The bug this module exists to fix
----------------------------------
build_workbook used to do

    preserved = read_existing_bets(path) or import_bet_log(log_path)

where `path` is the CURRENT week's workbook. On the first run of Week 2 that
file does not exist yet, so it fell through to the CSV -- which was last
written at the END of the previous script run. Anything typed into the Week 1
workbook after that run (the normal case: log Wednesday, settle Monday, run
Week 2 on Tuesday) was silently absent from the Week 2 workbook. Quiet,
total, and only noticed later -- the worst possible failure for a bet log.

The fix is to stop guessing which copy is authoritative. Read every copy,
identify each bet by what it *is* (date, matchup, market, side) rather than
by where it sits, and let the most recently modified file win per bet. A row
that exists only in an older copy is kept, not dropped.

This module also owns the typed view of a tracker row (parse_row) and the
CLV arithmetic (clv_for_row), so that history.py can grade bets in Python
exactly the way the workbook's formulas grade them in Excel.
"""

from __future__ import annotations

import csv
import math
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

from .market import closing_line_value

# Identical to the header excel.py writes. excel.py will import it from here.
BET_LOG_COLUMNS = [
    "date", "week", "matchup", "market", "bet_side", "line_taken", "odds",
    "stake", "result", "closing_line", "closing_odds", "model_edge",
]

# Layout of the Bet Tracker sheet, as built by excel._sheet_tracker. Headers
# sit on row 11; the user types into rows 12..500. Columns A..I are the
# hand-entered fields, J/K/N/O are formulas rewritten every run, and L, M, P
# (closing line, closing odds, model edge) are hand-entered too.
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
    Mirror tracker rows to the CSV under version control.

    output/ is gitignored because everything in it regenerates -- except the
    tracker. This copy is what survives a lost machine, so it is written on
    every run and committed weekly.
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
# COLLECTING FROM EVERY COPY
# ─────────────────────────────────────────────

def collect_preserved_bets(path, output_dir, log_path) -> list[list]:
    """
    Union of every copy of the tracker, newest edit winning per bet.

    Sources are the current week's workbook (if it exists), every other
    NFL_Model_*_Week*.xlsx under output_dir, and the CSV mirror. They are
    walked in descending mtime order and the first sighting of each bet_key
    is kept, so a row edited in the most recently saved file beats older
    copies while a row that exists only in an old copy still survives.

    Output order: the newest source's rows as they were, then rows the older
    sources add, in the order they appear there. Values are returned exactly
    as read -- no coercion, so a workbook cell that was a number stays a
    number and a CSV cell stays a string.

    One line is printed per source so the run shows where the rows came from.
    Returns [] when no source has anything.
    """
    candidates: list[Path] = []
    if path is not None and Path(path).exists():
        candidates.append(Path(path))
    if output_dir is not None and Path(output_dir).is_dir():
        candidates.extend(sorted(Path(output_dir).glob(WORKBOOK_GLOB)))
    if log_path is not None and Path(log_path).exists():
        candidates.append(Path(log_path))

    seen_paths: set = set()
    sources: list[Path] = []
    for p in candidates:
        rp = p.resolve()
        if rp in seen_paths:
            continue
        seen_paths.add(rp)
        sources.append(p)

    # Stable sort: ties keep the candidate order (current workbook first).
    sources.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    merged: list[list] = []
    seen_keys: set = set()
    for p in sources:
        rows = (read_csv_rows(p) if p.suffix.lower() == ".csv"
                else read_tracker_rows(p))
        stamp = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        print(f"  bet log: {p.name} (modified {stamp}) — {len(rows)} row(s)")
        for row in rows:
            k = bet_key(row)
            # A row with no identifying fields at all cannot be matched to
            # anything, so it is never treated as a duplicate.
            if not _key_is_empty(k):
                if k in seen_keys:
                    continue
                seen_keys.add(k)
            merged.append(row)
    return merged


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

    The raw rows are kept untyped on purpose (see collect_preserved_bets);
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
