"""
excel.py — builds the NFL_Betting_Model workbook.

Visual language deliberately matches the MLB workbook: navy headers, yellow
input cells, gray calculated cells, green/red conditional formatting on edges.
Structure differs because NFL is a weekly sport -- the primary sheet is a slate
of ~16 games ranked by edge, not a single-game form.

Sheets, in tab order:

  This Week's Bets    the bets, split: on the model's pick vs value against it
  Picks               every game as a straight-up winner, most confident first
  Weekly Slate        every game: date, prices, model line, edge, verdict
  Model Picks %       model win probability vs the de-vigged market, per side
  Game Detail         a matchup picker -- choose a game, see what drives it
  Team Stats          record, point differential, roster and injured list
  Power Ratings       the fitted ratings
  Bet Tracker         hand-entered bets, CLV, P&L (persists across runs)
  Bet Log             every pick and lean ever published, graded
  Rosters, Injuries   the player-level detail behind Team Stats
  Reference & Glossary
  (hidden) Lists, Model Data -- lookup tables the formulas read

Every tabular sheet has a frozen header row and a filter. The workbook never
presents a lean as more than the validation supports: the hold-out verdict is
on the Reference sheet and in a banner on every sheet that shows an edge.
"""

from __future__ import annotations

import math
from datetime import date, datetime

import pandas as pd
from openpyxl import Workbook
from openpyxl.formatting.rule import ColorScaleRule, DataBarRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from .betlog import (BET_LOG_COLUMNS, collect_preserved_bets, read_csv_rows,
                     read_tracker_rows, write_csv_rows)
from .config import OUTPUT_DIR, REPO_ROOT, STAKING
from .data import TEAMS
from .market import format_spread

# ── Colors (same palette as the MLB model) ──
NAVY = "1B2A4A"
WHITE = "FFFFFF"
GREEN = "2E7D32"
LIGHT_YELLOW = "FFFDE7"
LIGHT_GRAY = "F5F5F5"
LIGHT_GREEN = "C8E6C9"
LIGHT_RED = "FFCDD2"
LIGHT_ORANGE = "FFE0B2"
GRAY_BLUE = "607D8B"
DARK_GOLD = "F9A825"
ROW_TINT = "EEF2F7"
LABEL_FILL = "E8EDF3"
LEAN_FILL = "FFECB3"
LEAN_TEXT = "7A5C00"
MID_GREEN = "81C784"
MID_RED = "EF9A9A"
MUTED = "757575"
BAR_BLUE = "90CAF9"

# The hold-out verdict, quoted on the sheets that show an edge. These are the
# README's numbers; they are here so the workbook cannot drift into
# presenting picks as more confident than the validation supports.
HOLDOUT = {
    "seasons": "2021-25 hold-out, n = 1,424",
    "bare_ats": "48.6% ATS, −7.3% ROI at a 1.5-pt edge (bare ratings)",
    "deployed_ats": "50.1% ATS, −4.3% ROI at a 1.5-pt edge (deployed model, with market prior)",
    "ml": "38.8%, −9.5% ROI on moneylines at a 3% edge",
    "mae": "MAE 10.08 vs the closing line's 9.76",
    "coef": "incremental coefficient vs the line −0.018 (t = −0.1): zero information beyond the line",
    "breakeven": "break-even at −110 is 52.38%",
}


def fill(hex_color):
    return PatternFill(fill_type="solid", fgColor=hex_color)


def font(bold=False, color=WHITE, size=11, italic=False):
    return Font(bold=bold, color=color, size=size, italic=italic)


def thin_border():
    s = Side(style="thin", color="CCCCCC")
    return Border(left=s, right=s, top=s, bottom=s)


def center():
    return Alignment(horizontal="center", vertical="center", wrap_text=True)


def left():
    return Alignment(horizontal="left", vertical="center", wrap_text=True)


def top_left():
    return Alignment(horizontal="left", vertical="top", wrap_text=True)


def apply_header(ws, ref, text, merge_to=None, size=16):
    c = ws[ref]
    c.value, c.fill, c.font, c.alignment = text, fill(NAVY), font(True, WHITE, size), center()
    if merge_to:
        ws.merge_cells(f"{ref}:{merge_to}")


def apply_section(ws, ref, text, merge_to=None):
    c = ws[ref]
    c.value, c.fill, c.font, c.alignment = text, fill(NAVY), font(True, WHITE, 11), left()
    if merge_to:
        ws.merge_cells(f"{ref}:{merge_to}")


def set_widths(ws, widths: dict):
    for col, w in widths.items():
        ws.column_dimensions[col].width = w


def _header_row(ws, row, labels, start_col=1):
    for i, label in enumerate(labels):
        c = ws.cell(row=row, column=start_col + i, value=label)
        c.fill, c.font, c.alignment, c.border = fill(NAVY), font(True, WHITE, 11), center(), thin_border()
    ws.row_dimensions[row].height = 24


def _banner(ws, row, text, merge_to, color=GREEN, italic=True, size=10, height=None):
    """A one-line note under a title: the advisory framing, a data caveat."""
    c = ws.cell(row=row, column=1, value=_safe_text(text))
    c.font = Font(italic=italic, color=color, size=size)
    c.alignment = left()
    ws.merge_cells(f"A{row}:{merge_to}{row}")
    if height:
        ws.row_dimensions[row].height = height


def _label_value(ws, row, col, label, value, fmt=None, bold_label=False, value_font=None):
    """A 'label | value' pair, the form-style cell used on the picker."""
    lc = ws.cell(row=row, column=col, value=_safe_text(label))
    lc.font = Font(bold=bold_label, color="000000", size=11)
    lc.fill, lc.border, lc.alignment = fill(LABEL_FILL), thin_border(), left()
    vc = ws.cell(row=row, column=col + 1, value=value)
    vc.font = value_font or Font(bold=True, color=NAVY, size=11)
    vc.alignment, vc.border, vc.fill = center(), thin_border(), fill(LIGHT_GRAY)
    if fmt:
        vc.number_format = fmt
    return vc


# Excel reads a leading =, +, - or @ as the start of a formula, so a caption
# that opens with one is stored as a broken formula rather than text. This
# shipped once: the "= rating net + QB net + ..." note under PROJECTED MARGIN
# evaluated to #REF!. Every string the builder writes goes through here.
_FORMULA_LEAD = ("=", "+", "-", "@")


def _safe_text(s: str) -> str:
    """A string Excel will treat as text, not as a formula."""
    return s if not s[:1] in _FORMULA_LEAD else "'" + s


def _clean(v):
    """
    An Excel-safe scalar.

    openpyxl writes float NaN as the text 'nan' and chokes on some numpy and
    pandas scalars; every value written from a DataFrame goes through here so
    a missing number is a blank cell and a Timestamp is a date.
    """
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return _safe_text(v)
    if isinstance(v, int):
        return v
    if isinstance(v, pd.Timestamp):
        return None if pd.isna(v) else v.to_pydatetime()
    if isinstance(v, (datetime, date)):
        return v
    if hasattr(v, "item"):                       # numpy scalar
        try:
            v = v.item()
        except Exception:
            pass
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, (float, int, str, bool, datetime, date)):
        return v
    try:
        if pd.isna(v):
            return None
    except Exception:
        pass
    return str(v)


def _num(v):
    """float or None."""
    v = _clean(v)
    if v is None or isinstance(v, (str, datetime, date)):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def _text(v) -> str:
    v = _clean(v)
    return "" if v is None else str(v)


def _kickoff(weekday, gametime) -> str:
    """'Sun 1:00 PM' from the game file's weekday and 24h gametime."""
    wd = _text(weekday)[:3]
    t = _text(gametime)
    if ":" in t:
        try:
            h, m = t.split(":")[:2]
            h, m = int(h), int(m)
            t = f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"
        except ValueError:
            pass
    return " ".join(x for x in (wd, t) if x)


def _as_date(v):
    v = _clean(v)
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str) and v:
        try:
            return datetime.fromisoformat(v[:10]).date()
        except ValueError:
            return None
    return None


def _write_table(ws, top, headers, rows, *, formats=None, aligns=None, bold_cols=(),
                 zebra=True, freeze=True, autofilter=True, fonts=None):
    """
    A header row at `top` and the data under it, styled as a table.

    Returns the last data row (== top when there are no rows). Sets the
    freeze pane under the header and the filter over the whole table, which
    is what every tabular sheet in the workbook wants.
    """
    _header_row(ws, top, headers)
    formats, aligns, fonts = formats or {}, aligns or {}, fonts or {}
    for i, rec in enumerate(rows, start=1):
        r = top + i
        for j, v in enumerate(rec, start=1):
            c = ws.cell(row=r, column=j, value=_clean(v))
            c.border = thin_border()
            a = aligns.get(j)
            c.alignment = left() if a == "left" else (top_left() if a == "top" else center())
            c.font = fonts.get(j) or Font(color="000000", size=11, bold=(j in bold_cols))
            if zebra and i % 2 == 0:
                c.fill = fill(ROW_TINT)
            fmt = formats.get(j)
            if fmt:
                c.number_format = fmt
    last = top + len(rows)
    if autofilter and headers:
        ws.auto_filter.ref = f"A{top}:{get_column_letter(len(headers))}{max(last, top + 1)}"
    if freeze:
        ws.freeze_panes = f"A{top + 1}"
    return last


def _fit_row_heights(ws, first, last, wrap_cols: dict, min_height=18, max_height=210):
    """
    Rough row heights for wrapped text. openpyxl cannot ask Excel to autofit,
    so this estimates lines from the text length and the column width.
    """
    for r in range(first, last + 1):
        lines = 1
        for col, width in wrap_cols.items():
            v = ws.cell(row=r, column=col).value
            if isinstance(v, str) and v:
                per_line = max(8, int(width * 1.15))
                seg_lines = sum(max(1, math.ceil(len(seg) / per_line)) for seg in v.split("\n"))
                lines = max(lines, seg_lines)
        ws.row_dimensions[r].height = max(min_height, min(max_height, 15 * lines + 3))


# ─────────────────────────────────────────────
# BUILD
# ─────────────────────────────────────────────

# Backward-compatible names; the implementations moved to betlog.py so the
# bet log can be read, merged and typed without importing the workbook code.
def export_bet_log(rows: list[list], path) -> None:
    write_csv_rows(rows, path)


def import_bet_log(path) -> list[list]:
    return read_csv_rows(path)


def read_existing_bets(path: str) -> list[list]:
    return read_tracker_rows(path)


def build_workbook(
    slate: pd.DataFrame,
    ratings: pd.DataFrame,
    season: int,
    week: int,
    backtest_summary: dict | None = None,
    path: str = "NFL_Betting_Model.xlsx",
    pts_table: list | None = None,
    ranked: pd.DataFrame | None = None,
    starters: dict | None = None,
    qb_source: dict | None = None,
    team_stats: dict | None = None,
    games: pd.DataFrame | None = None,
    model_meta: dict | None = None,
    trends_state: dict | None = None,
) -> str:
    log_path = REPO_ROOT / "data" / "bet_log.csv"
    model_meta = model_meta or {}

    # Every copy of the tracker, newest edit winning per bet. The old code
    # read only the current week's file and fell back to the CSV, which lost
    # anything typed into last week's workbook after its final run.
    preserved = collect_preserved_bets(path, OUTPUT_DIR, log_path)

    # Graded history of every archived pick. Derived data: a failure here is
    # a WARNING and an empty sheet, never a lost slate.
    history = None
    try:
        from .history import build_history
        history = build_history(games, preserved, pts_table=pts_table) if games is not None else None
    except Exception as exc:                          # noqa: BLE001
        print(f"WARNING: bet log history unavailable ({type(exc).__name__}: {exc})")

    wb = Workbook()

    _sheet_lists(wb, pts_table)
    _sheet_bets(wb, slate, season, week, model_meta)
    if ranked is not None:
        _sheet_picks(wb, ranked, season, week, starters, qb_source)
    slate_last = _sheet_slate(wb, slate, season, week, model_meta)
    _sheet_model_picks(wb, slate, season, week, model_meta)
    _sheet_detail(wb, slate, season, week, slate_last, model_meta)
    _sheet_team_stats(wb, team_stats, season, week)
    _sheet_ratings(wb, ratings, season, week)
    _sheet_tracker(wb, preserved)
    _sheet_history(wb, history, season, week)
    _sheet_miss_report(wb, trends_state)
    _sheet_rosters(wb, team_stats)
    _sheet_injuries(wb, team_stats)
    _sheet_reference(wb, backtest_summary, model_meta)
    _sheet_model_data(wb, slate)

    # Open on a visible sheet. A hidden active sheet makes Excel repair the file.
    for ws in wb.worksheets:
        ws.sheet_view.tabSelected = False
    first = "This Week's Bets"
    wb.active = wb.sheetnames.index(first)
    wb[first].sheet_view.tabSelected = True

    wb.save(path)
    write_csv_rows(preserved, log_path)
    return path


# ─────────────────────────────────────────────
# HIDDEN LOOKUP SHEETS
# ─────────────────────────────────────────────

def _sheet_lists(wb, pts_table=None):
    ws = wb.active
    ws.title = "Lists"
    ws.sheet_state = "hidden"
    for i, t in enumerate(TEAMS, start=1):
        ws.cell(row=i, column=1, value=t)
    for i, v in enumerate(["W", "L", "Push"], start=1):
        ws.cell(row=i, column=2, value=v)

    # Columns D:E — win-probability value of one point of spread, by line.
    # Used by the tracker to convert points of CLV into probability. This is a
    # lookup rather than a constant because the point crossing 3 is worth four
    # times a point at 2.
    for i, (line, per_pt) in enumerate(pts_table or [], start=1):
        ws.cell(row=i, column=4, value=line)
        ws.cell(row=i, column=5, value=per_pt)


# One row per game, every number the picker can show. Keys are slate columns
# or derived from them; the header is what a curious reader sees if they
# unhide the sheet. The ORDER is what the picker's formulas depend on.
MODEL_DATA_COLS = [
    ("matchup", "Matchup"), ("game_id", "Game id"), ("away_team", "Away"),
    ("home_team", "Home"), ("gameday", "Date"), ("kickoff", "Kickoff (ET)"),
    ("stadium", "Stadium"), ("roof", "Roof"), ("site", "Site"),
    ("spread_line", "Spread line (home favored by)"), ("vegas_line", "Vegas line"),
    ("total_line", "Total"), ("home_ml", "Home ML"), ("away_ml", "Away ML"),
    ("home_spread_odds", "Home spread juice"), ("away_spread_odds", "Away spread juice"),
    ("over_odds", "Over odds"), ("under_odds", "Under odds"),
    ("projected_margin", "Projected margin (home − away)"), ("fair_spread", "Fair spread"),
    ("model_line", "Model line"), ("spread_edge_pts", "Edge (pts)"),
    ("situational_adj", "Situational adj"),
    ("selftune_adj", "Self-tune adj"), ("trend_adj", "Trend fixes adj"),
    ("trend_notes", "Trend fixes"), ("wx_label", "Weather (forecast)"),
    ("home_cover_prob", "Home cover %"), ("push_prob", "Push %"),
    ("away_cover_prob", "Away cover %"), ("model_side", "Model side (spread)"),
    ("model_side_cover", "Model side cover %"),
    ("home_win_prob", "Home win %"), ("away_win_prob", "Away win %"),
    ("home_ml_fair", "Home fair ML"), ("away_ml_fair", "Away fair ML"),
    ("ml_edge_home", "ML edge home"), ("ml_edge_away", "ML edge away"),
    ("market_home_prob", "Market home % (de-vigged)"),
    ("market_away_prob", "Market away % (de-vigged)"), ("vig_pct", "Vig %"),
    ("home_team_rating", "Home team rating"), ("away_team_rating", "Away team rating"),
    ("home_qb", "Home QB"), ("away_qb", "Away QB"),
    ("home_qb_adj", "Home QB adj"), ("away_qb_adj", "Away QB adj"),
    ("home_qb_note", "Home QB note"), ("away_qb_note", "Away QB note"),
    ("home_strength", "Home strength"), ("away_strength", "Away strength"),
    ("hfa_used", "Home field"), ("market_prior_weight", "Market prior weight"),
    ("recommendation", "Recommendation"), ("bet_market", "Market"),
    ("bet_side", "Side"), ("bet_odds", "Odds"), ("stake", "Stake"),
    ("confidence", "Confidence"),
    ("projected_winner", "Projected winner"), ("winner_prob", "Winner win %"),
    ("winner_margin", "Winner margin"), ("market_favorite", "Market favorite"),
    ("agree", "Model agrees with market"),
]
MD_COL = {key: get_column_letter(i + 1) for i, (key, _) in enumerate(MODEL_DATA_COLS)}


def _model_rows(slate: pd.DataFrame) -> list[dict]:
    """Derive every Model Data field from a slate row; missing inputs stay blank."""
    out = []
    for _, g in slate.iterrows():
        d = g.to_dict()
        home, away = d["home_team"], d["away_team"]
        line = _num(d.get("spread_line"))
        fair = _num(d.get("fair_spread"))
        pm = _num(d.get("projected_margin"))
        hwp = _num(d.get("home_win_prob"))
        edge = _num(d.get("spread_edge_pts"))
        hcp, acp = _num(d.get("home_cover_prob")), _num(d.get("away_cover_prob"))

        if hwp is not None:
            home_fav = hwp >= 0.5
        else:
            home_fav = (pm or 0.0) >= 0
        winner = home if home_fav else away
        winner_prob = None if hwp is None else (hwp if home_fav else 1.0 - hwp)
        winner_margin = None if pm is None else (pm if home_fav else -pm)

        if line is None:
            mkt_fav = ""
        elif line > 0:
            mkt_fav = home
        elif line < 0:
            mkt_fav = away
        else:
            mkt_fav = "pick'em"
        agree = "" if not mkt_fav else ("YES" if mkt_fav in (winner, "pick'em") else "NO")

        if edge is None or line is None:
            side, side_cover = "", None
        elif edge > 0:
            side, side_cover = home, hcp
        else:
            side, side_cover = away, acp

        def qb_note(known, name):
            if not name:
                return "unknown — replacement level"
            return "rated" if known else "no rating yet — replacement level"

        row = {
            "matchup": f"{away} @ {home}",
            "game_id": _text(d.get("game_id")),
            "away_team": away, "home_team": home,
            "gameday": _as_date(d.get("gameday")),
            "kickoff": _kickoff(d.get("weekday"), d.get("gametime")),
            "stadium": _text(d.get("stadium")), "roof": _text(d.get("roof")),
            "site": "neutral site" if bool(_clean(d.get("neutral")) or False) else f"{home} home",
            "spread_line": line,
            "vegas_line": format_spread(home, line) if line is not None else "—",
            "total_line": _num(d.get("total_line")),
            "home_ml": _num(d.get("home_ml")), "away_ml": _num(d.get("away_ml")),
            "home_spread_odds": _num(d.get("home_spread_odds")),
            "away_spread_odds": _num(d.get("away_spread_odds")),
            "over_odds": _num(d.get("over_odds")), "under_odds": _num(d.get("under_odds")),
            "projected_margin": pm, "fair_spread": fair,
            "model_line": format_spread(home, fair) if fair is not None else "—",
            "spread_edge_pts": edge,
            "situational_adj": _num(d.get("situational_adj")),
            "selftune_adj": _num(d.get("selftune_adj")) or 0.0,
            "trend_adj": _num(d.get("trend_adj")) or 0.0,
            "trend_notes": _text(d.get("trend_notes")),
            "wx_label": _text(d.get("wx_label")),
            "home_cover_prob": hcp, "push_prob": _num(d.get("push_prob")),
            "away_cover_prob": acp, "model_side": side, "model_side_cover": side_cover,
            "home_win_prob": hwp, "away_win_prob": None if hwp is None else 1.0 - hwp,
            "home_ml_fair": _num(d.get("home_ml_fair")), "away_ml_fair": _num(d.get("away_ml_fair")),
            "ml_edge_home": _num(d.get("ml_edge_home")), "ml_edge_away": _num(d.get("ml_edge_away")),
            "market_home_prob": _num(d.get("market_home_prob")),
            "market_away_prob": _num(d.get("market_away_prob")),
            "vig_pct": _num(d.get("vig_pct")),
            "home_team_rating": _num(d.get("home_team_rating")),
            "away_team_rating": _num(d.get("away_team_rating")),
            "home_qb": _text(d.get("home_qb") or d.get("home_qb_name")),
            "away_qb": _text(d.get("away_qb") or d.get("away_qb_name")),
            "home_qb_adj": _num(d.get("home_qb_adj")), "away_qb_adj": _num(d.get("away_qb_adj")),
            "home_qb_note": qb_note(bool(_clean(d.get("home_qb_known")) or False),
                                    _text(d.get("home_qb") or d.get("home_qb_name"))),
            "away_qb_note": qb_note(bool(_clean(d.get("away_qb_known")) or False),
                                    _text(d.get("away_qb") or d.get("away_qb_name"))),
            "home_strength": _num(d.get("home_strength")), "away_strength": _num(d.get("away_strength")),
            "hfa_used": _num(d.get("hfa_used")),
            "market_prior_weight": _num(d.get("market_prior_weight")),
            "recommendation": _text(d.get("recommendation")),
            "bet_market": _text(d.get("bet_market")), "bet_side": _text(d.get("bet_side")),
            "bet_odds": _num(d.get("bet_odds")) or None, "stake": _num(d.get("stake")) or 0.0,
            "confidence": _text(d.get("confidence")),
            "projected_winner": winner, "winner_prob": winner_prob,
            "winner_margin": winner_margin, "market_favorite": mkt_fav, "agree": agree,
        }
        out.append(row)
    return out


def _sheet_model_data(wb, slate):
    """The picker's lookup table: one row per game, raw values, hidden."""
    ws = wb.create_sheet("Model Data")
    ws.sheet_state = "hidden"
    for j, (_, header) in enumerate(MODEL_DATA_COLS, start=1):
        ws.cell(row=1, column=j, value=header).font = Font(bold=True, size=10)
    for i, row in enumerate(_model_rows(slate), start=2):
        for j, (key, _) in enumerate(MODEL_DATA_COLS, start=1):
            ws.cell(row=i, column=j, value=_clean(row.get(key)))
    ws.cell(row=1, column=len(MODEL_DATA_COLS) + 2,
            value="Hidden. Read by the Game Detail picker via INDEX/MATCH on column A. "
                  "Regenerated every run; do not edit.")


# ─────────────────────────────────────────────
# PICKS
# ─────────────────────────────────────────────

BETS_HEADERS = ["Game", "Kickoff", "Bet", "Market", "Odds", "Stake", "Model Picks", "Win Chance",
                "Why"]


def _sheet_bets(wb, slate, season, week, model_meta):
    """
    The week's bets in two plain lists: bets on the team the model picks to
    win, and value bets on the other team at a price the model thinks is too
    generous. Each carries a one-line reason saying what has to happen.
    """
    from .model import WITH_PICK, AGAINST_PICK
    ws = wb.create_sheet("This Week's Bets")
    ws.tab_color = GREEN
    set_widths(ws, {"A": 13, "B": 13, "C": 15, "D": 11, "E": 8, "F": 8, "G": 12, "H": 11, "I": 90})
    lastc = get_column_letter(len(BETS_HEADERS))
    apply_header(ws, "A1", f"THIS WEEK'S BETS — {season} WEEK {week}", merge_to=f"{lastc}1", size=16)
    ws.row_dimensions[1].height = 30
    _banner(ws, 2, _advisory_banner(model_meta), lastc, height=32)

    active = (slate[slate["recommendation"].astype(str).str.match(r"^(LEAN|BET) ")]
              if "recommendation" in slate.columns else slate.iloc[0:0])
    row = 4
    for title, kind, blurb, color in (
        ("BETS ON THE MODEL'S PICK", WITH_PICK,
         "The team the model expects to win, at a price it likes.", GREEN),
        ("VALUE BETS AGAINST THE PICK", AGAINST_PICK,
         "The model still expects the OTHER team to win — but thinks this price pays more than "
         "the real chance deserves. These lose more often and are sized to match.", "E65100"),
    ):
        apply_section(ws, f"A{row}", title, merge_to=f"{lastc}{row}")
        ws.cell(row=row + 1, column=1, value=blurb).font = Font(italic=True, color=color, size=10)
        ws.merge_cells(start_row=row + 1, start_column=1, end_row=row + 1, end_column=len(BETS_HEADERS))
        _header_row(ws, row + 2, BETS_HEADERS)
        group = (active[active["bet_type"] == kind]
                 if len(active) and "bet_type" in active.columns else active.iloc[0:0])
        r = row + 3
        if group.empty:
            ws.cell(row=r, column=1, value="None this week.").font = Font(italic=True, color=MUTED)
            r += 1
        for _, g in group.iterrows():
            d = g.to_dict()
            home, away = d["home_team"], d["away_team"]
            hwp = _num(d.get("home_win_prob")) or 0.5
            pick, wp = (home, hwp) if hwp >= 0.5 else (away, 1 - hwp)
            vals = [f"{away} @ {home}", _kickoff(d.get("weekday"), d.get("gametime")),
                    _text(d.get("bet_side")), _text(d.get("bet_market")).title(),
                    _num(d.get("bet_odds")), _num(d.get("stake")), pick, wp, _text(d.get("bet_why"))]
            for j, v in enumerate(vals, start=1):
                c = ws.cell(row=r, column=j, value=_clean(v))
                c.border = thin_border()
                c.alignment = left() if j == 9 else center()
                c.font = Font(bold=(j == 3), size=11, color=color if j == 3 else "000000")
            ws.cell(row=r, column=5).number_format = "+0;-0"
            ws.cell(row=r, column=6).number_format = '"$"#,##0'
            ws.cell(row=r, column=8).number_format = "0%"
            r += 1
        row = r + 1

    n_bets = len(active)
    staked = float(active["stake"].sum()) if n_bets and "stake" in active.columns else 0.0
    ws.cell(row=row, column=1, value=f"{n_bets} bet(s), ${staked:,.0f} total. Re-run Sunday morning "
                                     "with --refresh before placing anything: starters and lines move."
            ).font = Font(bold=True, color=NAVY, size=11)
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=len(BETS_HEADERS))
    ws.freeze_panes = "A4"


def _sheet_picks(wb, ranked, season, week, starters=None, qb_source=None):
    """
    Straight-up winners, most confident first, plus the quarterback each
    projection assumed.

    The starters block is not decoration. Every number on this sheet moves if
    a quarterback is wrong, and a wrong one is invisible unless it is printed.
    """
    ws = wb.create_sheet("Picks")
    ws.tab_color = DARK_GOLD
    set_widths(ws, {"A": 6, "B": 10, "C": 10, "D": 22, "E": 10, "F": 12,
                    "G": 10, "H": 13, "I": 14})

    apply_header(ws, "A1", f"PREDICTED WINNERS — {season} WEEK {week}",
                 merge_to="I1", size=16)
    ws.row_dimensions[1].height = 30
    _banner(ws, 2, "Who the model thinks wins, not where it thinks the price is wrong. "
                   "Win % is the model's probability; early in the season most of it is "
                   "inherited from the market.", "I", height=30)

    _header_row(ws, 3, ["#", "Pick", "Over", "Matchup", "Win %",
                        "Margin", "ML", "Confidence", "vs Market"])
    ws.freeze_panes = "A4"

    for i, (_, g) in enumerate(ranked.iterrows(), start=1):
        r = 3 + i
        vals = [
            int(g["rank"]), g["winner"], g["loser"], g["matchup"],
            float(g["win_prob"]), float(g["proj_margin"]), int(g["moneyline"]),
            g["confidence"],
            "favorite" if g["market_favorite"] else "UNDERDOG",
        ]
        for j, v in enumerate(vals, start=1):
            c = ws.cell(row=r, column=j, value=v)
            c.border = thin_border()
            c.alignment = left() if j == 4 else center()
            c.font = Font(color="000000", size=11)
            if i % 2 == 0:
                c.fill = fill(ROW_TINT)
        ws.cell(row=r, column=2).font = Font(bold=True, size=11)
        ws.cell(row=r, column=5).number_format = "0.0%"
        ws.cell(row=r, column=6).number_format = "+0.0;-0.0"
        ws.cell(row=r, column=7).number_format = "+0;-0"

    last = 3 + len(ranked)
    ws.auto_filter.ref = f"A3:I{max(last, 4)}"
    if last > 3:
        conf = f"H4:H{last}"
        ws.conditional_formatting.add(conf, FormulaRule(
            formula=['H4="strong"'], fill=fill(LIGHT_GREEN),
            font=Font(bold=True, color="1B5E20")))
        ws.conditional_formatting.add(conf, FormulaRule(
            formula=['H4="coin flip"'], fill=fill(LIGHT_GRAY),
            font=Font(color="616161")))
        ws.conditional_formatting.add(f"I4:I{last}", FormulaRule(
            formula=['I4="UNDERDOG"'], fill=fill(LIGHT_ORANGE),
            font=Font(bold=True, color="E65100")))
        ws.conditional_formatting.add(f"E4:E{last}", DataBarRule(
            start_type="num", start_value=0.5, end_type="num", end_value=1.0,
            color=BAR_BLUE, showValue=True))

    n = last + 2
    ws.cell(row=n, column=1,
            value="→ Confidence is win probability, which early in the season is "
                  "mostly inherited from the market. The most confident pick is "
                  "usually the worst bet — see Weekly Slate for where the model "
                  "actually disagrees with the price.")
    ws.cell(row=n, column=1).font = Font(italic=True, color=GREEN, size=10)
    ws.merge_cells(start_row=n, start_column=1, end_row=n, end_column=9)

    if not starters:
        return

    n += 2
    apply_section(ws, f"A{n}", "ASSUMED STARTING QUARTERBACKS", merge_to=f"I{n}")
    _header_row(ws, n + 1, ["Team", "Starting QB", "Source"])
    for k, team in enumerate(sorted(starters), start=1):
        r = n + 1 + k
        for j, v in enumerate([team, starters[team],
                               (qb_source or {}).get(team, "—")], start=1):
            c = ws.cell(row=r, column=j, value=v)
            c.border = thin_border()
            c.alignment = center() if j == 1 else left()
            c.font = Font(color="000000", size=11)
            if k % 2 == 0:
                c.fill = fill(ROW_TINT)


# ─────────────────────────────────────────────
# WEEKLY SLATE
# ─────────────────────────────────────────────

SLATE_HEADERS = ["#", "Date", "Kickoff (ET)", "Matchup", "Away", "Home", "Away ML", "Home ML",
                 "Spread (Vegas)", "Juice H / A", "Total", "Model Line", "Edge (pts)",
                 "Model Side", "Side Cover %", "Push %", "Home Win %", "Conf",
                 "Recommendation", "Odds", "Stake", "Weather (forecast)", "Trend fixes"]
SLATE_MATCHUP_COL = "D"        # the picker's dropdown reads this column
SLATE_EDGE_COL = "M"
SLATE_REC_COL = "S"
SLATE_LAST_COL = get_column_letter(len(SLATE_HEADERS))


def _advisory_banner(model_meta) -> str:
    if model_meta.get("advisory", True):
        return ("ADVISORY MODE — LEANs, $0 staked. The hold-out backtest (2021-25) found no "
                f"edge against closing lines: {HOLDOUT['bare_ats']}; deployed model "
                "50.1%, −4.3% ROI. Read an edge as a disagreement worth logging for CLV, "
                "not as a bet. Full verdict on Reference & Glossary.")
    return ("LIVE STAKING — ADVISORY_MODE is off in config.py. The hold-out backtest still "
            f"shows no edge against closing lines ({HOLDOUT['bare_ats']}). Stakes are "
            "half-Kelly, capped; see Reference & Glossary.")


def _sheet_slate(wb, slate, season, week, model_meta) -> int:
    """Every game with its prices and the model's verdict. Returns the last data row."""
    ws = wb.create_sheet("Weekly Slate")
    ws.tab_color = NAVY
    set_widths(ws, {"A": 5, "B": 9, "C": 13, "D": 16, "E": 7, "F": 7, "G": 9, "H": 9,
                    "I": 13, "J": 13, "K": 8, "L": 12, "M": 10, "N": 11, "O": 12,
                    "P": 8, "Q": 10, "R": 9, "S": 19, "T": 8, "U": 9, "V": 30, "W": 44})

    apply_header(ws, "A1", f"NFL BETTING MODEL — {season} WEEK {week}",
                 merge_to=f"{SLATE_LAST_COL}1", size=16)
    ws.row_dimensions[1].height = 30
    _banner(ws, 2, _advisory_banner(model_meta), SLATE_LAST_COL, height=32)

    rows = []
    for i, (_, g) in enumerate(slate.iterrows(), start=1):
        d = g.to_dict()
        home, away = d["home_team"], d["away_team"]
        line = _num(d.get("spread_line"))
        edge = _num(d.get("spread_edge_pts"))
        hso, aso = _num(d.get("home_spread_odds")), _num(d.get("away_spread_odds"))
        juice = f"{hso:+.0f} / {aso:+.0f}" if hso is not None and aso is not None else ""
        # Cover % is the model's SIDE covering, so the side has to be named:
        # on a NO BET row nothing else on the sheet says which team it is.
        if line is None or edge is None:
            side, cover = "", None
        elif edge > 0:
            side, cover = home, _num(d.get("home_cover_prob"))
        else:
            side, cover = away, _num(d.get("away_cover_prob"))
        rows.append([
            i, _as_date(d.get("gameday")), _kickoff(d.get("weekday"), d.get("gametime")),
            f"{away} @ {home}", away, home,
            _num(d.get("away_ml")), _num(d.get("home_ml")),
            format_spread(home, line) if line is not None else "—", juice,
            _num(d.get("total_line")),
            format_spread(home, _num(d.get("fair_spread")) or 0.0),
            edge, side, cover, _num(d.get("push_prob")), _num(d.get("home_win_prob")),
            _text(d.get("confidence")), _text(d.get("recommendation")),
            _num(d.get("bet_odds")) or None, _num(d.get("stake")) or None,
            _text(d.get("wx_label")), _text(d.get("trend_notes")),
        ])

    last = _write_table(
        ws, 3, SLATE_HEADERS, rows,
        formats={2: "ddd m/d", 7: "+0;-0", 8: "+0;-0", 11: "0.0", 13: "+0.0;-0.0",
                 15: "0.0%", 16: "0.0%", 17: "0.0%", 20: "+0;-0", 21: '"$"#,##0'},
        aligns={4: "left", 19: "left", 22: "left", 23: "left"}, bold_cols=(13, 14, 19),
    )

    if last > 3:
        E, R = SLATE_EDGE_COL, SLATE_REC_COL
        # Whole-row styling for NO BET, on both sides of the edge column so the
        # edge shading below stays visible on every row.
        for rng in (f"A4:L{last}", f"N4:{SLATE_LAST_COL}{last}"):   # skip M, the edge scale
            ws.conditional_formatting.add(rng, FormulaRule(
                formula=[f'${R}4="NO BET"'], fill=fill(LIGHT_GRAY),
                font=Font(color=MUTED, italic=True)))
        rec = f"{R}4:{R}{last}"
        ws.conditional_formatting.add(rec, FormulaRule(
            formula=[f'LEFT({R}4,3)="BET"'], fill=fill(LIGHT_GREEN),
            font=Font(bold=True, color="1B5E20")))
        ws.conditional_formatting.add(rec, FormulaRule(
            formula=[f'LEFT({R}4,4)="LEAN"'], fill=fill(LEAN_FILL),
            font=Font(bold=True, color=LEAN_TEXT)))
        ws.conditional_formatting.add(rec, FormulaRule(
            formula=[f'{R}4="NO BET"'], fill=fill(LIGHT_GRAY),
            font=Font(color=MUTED, italic=True)))
        # Edge size as a color scale: white at zero, green at ±3 (the strong
        # threshold), either direction. Magnitude is what matters here; the
        # sign only says which side, and that is spelled out in the verdict.
        ws.conditional_formatting.add(f"{E}4:{E}{last}", ColorScaleRule(
            start_type="num", start_value=-3, start_color=MID_GREEN,
            mid_type="num", mid_value=0, mid_color=WHITE,
            end_type="num", end_value=3, end_color=MID_GREEN))

    n = last + 2
    apply_section(ws, f"A{n}", "SLATE SUMMARY", merge_to=f"{SLATE_LAST_COL}{n}")
    bets = slate[slate["stake"] > 0] if "stake" in slate.columns else slate.iloc[0:0]
    leans = (slate[slate["recommendation"].astype(str).str.match(r"^(LEAN|BET) ")]
             if "recommendation" in slate.columns else slate.iloc[0:0])
    abs_edge = slate["spread_edge_pts"].abs() if "spread_edge_pts" in slate.columns else pd.Series(dtype=float)
    for k, (label, val) in enumerate([
        ("Games on slate", len(slate)),
        ("Leans (price disagreements)", len(leans)),
        ("Qualifying bets", len(bets)),
        ("Total staked", f"${bets['stake'].sum():,.0f}" if len(bets) else "$0"),
        ("% of bankroll", f"{(bets['stake'].sum() if len(bets) else 0)/STAKING.bankroll*100:.1f}%"),
        ("Largest edge", f"{abs_edge.max():.1f} pts" if len(abs_edge) else "—"),
        ("Home field used", f"{model_meta.get('hfa', 0.0):+.2f} pts" if model_meta.get("hfa") is not None else "—"),
        ("Market prior weight", f"{model_meta.get('market_prior_weight', 0.0):.0%}"
                                if model_meta.get("market_prior_weight") is not None else "—"),
    ], start=1):
        ws.cell(row=n + k, column=1, value=label).font = Font(bold=True, size=11)
        ws.merge_cells(start_row=n + k, start_column=1, end_row=n + k, end_column=4)
        c = ws.cell(row=n + k, column=5, value=val)
        c.font, c.alignment = Font(bold=True, color=NAVY, size=11), center()

    note = n + 10
    ws.cell(row=note, column=1,
            value="→ Spread (Vegas) and Model Line read like a ticket for the home team. Edge is "
                  "the model's disagreement with Vegas in points, shaded by size; Model Side is the "
                  "team that edge favours and Side Cover % is that team's chance of covering. Total "
                  "is the market's number only — this model does not project totals. Lines and "
                  "prices are FanDuel's (the book Jameson bets at). Trend fixes are the consistent "
                  "miss-reasons the model corrects for — see the Miss Report sheet.")
    ws.cell(row=note, column=1).font = Font(italic=True, color=GREEN, size=10)
    ws.merge_cells(start_row=note, start_column=1, end_row=note, end_column=len(SLATE_HEADERS))
    ws.row_dimensions[note].height = 30
    return last


# ─────────────────────────────────────────────
# MODEL PICKS %
# ─────────────────────────────────────────────

MP_HEADERS = ["#", "Date", "Kickoff (ET)", "Matchup", "Away", "Home",
              "Away Win % (model)", "Home Win % (model)",
              "Away % (market, de-vigged)", "Home % (market, de-vigged)",
              "Away Edge", "Home Edge", "Model Pick", "Pick Win %",
              "Market Favorite", "Agree?", "Away ML", "Home ML", "Vig %"]


def _sheet_model_picks(wb, slate, season, week, model_meta):
    """
    Every game, the model's probability for each side next to the market's.

    The two model columns sum to 100% by construction (ties are split); the
    market columns sum to 100% because they are de-vigged. Edge is model
    minus market, so the sign says which side the model likes more than the
    price does. That is a disagreement, not evidence -- the banner says so.
    """
    ws = wb.create_sheet("Model Picks %")
    ws.tab_color = GRAY_BLUE
    set_widths(ws, {"A": 5, "B": 9, "C": 13, "D": 16, "E": 7, "F": 7, "G": 12, "H": 12,
                    "I": 13, "J": 13, "K": 10, "L": 10, "M": 11, "N": 11, "O": 11,
                    "P": 9, "Q": 9, "R": 9, "S": 8})
    lastc = get_column_letter(len(MP_HEADERS))
    apply_header(ws, "A1", f"MODEL WIN PROBABILITY vs MARKET — {season} WEEK {week}",
                 merge_to=f"{lastc}1", size=16)
    ws.row_dimensions[1].height = 30
    _banner(ws, 2, "Edge = model win % − de-vigged market %. " + HOLDOUT["coef"].capitalize()
                   + " on hold-out; treat a gap as a disagreement to log, not an opportunity.",
            lastc, height=32)

    rows = []
    data = _model_rows(slate)
    # Kickoff order reads naturally here; the slate keeps edge order.
    data.sort(key=lambda r: (r["gameday"] or date.max, r["kickoff"], r["matchup"]))
    for i, r in enumerate(data, start=1):
        hwp, awp = r["home_win_prob"], r["away_win_prob"]
        mh, ma = r["market_home_prob"], r["market_away_prob"]
        rows.append([
            i, r["gameday"], r["kickoff"], r["matchup"], r["away_team"], r["home_team"],
            awp, hwp, ma, mh,
            None if (awp is None or ma is None) else awp - ma,
            None if (hwp is None or mh is None) else hwp - mh,
            r["projected_winner"], r["winner_prob"], r["market_favorite"], r["agree"],
            r["away_ml"], r["home_ml"],
            None if r["vig_pct"] is None else r["vig_pct"] / 100.0,
        ])

    last = _write_table(
        ws, 3, MP_HEADERS, rows,
        formats={2: "ddd m/d", 7: "0.0%", 8: "0.0%", 9: "0.0%", 10: "0.0%",
                 11: "+0.0%;-0.0%", 12: "+0.0%;-0.0%", 14: "0.0%", 17: "+0;-0",
                 18: "+0;-0", 19: "0.0%"},
        aligns={4: "left"}, bold_cols=(13,),
    )
    if last > 3:
        for col in ("G", "H"):
            ws.conditional_formatting.add(f"{col}4:{col}{last}", DataBarRule(
                start_type="num", start_value=0, end_type="num", end_value=1,
                color=BAR_BLUE, showValue=True))
        for col in ("K", "L"):
            ws.conditional_formatting.add(f"{col}4:{col}{last}", ColorScaleRule(
                start_type="num", start_value=-0.10, start_color=MID_RED,
                mid_type="num", mid_value=0, mid_color=WHITE,
                end_type="num", end_value=0.10, end_color=MID_GREEN))
        ws.conditional_formatting.add(f"P4:P{last}", FormulaRule(
            formula=['P4="NO"'], fill=fill(LIGHT_ORANGE), font=Font(bold=True, color="E65100")))

    n = last + 2
    ws.cell(row=n, column=1,
            value="→ Model % comes from tilting the empirical margin distribution to the projected "
                  "margin (key numbers preserved). Market % strips the vig multiplicatively. A team "
                  "the model likes 5% more than the market is the model disagreeing with the "
                  "sharpest number in sports; the backtest says the market is usually right.")
    ws.cell(row=n, column=1).font = Font(italic=True, color=GREEN, size=10)
    ws.merge_cells(start_row=n, start_column=1, end_row=n, end_column=len(MP_HEADERS))
    ws.row_dimensions[n].height = 30


# ─────────────────────────────────────────────
# GAME DETAIL — THE MATCHUP PICKER
# ─────────────────────────────────────────────

def _sheet_detail(wb, slate, season, week, slate_last, model_meta):
    """
    Pick a game from a dropdown; every cell below looks it up.

    The dropdown's list is the Matchup column of the Weekly Slate, and every
    value is an INDEX/MATCH into the hidden Model Data sheet keyed on that
    text. Nothing on this sheet is typed in by the builder except the labels,
    so what it shows is exactly what the model computed for that game --
    the same fields as the slate, plus the pieces the projection is built
    from (team ratings, quarterback terms, home field, market prior weight),
    the de-vigged market probabilities and the key-number-aware cover/push
    split. No invented factors: if it is not a model output it is not here.
    """
    ws = wb.create_sheet("Game Detail")
    ws.tab_color = GRAY_BLUE
    set_widths(ws, {"A": 30, "B": 17, "C": 17, "D": 17, "E": 46})

    apply_header(ws, "A1", f"MATCHUP PICKER — {season} WEEK {week}", merge_to="E1", size=16)
    ws.row_dimensions[1].height = 30
    _banner(ws, 2, "Choose a game in the yellow cell. Everything below is a live lookup of the "
                   "model's own output for that game — the advisory verdict on the Reference "
                   "sheet applies to all of it.", "E", height=30)

    n = len(slate)
    if n == 0:
        ws.cell(row=4, column=1, value="No games on the slate.").font = Font(italic=True, color=MUTED)
        return

    def idx(key):
        col = MD_COL[key]
        return (f"INDEX('Model Data'!${col}$2:${col}${n + 1},"
                f"MATCH($B$3,'Model Data'!$A$2:$A${n + 1},0))")

    def lk(key):
        return f'=IFERROR({idx(key)},"")'

    def net(h, a):
        return f'=IFERROR({idx(h)}-{idx(a)},"")'

    # ── the dropdown ──
    lab = ws.cell(row=3, column=1, value="SELECT A GAME  ▶")
    lab.font, lab.fill, lab.alignment, lab.border = Font(bold=True, size=12), fill(LABEL_FILL), left(), thin_border()
    first_matchup = f"{slate.iloc[0]['away_team']} @ {slate.iloc[0]['home_team']}"
    sel = ws.cell(row=3, column=2, value=first_matchup)
    sel.font, sel.fill, sel.alignment, sel.border = Font(bold=True, size=13, color=NAVY), fill(LIGHT_YELLOW), center(), thin_border()
    ws.merge_cells("B3:C3")
    ws.row_dimensions[3].height = 26
    dv = DataValidation(
        type="list",
        formula1=f"'Weekly Slate'!${SLATE_MATCHUP_COL}$4:${SLATE_MATCHUP_COL}${slate_last}",
        allow_blank=False, showDropDown=False,
    )
    dv.promptTitle, dv.prompt = "Matchup", "Pick any game from this week's Weekly Slate."
    dv.showInputMessage = True
    dv.errorTitle, dv.error = "Not on the slate", "Choose a matchup from the list."
    dv.showErrorMessage = True
    ws.add_data_validation(dv)
    dv.add("B3")
    kick = ws.cell(row=3, column=4, value=f'=IFERROR(TEXT({idx("gameday")},"ddd m/d")&"  "&{idx("kickoff")},"")')
    kick.font, kick.alignment = Font(italic=True, color=MUTED, size=11), center()
    site = ws.cell(row=3, column=5, value=f'=IFERROR({idx("stadium")}&" · "&{idx("site")}&" · "&{idx("roof")},"")')
    site.font, site.alignment = Font(italic=True, color=MUTED, size=11), left()

    # ── verdict strip ──
    r = 5
    apply_section(ws, f"A{r}", "THE MODEL'S CALL", merge_to=f"E{r}")
    big = Font(bold=True, size=14, color=NAVY)
    _label_value(ws, r + 1, 1, "Projected winner", lk("projected_winner"), value_font=big, bold_label=True)
    _label_value(ws, r + 1, 3, "Win probability", lk("winner_prob"), fmt="0.0%", value_font=big, bold_label=True)
    ws.cell(row=r + 1, column=5, value='=IFERROR("Market favorite: "&' + idx("market_favorite") +
            '&"   ·   Model agrees: "&' + idx("agree") + ',"")').font = Font(italic=True, color=MUTED, size=10)
    _label_value(ws, r + 2, 1, "Projected margin (winner's side)", lk("winner_margin"), fmt="+0.0;-0.0")
    _label_value(ws, r + 2, 3, "Recommendation", lk("recommendation"))
    ws.cell(row=r + 2, column=5, value='=IFERROR("Confidence: "&' + idx("confidence") +
            '&IF(' + idx("stake") + '>0,"   ·   Stake $"&TEXT(' + idx("stake") + ',"0"),"   ·   $0 staked (advisory)"),"")'
            ).font = Font(italic=True, color=MUTED, size=10)
    ws.conditional_formatting.add(f"D{r + 2}", FormulaRule(
        formula=[f'LEFT(D{r + 2},4)="LEAN"'], fill=fill(LEAN_FILL), font=Font(bold=True, color=LEAN_TEXT)))
    ws.conditional_formatting.add(f"D{r + 2}", FormulaRule(
        formula=[f'LEFT(D{r + 2},3)="BET"'], fill=fill(LIGHT_GREEN), font=Font(bold=True, color="1B5E20")))
    ws.conditional_formatting.add(f"D{r + 2}", FormulaRule(
        formula=[f'D{r + 2}="NO BET"'], fill=fill(LIGHT_GRAY), font=Font(color=MUTED, italic=True)))

    # ── what drives it ──
    r = 9
    apply_section(ws, f"A{r}", "WHAT DRIVES IT  (points, home perspective)", merge_to=f"E{r}")
    hdr = r + 1
    _header_row(ws, hdr, ["Factor", "Home", "Away", "Net (home − away)", "What it means"])
    ws.cell(row=hdr, column=2, value=f'=IFERROR("Home: "&{idx("home_team")},"Home")')
    ws.cell(row=hdr, column=3, value=f'=IFERROR("Away: "&{idx("away_team")},"Away")')
    drivers = [
        ("Team power rating", lk("home_team_rating"), lk("away_team_rating"),
         net("home_team_rating", "away_team_rating"), "+0.00;-0.00",
         "Opponent-adjusted ridge rating in points vs an average team, already blended toward the market's implied rating early in the season."),
        ("Starting quarterback", lk("home_qb"), lk("away_qb"), "", None,
         '=IFERROR("Home QB "&' + idx("home_qb_note") + '&"; away QB "&' + idx("away_qb_note") + ',"")'),
        ("Quarterback adjustment", lk("home_qb_adj"), lk("away_qb_adj"),
         net("home_qb_adj", "away_qb_adj"), "+0.00;-0.00",
         "QB term from the joint team+QB fit. A QB without enough starts sits at replacement level, which is the fit's honest default for a rookie or a backup."),
        ("Home field advantage", lk("hfa_used"), "", lk("hfa_used"), "+0.00;-0.00",
         "Fitted at ~2 points, not 3; zero at a neutral site."),
        ("Situational adjustments", lk("situational_adj"), "", lk("situational_adj"), "+0.00;-0.00",
         "Rest, weather, travel, divisional, late-season — all measured against the closing line and all ship at zero."),
        ("Weekly self-tune (EPA)", lk("selftune_adj"), "", lk("selftune_adj"), "+0.00;-0.00",
         "Nudge from how well each team has actually played (EPA) vs what the model projected. Max 0.5 pt."),
        ("Trend fixes", lk("trend_adj"), "", lk("trend_adj"), "+0.00;-0.00",
         '=IFERROR(' + idx("trend_notes") + ',"")'),
        ("Market prior weight", lk("market_prior_weight"), "", "", "0%",
         "Share of each team rating that is the market's own preseason opinion. High in Week 1 by design; decays as games are played."),
        ("PROJECTED MARGIN", "", "", lk("projected_margin"), "+0.00;-0.00",
         "Rating net + QB net + home field + situational + self-tune + trend fixes. This is the number every probability below comes from."),
    ]
    for k, (label, h, a, nt, fmt, note) in enumerate(drivers, start=1):
        rr = hdr + k
        bold = label.isupper()
        lc = ws.cell(row=rr, column=1, value=label)
        lc.font, lc.fill, lc.border, lc.alignment = Font(bold=bold, size=11), fill(LABEL_FILL), thin_border(), left()
        for col, val in ((2, h), (3, a), (4, nt)):
            c = ws.cell(row=rr, column=col, value=val)
            c.font = Font(bold=(col == 4 or bold), color=NAVY, size=11)
            c.alignment, c.border, c.fill = center(), thin_border(), fill(LIGHT_GRAY)
            if fmt and val:
                c.number_format = fmt
        nc = ws.cell(row=rr, column=5, value=note if str(note).startswith("=") else _safe_text(str(note)))
        nc.font, nc.alignment, nc.border = Font(size=10, color="333333"), left(), thin_border()
        ws.row_dimensions[rr].height = 30 if len(note) > 70 else 18
    drv_last = hdr + len(drivers)
    ws.auto_filter.ref = f"A{hdr}:E{drv_last}"
    ws.freeze_panes = "A4"

    # ── spread ──
    r = drv_last + 2
    apply_section(ws, f"A{r}", "SPREAD  (key-number aware: probabilities come from the empirical margin distribution)", merge_to=f"E{r}")
    spread = [
        ("Vegas line (home ticket)", lk("vegas_line"), None, "Model line (home ticket)", lk("model_line"), None),
        ("Edge (pts, model − Vegas)", lk("spread_edge_pts"), "+0.00;-0.00", "Model's side", lk("model_side"), None),
        ("Home cover %", lk("home_cover_prob"), "0.0%", "Away cover %", lk("away_cover_prob"), "0.0%"),
        ("Push % (at this line)", lk("push_prob"), "0.0%", "Model's side cover %", lk("model_side_cover"), "0.0%"),
        ("Spread juice (home)", lk("home_spread_odds"), "+0;-0", "Spread juice (away)", lk("away_spread_odds"), "+0;-0"),
        ("Total (market only)", lk("total_line"), "0.0", "Over / under odds", f'=IFERROR(TEXT({idx("over_odds")},"+0;-0")&" / "&TEXT({idx("under_odds")},"+0;-0"),"")', None),
    ]
    for k, (l1, v1, f1, l2, v2, f2) in enumerate(spread, start=1):
        _label_value(ws, r + k, 1, l1, v1, fmt=f1)
        _label_value(ws, r + k, 3, l2, v2, fmt=f2)
    sp_last = r + len(spread)
    ws.cell(row=sp_last + 1, column=1,
            value="→ Cover % on a whole-number line comes with real push mass: a game lands on exactly 3 about "
                  "4.7× as often as on 4, and the model reproduces that instead of smoothing it away.")
    ws.cell(row=sp_last + 1, column=1).font = Font(italic=True, color=GREEN, size=10)
    ws.merge_cells(start_row=sp_last + 1, start_column=1, end_row=sp_last + 1, end_column=5)

    # ── moneyline ──
    r = sp_last + 3
    apply_section(ws, f"A{r}", "MONEYLINE  (market probabilities are de-vigged before any edge is computed)", merge_to=f"E{r}")
    ml = [
        ("Home win % (model)", lk("home_win_prob"), "0.0%", "Away win % (model)", lk("away_win_prob"), "0.0%"),
        ("Home % (market, de-vigged)", lk("market_home_prob"), "0.0%", "Away % (market, de-vigged)", lk("market_away_prob"), "0.0%"),
        ("Home edge (model − market)", lk("ml_edge_home"), "+0.0%;-0.0%", "Away edge (model − market)", lk("ml_edge_away"), "+0.0%;-0.0%"),
        ("Home ML (actual)", lk("home_ml"), "+0;-0", "Away ML (actual)", lk("away_ml"), "+0;-0"),
        ("Home ML (model fair)", lk("home_ml_fair"), "+0;-0", "Away ML (model fair)", lk("away_ml_fair"), "+0;-0"),
        ("Vig in the posted moneyline", f'=IFERROR({idx("vig_pct")}/100,"")', "0.0%", "Market favorite", lk("market_favorite"), None),
    ]
    for k, (l1, v1, f1, l2, v2, f2) in enumerate(ml, start=1):
        _label_value(ws, r + k, 1, l1, v1, fmt=f1)
        _label_value(ws, r + k, 3, l2, v2, fmt=f2)
    ml_last = r + len(ml)
    for col, rows_ in (("B", (r + 3,)), ("D", (r + 3,))):
        for rr in rows_:
            ws.conditional_formatting.add(f"{col}{rr}", FormulaRule(
                formula=[f'AND(ISNUMBER({col}{rr}),{col}{rr}>=0.03)'], fill=fill(LIGHT_GREEN),
                font=Font(bold=True, color="1B5E20")))
            ws.conditional_formatting.add(f"{col}{rr}", FormulaRule(
                formula=[f'AND(ISNUMBER({col}{rr}),{col}{rr}<=-0.03)'], fill=fill(LIGHT_RED),
                font=Font(bold=True, color="B71C1C")))
    first_driver = hdr + 1
    ws.conditional_formatting.add(f"B{first_driver}:D{drv_last}", FormulaRule(
        formula=[f'AND(ISNUMBER(B{first_driver}),B{first_driver}<0)'],
        font=Font(color="B71C1C")))

    # ── the bet, if any ──
    r = ml_last + 2
    apply_section(ws, f"A{r}", "THE TICKET", merge_to=f"E{r}")
    _label_value(ws, r + 1, 1, "Market", lk("bet_market"))
    _label_value(ws, r + 1, 3, "Side", lk("bet_side"))
    _label_value(ws, r + 2, 1, "Odds", lk("bet_odds"), fmt="+0;-0")
    _label_value(ws, r + 2, 3, "Stake", lk("stake"), fmt='"$"#,##0')
    _label_value(ws, r + 3, 1, "Confidence", lk("confidence"))
    _label_value(ws, r + 3, 3, "Game id", lk("game_id"))
    ws.cell(row=r + 5, column=1,
            value=("→ " + ("Advisory mode: the ticket is what the model WOULD take, at $0. Log it on the Bet "
                           "Tracker with the number you can actually get; CLV over ~40-50 picks is the test."
                           if model_meta.get("advisory", True) else
                           "Live staking is on. Stakes are half-Kelly, capped per bet and per week.")))
    ws.cell(row=r + 5, column=1).font = Font(italic=True, color=GREEN, size=10)
    ws.merge_cells(start_row=r + 5, start_column=1, end_row=r + 5, end_column=5)
    ws.row_dimensions[r + 5].height = 30


# ─────────────────────────────────────────────
# TEAM STATS, ROSTERS, INJURIES
# ─────────────────────────────────────────────

TS_HEADERS = ["Rank", "Team", "Rating", "Record", "PF", "PA", "PD", "Home", "Away", "ATS",
              "Last Result", "Starting QB", "QB Source", "Active", "Injured", "Out / IR",
              "Injured List (name · injury · status · expected return)",
              "QB", "RB", "WR", "TE", "OL", "DL", "LB", "DB", "ST"]
TS_KEYS = ["rank", "team", "rating", "record", "pf", "pa", "pd", "home_record", "away_record",
           "ats_record", "last_result", "starting_qb", "qb_source", "roster_size", "n_injured",
           "n_out", "injured_list", "QB", "RB", "WR", "TE", "OL", "DL", "LB", "DB", "ST"]


def _frame(team_stats, key) -> pd.DataFrame:
    if not team_stats:
        return pd.DataFrame()
    df = team_stats.get(key)
    return df if isinstance(df, pd.DataFrame) else pd.DataFrame()


def _sheet_team_stats(wb, team_stats, season, week):
    """
    One row per team: where it stands, who it starts, who it is missing.

    Records and point differential are this season's played games. Rosters
    and injuries are live feeds (ESPN, nflverse fallback). None of this moves
    the ratings -- the quarterback is the only player the model rates, and he
    is resolved separately -- so this sheet is for the human deciding whether
    to trust a projection, which is worth more than a coefficient nobody has
    validated.
    """
    ws = wb.create_sheet("Team Stats")
    ws.tab_color = GREEN
    widths = {"A": 6, "B": 7, "C": 8, "D": 8, "E": 6, "F": 6, "G": 7, "H": 7, "I": 7, "J": 8,
              "K": 15, "L": 18, "M": 12, "N": 7, "O": 8, "P": 8, "Q": 58,
              "R": 22, "S": 22, "T": 30, "U": 20, "V": 34, "W": 32, "X": 26, "Y": 32, "Z": 18}
    set_widths(ws, widths)
    lastc = get_column_letter(len(TS_HEADERS))
    apply_header(ws, "A1", f"TEAM STATS — entering {season} Week {week}", merge_to=f"{lastc}1", size=16)
    ws.row_dimensions[1].height = 30

    summary = _frame(team_stats, "summary")
    sources = (team_stats or {}).get("sources", {}) if team_stats else {}
    fetched = (team_stats or {}).get("fetched_utc", "") if team_stats else ""
    src_note = (f"Rosters: {sources.get('roster', 'unavailable')}; injuries: "
                f"{sources.get('injuries', 'unavailable')}"
                + (f"; pulled {fetched}" if fetched else ""))
    _banner(ws, 2, f"Record, PF/PA and point differential from this season's played games before "
                   f"Week {week}. ATS is against the closing line. {src_note}. Reporting only — "
                   "nothing here moves the ratings except the starting quarterback.", lastc, height=32)

    if summary.empty:
        ws.cell(row=4, column=1, value="Team stats unavailable this run (feeds offline). "
                                       "Re-run with --refresh once the network is back.").font = Font(italic=True, color=MUTED)
        _header_row(ws, 3, TS_HEADERS)
        ws.freeze_panes = "C4"
        ws.auto_filter.ref = f"A3:{lastc}4"
        return

    rows = []
    for _, s in summary.iterrows():
        d = s.to_dict()
        rows.append([d.get(k) for k in TS_KEYS])

    last = _write_table(
        ws, 3, TS_HEADERS, rows,
        formats={3: "+0.00;-0.00", 7: "+0;-0"},
        aligns={11: "left", 12: "left", 17: "top", 18: "top", 19: "top", 20: "top",
                21: "top", 22: "top", 23: "top", 24: "top", 25: "top", 26: "top"},
        bold_cols=(2, 3),
        fonts={17: Font(size=10, color="333333"), 18: Font(size=10), 19: Font(size=10),
               20: Font(size=10), 21: Font(size=10), 22: Font(size=10), 23: Font(size=10),
               24: Font(size=10), 25: Font(size=10), 26: Font(size=10)},
    )
    ws.freeze_panes = "C4"
    if last > 3:
        ws.conditional_formatting.add(f"G4:G{last}", ColorScaleRule(
            start_type="min", start_color=MID_RED, mid_type="num", mid_value=0,
            mid_color=WHITE, end_type="max", end_color=MID_GREEN))
        ws.conditional_formatting.add(f"C4:C{last}", ColorScaleRule(
            start_type="min", start_color=MID_RED, mid_type="num", mid_value=0,
            mid_color=WHITE, end_type="max", end_color=MID_GREEN))
        ws.conditional_formatting.add(f"P4:P{last}", FormulaRule(
            formula=["P4>=3"], fill=fill(LIGHT_RED), font=Font(bold=True, color="B71C1C")))
        ws.conditional_formatting.add(f"O4:O{last}", DataBarRule(
            start_type="num", start_value=0, end_type="max", color=LIGHT_ORANGE, showValue=True))
        ws.conditional_formatting.add(f"M4:M{last}", FormulaRule(
            formula=['M4="carry-forward"'], fill=fill(LIGHT_ORANGE), font=Font(color="E65100")))
        _fit_row_heights(ws, 4, last, {17: widths["Q"], 18: widths["R"], 19: widths["S"],
                                       20: widths["T"], 21: widths["U"], 22: widths["V"],
                                       23: widths["W"], 24: widths["X"], 25: widths["Y"],
                                       26: widths["Z"]})

    n = last + 2
    ws.cell(row=n, column=1,
            value="→ Position columns are the full roster by group; (IR) and (PS) mark injured reserve and "
                  "practice squad. The Rosters and Injuries sheets hold the same data one row per player, "
                  "with filters. A wrong starting QB is the single most expensive input error — check it "
                  "here before trusting any lean.")
    ws.cell(row=n, column=1).font = Font(italic=True, color=GREEN, size=10)
    ws.merge_cells(start_row=n, start_column=1, end_row=n, end_column=12)
    ws.row_dimensions[n].height = 30


ROSTER_HEADERS = ["Team", "Player", "Pos", "Group", "#", "Age", "Exp", "Status", "Injury Status", "Source"]
ROSTER_KEYS = ["team", "player", "position", "pos_group", "jersey", "age", "years_exp",
               "status", "injury_status", "source"]


def _sheet_rosters(wb, team_stats):
    ws = wb.create_sheet("Rosters")
    ws.tab_color = GREEN
    set_widths(ws, {"A": 7, "B": 24, "C": 6, "D": 8, "E": 5, "F": 6, "G": 6, "H": 16, "I": 16, "J": 10})
    apply_header(ws, "A1", "ROSTERS — every player under contract, one row each", merge_to="J1", size=16)
    ws.row_dimensions[1].height = 30
    _banner(ws, 2, "Filter by Team or Status. Practice squad and injured reserve are included so the "
                   "roster is complete; Status tells them apart.", "J", height=18)
    roster = _frame(team_stats, "roster")
    rows = [[d.get(k) for k in ROSTER_KEYS] for d in roster.to_dict("records")] if not roster.empty else []
    last = _write_table(ws, 3, ROSTER_HEADERS, rows, aligns={2: "left"}, bold_cols=(2,))
    if not rows:
        ws.cell(row=4, column=1, value="Roster feed unavailable this run.").font = Font(italic=True, color=MUTED)
        return
    ws.conditional_formatting.add(f"H4:H{last}", FormulaRule(
        formula=['H4<>"Active"'], font=Font(color=MUTED, italic=True)))
    ws.conditional_formatting.add(f"H4:H{last}", FormulaRule(
        formula=['OR(H4="Injured Reserve",H4="Out",H4="Reserve/IR",H4="Suspended")'],
        fill=fill(LIGHT_RED), font=Font(color="B71C1C")))
    ws.conditional_formatting.add(f"I4:I{last}", FormulaRule(
        formula=['OR(I4="Out",I4="Injured Reserve",I4="Doubtful")'],
        fill=fill(LIGHT_RED), font=Font(color="B71C1C")))
    ws.conditional_formatting.add(f"I4:I{last}", FormulaRule(
        formula=['I4="Questionable"'], fill=fill(LIGHT_ORANGE), font=Font(color="E65100")))


INJ_HEADERS = ["Team", "Player", "Pos", "Status", "Injury", "Practice", "Expected Return",
               "Updated", "Comment", "Source"]
INJ_KEYS = ["team", "player", "position", "status", "injury", "practice_status",
            "expected_return", "updated", "comment", "source"]


def _sheet_injuries(wb, team_stats):
    ws = wb.create_sheet("Injuries")
    ws.tab_color = DARK_GOLD
    set_widths(ws, {"A": 7, "B": 24, "C": 6, "D": 16, "E": 18, "F": 18, "G": 12, "H": 18, "I": 70, "J": 14})
    apply_header(ws, "A1", "INJURIES — designations, expected returns and the latest word", merge_to="J1", size=16)
    ws.row_dimensions[1].height = 30
    _banner(ws, 2, "ESPN designations (Out / Doubtful / Questionable / IR) merged with the official "
                   "nflverse report (practice status). Teams file Wednesday–Friday, so a Tuesday run "
                   "sees a thinner list than Sunday's. Expected return is ESPN's estimate.", "J", height=30)
    inj = _frame(team_stats, "injuries")
    rows = [[d.get(k) for k in INJ_KEYS] for d in inj.to_dict("records")] if not inj.empty else []
    last = _write_table(ws, 3, INJ_HEADERS, rows, aligns={2: "left", 5: "left", 9: "left"},
                        bold_cols=(2,), fonts={9: Font(size=10, color="333333")})
    if not rows:
        ws.cell(row=4, column=1, value="No injury designations available this run.").font = Font(italic=True, color=MUTED)
        return
    ws.conditional_formatting.add(f"D4:D{last}", FormulaRule(
        formula=['OR(D4="Out",D4="Injured Reserve",D4="Doubtful",D4="Suspension",D4="Suspended")'],
        fill=fill(LIGHT_RED), font=Font(bold=True, color="B71C1C")))
    ws.conditional_formatting.add(f"D4:D{last}", FormulaRule(
        formula=['D4="Questionable"'], fill=fill(LIGHT_ORANGE), font=Font(color="E65100")))
    ws.conditional_formatting.add(f"D4:D{last}", FormulaRule(
        formula=['LEFT(D4,8)="Practice"'], font=Font(color=MUTED, italic=True)))
    ws.conditional_formatting.add(f"C4:C{last}", FormulaRule(
        formula=['C4="QB"'], fill=fill(LIGHT_YELLOW), font=Font(bold=True)))
    _fit_row_heights(ws, 4, last, {9: 70}, max_height=60)


# ─────────────────────────────────────────────
# POWER RATINGS
# ─────────────────────────────────────────────

def _sheet_ratings(wb, ratings, season, week):
    ws = wb.create_sheet("Power Ratings")
    ws.tab_color = GREEN
    set_widths(ws, {"A": 8, "B": 14, "C": 16, "D": 60})

    apply_header(ws, "A1", f"POWER RATINGS — entering {season} Week {week}", merge_to="D1", size=16)
    ws.row_dimensions[1].height = 30
    _header_row(ws, 3, ["Rank", "Team", "Rating (pts)", "Interpretation"])
    ws.freeze_panes = "A4"

    for i, (_, r) in enumerate(ratings.iterrows(), start=1):
        row = 3 + i
        vals = [int(r["rank"]), r["team"], round(float(r["rating"]), 2),
                f"{abs(r['rating']):.1f} pts {'better' if r['rating'] >= 0 else 'worse'} than an average team on a neutral field"]
        for j, v in enumerate(vals, start=1):
            c = ws.cell(row=row, column=j, value=v)
            c.border = thin_border()
            c.alignment = center() if j != 4 else left()
            c.font = Font(color="000000", size=11, bold=(j == 3))
            if i % 2 == 0:
                c.fill = fill(ROW_TINT)
        ws.cell(row=row, column=3).number_format = "+0.00;-0.00"

    last = 3 + len(ratings)
    ws.auto_filter.ref = f"A3:D{max(last, 4)}"
    if last > 3:
        ws.conditional_formatting.add(f"C4:C{last}", ColorScaleRule(
            start_type="min", start_color=MID_RED, mid_type="num", mid_value=0,
            mid_color=WHITE, end_type="max", end_color=MID_GREEN))

    n = last + 2
    ws.cell(row=n, column=1, value="Ratings are opponent-adjusted and include the projected starting quarterback. "
                                   "A matchup's model line = home rating − away rating + home field advantage. "
                                   "Early in the season most of a rating is the market's implied rating, by design.")
    ws.cell(row=n, column=1).font = Font(italic=True, color=GREEN, size=10)
    ws.merge_cells(start_row=n, start_column=1, end_row=n, end_column=4)
    ws.row_dimensions[n].height = 30


# ─────────────────────────────────────────────
# BET TRACKER
# ─────────────────────────────────────────────

def _sheet_tracker(wb, preserved=None):
    """
    The hand-entered log. Columns A-I, L, M and P are yours; J, K, N, O are
    formulas. Rows found in any earlier workbook or the CSV mirror are put
    back exactly where they were, so re-running never loses a bet.
    """
    ws = wb.create_sheet("Bet Tracker")
    ws.tab_color = DARK_GOLD
    set_widths(ws, {"A": 11, "B": 6, "C": 22, "D": 12, "E": 18, "F": 11, "G": 9,
                    "H": 9, "I": 8, "J": 12, "K": 13, "L": 12, "M": 12,
                    "N": 10, "O": 10, "P": 11})

    apply_header(ws, "A1", "BET TRACKER", merge_to="P1", size=16)
    ws.row_dimensions[1].height = 30
    _banner(ws, 2, "Log every lean you would act on, even at $0 — yellow columns are yours, gray ones "
                   "calculate. Rows persist across weekly runs and mirror to data/bet_log.csv.", "P", height=18)

    apply_section(ws, "A3", "SUMMARY", merge_to="F3")
    summary = [
        (4, "Starting Bankroll", STAKING.bankroll, '"$"#,##0.00'),
        (5, "Total Bets", "=COUNTA($A$12:$A$500)", None),
        (6, "Record (W-L-P)", '=COUNTIF($I$12:$I$500,"W")&"-"&COUNTIF($I$12:$I$500,"L")&"-"&COUNTIF($I$12:$I$500,"Push")', None),
        (7, "Win %", '=IFERROR(COUNTIF($I$12:$I$500,"W")/(COUNTIF($I$12:$I$500,"W")+COUNTIF($I$12:$I$500,"L")),0)', "0.0%"),
        (8, "Total P&L", "=SUM($J$12:$J$500)", '"$"#,##0.00'),
        (9, "ROI", "=IFERROR(SUM($J$12:$J$500)/SUM($H$12:$H$500),0)", "0.0%"),
        (10, "Current Bankroll", "=$B$4+SUM($J$12:$J$500)", '"$"#,##0.00'),
    ]
    for row, label, formula, fmt in summary:
        lc = ws.cell(row=row, column=1, value=label)
        lc.font = Font(bold=True, color="000000", size=11)
        c = ws.cell(row=row, column=2, value=formula)
        c.font, c.alignment, c.border = Font(bold=True, color=NAVY, size=12), center(), thin_border()
        if fmt:
            c.number_format = fmt
        if row == 4:
            c.fill = fill(LIGHT_YELLOW)

    # CLV summary — the metric that tells you if you're sharp before P&L can.
    ws.cell(row=4, column=4, value="Avg CLV").font = Font(bold=True, size=11)
    clv = ws.cell(row=4, column=5, value='=IFERROR(AVERAGE($O$12:$O$500),"")')
    clv.font, clv.alignment, clv.number_format, clv.border = Font(bold=True, color=NAVY, size=12), center(), "0.00%", thin_border()
    ws.cell(row=5, column=4, value="Beat close %").font = Font(bold=True, size=11)
    bc = ws.cell(row=5, column=5, value='=IFERROR(COUNTIF($O$12:$O$500,">0")/COUNT($O$12:$O$500),"")')
    bc.font, bc.alignment, bc.number_format, bc.border = Font(bold=True, color=NAVY, size=12), center(), "0.0%", thin_border()
    ws.cell(row=4, column=6, value="Avg CLV (pts)").font = Font(bold=True, size=11)
    cp = ws.cell(row=4, column=7, value='=IFERROR(AVERAGE($N$12:$N$500),"")')
    cp.font, cp.alignment, cp.number_format, cp.border = Font(bold=True, color=NAVY, size=12), center(), "+0.00;-0.00", thin_border()
    ws.cell(row=5, column=6, value="CLV samples").font = Font(bold=True, size=11)
    cn = ws.cell(row=5, column=7, value="=COUNT($O$12:$O$500)")
    cn.font, cn.alignment, cn.border = Font(bold=True, color=NAVY, size=12), center(), thin_border()
    ws.cell(row=6, column=4, value="↑ Positive CLV is the earliest real evidence of edge. For spreads, points is the honest unit. "
                                   "Decision gate: ~40-50 logged picks (OPERATING.md).").font = Font(italic=True, color=GREEN, size=10)
    ws.merge_cells("D6:H6")

    headers = ["Date", "Week", "Matchup", "Market", "Bet Side", "Line Taken",
               "Odds", "Stake", "Result", "P&L", "Bankroll",
               "Closing Line", "Closing Odds", "CLV (pts)", "CLV (%)",
               "Model Edge"]
    _header_row(ws, 11, headers)
    ws.freeze_panes = "A12"
    ws.auto_filter.ref = "A11:P500"

    dv = DataValidation(type="list", formula1='"W,L,Push"', allow_blank=True)
    dv.sqref = "I12:I500"
    ws.add_data_validation(dv)

    dv_mkt = DataValidation(type="list", formula1='"SPREAD,MONEYLINE"', allow_blank=True)
    dv_mkt.sqref = "D12:D500"
    ws.add_data_validation(dv_mkt)

    for row in range(12, 501):
        # J — P&L. A push returns the stake, so it is zero, not a loss.
        ws.cell(row=row, column=10, value=(
            f'=IF($I{row}="W",IF($G{row}<0,$H{row}*100/ABS($G{row}),$H{row}*$G{row}/100),'
            f'IF($I{row}="L",-$H{row},IF($I{row}="Push",0,"")))'
        )).number_format = '"$"#,##0.00'

        # K — running bankroll
        ws.cell(row=row, column=11, value=(
            f'=IF(COUNTA($A$12:$A{row})=0,"",$B$4+SUM($J$12:$J{row}))'
        )).number_format = '"$"#,##0.00'

        # N — CLV in POINTS. Both numbers are quoted from your side, so
        # taken-minus-close is signed correctly: +3.5 taken vs +1.5 close = +2.
        ws.cell(row=row, column=14, value=(
            f'=IF(OR($D{row}<>"SPREAD",$F{row}="",$L{row}=""),"",$F{row}-$L{row})'
        )).number_format = "+0.0;-0.0"

        # O — CLV in probability. Moneyline uses the two prices. Spread
        # converts points via the per-line table on Lists!D:E, because the
        # point that crosses 3 is worth four times a point at 2.
        ws.cell(row=row, column=15, value=(
            f'=IF($D{row}="MONEYLINE",'
            f'IF(OR($G{row}="",$M{row}=""),"",'
            f'IF($M{row}<0,-$M{row}/(-$M{row}+100),100/($M{row}+100))'
            f'-IF($G{row}<0,-$G{row}/(-$G{row}+100),100/($G{row}+100))),'
            f'IF($N{row}="","",'
            f'$N{row}*IFERROR(VLOOKUP(ABS($F{row}),Lists!$D:$E,2,FALSE),0.03)))'
        )).number_format = "0.00%"

        for col in (10, 11, 14, 15):
            c = ws.cell(row=row, column=col)
            c.font, c.alignment, c.border, c.fill = (
                Font(color="000000", size=11), center(), thin_border(), fill(LIGHT_GRAY))
        for col in list(range(1, 10)) + [12, 13, 16]:
            c = ws.cell(row=row, column=col)
            c.border = thin_border()
            if row <= 60:
                c.fill = fill(LIGHT_YELLOW)

    for rng in ("N12:N500", "O12:O500"):
        col = rng[0]
        ws.conditional_formatting.add(rng, FormulaRule(
            formula=[f'AND({col}12<>"",{col}12>0)'], fill=fill(LIGHT_GREEN),
            font=Font(bold=True, color="1B5E20")))
        ws.conditional_formatting.add(rng, FormulaRule(
            formula=[f'AND({col}12<>"",{col}12<0)'], fill=fill(LIGHT_RED),
            font=Font(bold=True, color="B71C1C")))
    ws.conditional_formatting.add("I12:I500", FormulaRule(
        formula=['I12="W"'], fill=fill(LIGHT_GREEN), font=Font(bold=True, color="1B5E20")))
    ws.conditional_formatting.add("I12:I500", FormulaRule(
        formula=['I12="L"'], fill=fill(LIGHT_RED), font=Font(bold=True, color="B71C1C")))

    # Restore anything the user had already logged.
    for i, rec in enumerate(preserved or []):
        r = 12 + i
        for c, v in enumerate(rec[:9], start=1):      # A..I user-entered
            ws.cell(row=r, column=c, value=v)
        for off, col in enumerate((12, 13, 16)):      # closing line/odds, model edge
            idx = 9 + off
            if len(rec) > idx and rec[idx] is not None and rec[idx] != "":
                ws.cell(row=r, column=col, value=rec[idx])


# ─────────────────────────────────────────────
# BET LOG / HISTORY
# ─────────────────────────────────────────────

LOG_HEADERS = ["Week", "Date", "Game", "Model Picked", "Win Chance", "Confidence",
               "Final Score", "Winner", "Model Right?", "Model Bet", "Bet Type", "Model Bet Result",
               "Your Bet", "Stake", "Your Result", "Your P&L"]
LOG_HEADER_ROW = 8


def _your_bet_outcome(d):
    """(result, pnl) for the Bet Tracker row attached to a game.

    Uses the result typed in the tracker when there is one; otherwise grades
    it from the final score, so the log fills in without extra typing.
    """
    side_text = _text(d.get("bet_side"))
    if not side_text or not d.get("played"):
        return "", None
    typed = _text(d.get("bet_result")).upper()
    res = {"W": "WIN", "L": "LOSS", "PUSH": "PUSH"}.get(typed, "")
    hs, as_ = _num(d.get("home_score")), _num(d.get("away_score"))
    if not res and hs is not None and as_ is not None:
        side = side_text.split()[0]
        margin = (hs - as_) if side == _text(d.get("home")) else (as_ - hs)
        if _text(d.get("bet_market")).upper() == "MONEYLINE":
            cover = margin
        else:
            line = _num(d.get("bet_line"))
            if line is None:
                try:
                    line = float(side_text.split()[1])
                except (IndexError, ValueError):
                    return "", None
            cover = margin + line
        res = "WIN" if cover > 0 else ("PUSH" if cover == 0 else "LOSS")
    if not res:
        return "", None
    stake, odds = _num(d.get("bet_stake")) or 0.0, _num(d.get("bet_odds")) or -110.0
    win = stake * (100 / abs(odds) if odds < 0 else odds / 100)
    return res, (win if res == "WIN" else (-stake if res == "LOSS" else 0.0))


def _sheet_history(wb, hist, season, week):
    """
    Bet Log: one row per game the model has ever picked, in plain terms --
    who it picked, who won, whether it was right, plus the model's bet and
    Jameson's own bet (from the Bet Tracker) and how each did.

    Rows come from the tracked picks/ archive, never a rebuild, so every game
    is scored against what the model actually said at the time.
    """
    ws = wb.create_sheet("Bet Log")
    ws.tab_color = DARK_GOLD
    set_widths(ws, {"A": 7, "B": 9, "C": 13, "D": 13, "E": 11, "F": 11, "G": 18, "H": 9,
                    "I": 13, "J": 14, "K": 21, "L": 15, "M": 17, "N": 8, "O": 12, "P": 10})
    lastc = get_column_letter(len(LOG_HEADERS))
    apply_header(ws, "A1", "BET LOG — who the model picked, who won, and whether it was right",
                 merge_to=f"{lastc}1", size=16)
    ws.row_dimensions[1].height = 30
    _banner(ws, 2, "One row per game. Green = right, red = wrong. \"Model Bet\" is the model's bet; "
                   "\"Bet Type\" says if it backs the model's pick or is a value bet on the other team; \"Your Bet\" is pulled from the Bet Tracker and graded "
                   "from the final score. A few weeks is still mostly luck.", lastc, height=30)

    H = LOG_HEADER_ROW
    first = H + 1
    n_rows = 0 if hist is None or hist.empty else len(hist)
    last = max(first, H + n_rows)
    rng = lambda col: f"${col}${first}:${col}${last}"

    # ── scoreboard: two numbers ──
    apply_section(ws, "A4", "WIN RATES", merge_to="E4")
    right, wrong = f'COUNTIF({rng("I")},"YES")', f'COUNTIF({rng("I")},"NO")'
    vcount = lambda x: f'COUNTIFS({rng("K")},"VALUE — AGAINST PICK",{rng("L")},"{x}")'
    vw, vl = vcount("WIN"), vcount("LOSS")
    board = [
        (5, "Model's pick won the game",
         f'=IFERROR({right}/({right}+{wrong}),"—")', f'={right}&" of "&({right}+{wrong})'),
        (6, "Value picks won",
         f'=IFERROR({vw}/({vw}+{vl}),"—")', f'={vw}&" of "&({vw}+{vl})'),
    ]
    for row, label, pct, count in board:
        lc = ws.cell(row=row, column=1, value=label)
        lc.font, lc.fill, lc.border, lc.alignment = Font(bold=True, size=12), fill(LABEL_FILL), thin_border(), left()
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
        c = ws.cell(row=row, column=4, value=pct)
        c.font, c.alignment, c.border, c.fill = Font(bold=True, color=NAVY, size=14), center(), thin_border(), fill(LIGHT_GRAY)
        c.number_format = "0%"
        n = ws.cell(row=row, column=5, value=count)
        n.font, n.alignment, n.border = Font(color=MUTED, size=10), center(), thin_border()
        ws.row_dimensions[row].height = 24

    # ── the table ──
    def strip_rec(text):
        t = _text(text)
        for p in ("LEAN ", "BET "):
            if t.startswith(p):
                return t[len(p):]
        return t

    rows = []
    if n_rows:
        for _, h in hist.iterrows():
            d = h.to_dict()
            played = bool(_clean(d.get("played")) or False)
            hs, as_ = _num(d.get("home_score")), _num(d.get("away_score"))
            score = (f"{d.get('away')} {as_:.0f} – {d.get('home')} {hs:.0f}"
                     if played and hs is not None and as_ is not None else "not played yet")
            correct = _text(d.get("correct"))
            right = {"Y": "YES", "N": "NO"}.get(correct, "TIE" if _text(d.get("actual_winner")) == "TIE" else "—")
            model_bet = strip_rec(d.get("lean")) or "—"
            model_res = _text(d.get("lean_result")) or ("—" if model_bet == "—" else "pending")
            your_bet = _text(d.get("bet_side"))
            odds = _num(d.get("bet_odds"))
            if your_bet and odds is not None:
                your_bet += f" ({odds:+.0f})"
            your_res, pnl = _your_bet_outcome(d)
            rows.append([
                d.get("week"), _as_date(d.get("gameday")), d.get("matchup"), d.get("pick"),
                _num(d.get("win_prob")), _text(d.get("tier")),
                score, _text(d.get("actual_winner")) or "—", right,
                model_bet, _text(d.get("lean_type")) or "—", model_res,
                your_bet or "—", _num(d.get("bet_stake")) if your_bet else None,
                your_res or ("—" if not your_bet else "pending"), pnl,
            ])
    last = _write_table(
        ws, H, LOG_HEADERS, rows,
        formats={2: "m/d/yy", 5: "0%", 14: '"$"#,##0', 16: '"+$"#,##0.00;"-$"#,##0.00;"$0.00"'},
        bold_cols=(4, 8, 9),
    )
    if n_rows == 0:
        ws.cell(row=first, column=1, value="No picks archived yet — scripts/run_week.py writes them "
                                           "under picks/<season>/.").font = Font(italic=True, color=MUTED)
        return

    def good_bad(col, good, bad):
        ws.conditional_formatting.add(f"{col}{first}:{col}{last}", FormulaRule(
            formula=[f'{col}{first}="{good}"'], fill=fill(LIGHT_GREEN), font=Font(bold=True, color="1B5E20")))
        ws.conditional_formatting.add(f"{col}{first}:{col}{last}", FormulaRule(
            formula=[f'{col}{first}="{bad}"'], fill=fill(LIGHT_RED), font=Font(bold=True, color="B71C1C")))
    good_bad("I", "YES", "NO")
    good_bad("L", "WIN", "LOSS")
    good_bad("O", "WIN", "LOSS")
    ws.conditional_formatting.add(f"P{first}:P{last}", FormulaRule(
        formula=[f"AND(ISNUMBER(P{first}),P{first}>0)"], font=Font(bold=True, color="1B5E20")))
    ws.conditional_formatting.add(f"P{first}:P{last}", FormulaRule(
        formula=[f"AND(ISNUMBER(P{first}),P{first}<0)"], font=Font(bold=True, color="B71C1C")))
    ws.conditional_formatting.add(f"K{first}:K{last}", FormulaRule(
        formula=[f'LEFT(K{first},5)="VALUE"'], font=Font(bold=True, color="E65100")))
    # Picked team = winner: highlight the Winner cell the same way.
    ws.conditional_formatting.add(f"H{first}:H{last}", FormulaRule(
        formula=[f'I{first}="YES"'], font=Font(bold=True, color="1B5E20")))
    ws.conditional_formatting.add(f"H{first}:H{last}", FormulaRule(
        formula=[f'I{first}="NO"'], font=Font(bold=True, color="B71C1C")))
    # A thin rule between weeks so each week reads as a block.
    for r in range(first + 1, last + 1):
        if ws.cell(row=r, column=1).value != ws.cell(row=r - 1, column=1).value:
            for j in range(1, len(LOG_HEADERS) + 1):
                c = ws.cell(row=r, column=j)
                c.border = Border(left=c.border.left, right=c.border.right, bottom=c.border.bottom,
                                  top=Side(style="medium", color=NAVY))


# ─────────────────────────────────────────────
# REFERENCE
# ─────────────────────────────────────────────

SHEET_GUIDE = [
    ("Picks", "Every game as a straight-up winner ranked by win probability, with the assumed starting quarterbacks. Predictions, not bets."),
    ("Weekly Slate", "Every game with date, kickoff, moneylines, spread, total, the model's line, the edge (shaded by size) and the verdict. NO BET rows are grayed."),
    ("Miss Report", "Why the model gets games wrong: the reasons it now corrects for (consistent in 2013-2020 AND 2021+), the ones it is watching, the underdog win-rate check, and this season's misses with luck-vs-model."),
    ("Model Picks %", "Model win probability for each side (sums to 100%) next to the de-vigged market probability, so the disagreement is visible per side."),
    ("Game Detail", "The matchup picker: choose a game from the dropdown and every cell looks up that game — ratings, QB terms, home field, market prior, cover/push, moneyline edges, the ticket."),
    ("Team Stats", "One row per team: record, points for/against, differential, ATS record, rating and rank, starting QB and where that name came from, roster by position group, the injured list with expected returns."),
    ("Power Ratings", "The fitted ratings entering this week, in points against an average team."),
    ("Bet Tracker", "Where you log what you would take and the number you saw. CLV and P&L calculate; rows survive re-runs and mirror to data/bet_log.csv."),
    ("Bet Log", "One row per game: who the model picked, who won, whether it was right, the model's bet and your bet with results. Win rate of the model's picks and of its value picks at the top."),
    ("Rosters / Injuries", "The player-level detail behind Team Stats, one row per player, filterable."),
]


# ─────────────────────────────────────────────
# MISS REPORT
# ─────────────────────────────────────────────

MISS_STATUS_TEXT = {"confirmed": "FIXED — in the model", "watching": "watching",
                    "absorbed": "covered by the fixes already in",
                    "no pattern": "no pattern",
                    "rejected": "made 2021+ worse alongside the others"}


def _sheet_miss_report(wb, state):
    """
    Why the model misses, from data/trends.json (scripts/miss_report.py).

    A reason is only corrected when it shows up in 2013-2020 AND again in
    2021 onward. One game, or one week, never changes the model.
    """
    ws = wb.create_sheet("Miss Report")
    ws.tab_color = "C62828"
    set_widths(ws, {"A": 52, "B": 11, "C": 13, "D": 13, "E": 13, "F": 13, "G": 14, "H": 44})
    apply_header(ws, "A1", "MISS REPORT — why the model gets games wrong, and what it corrects",
                 merge_to="H1", size=16)
    ws.row_dimensions[1].height = 30
    if not state:
        _banner(ws, 2, "No trend check yet. Run scripts/miss_report.py after a week is graded.",
                "H", height=24)
        return
    h = state.get("history", {})
    _banner(ws, 2, f"Checked {h.get('n_games', 0):,} graded games ({h.get('first_season')}-"
                   f"{h.get('last_season')}, incl. {h.get('current_season_graded', 0)} of this "
                   f"season's picks), run {str(state.get('generated_utc', ''))[:10]}. A reason is "
                   "fixed only when it shows up in 2013-2020 AND again in 2021+ — one game or one "
                   "week never moves the model. Effects are points vs the model's projection, "
                   "for the team named in the reason.", "H", height=46)

    row = 4
    mt = state.get("margin_trends", [])
    fmt_pts = "+0.0;-0.0"

    def trend_rows(rows):
        out = []
        for r in rows:
            out.append([r["text"], r.get("n_disc", 0) + r.get("n_conf", 0),
                        r.get("effect_disc"), r.get("effect_conf"),
                        r.get("n_season", 0), r.get("effect_season"),
                        r.get("live_shift") if r.get("status") == "confirmed" else None,
                        MISS_STATUS_TEXT.get(r.get("status"), r.get("status"))])
        return out

    headers = ["Reason", "Games", "2013-2020", "2021+", "This season (games)",
               "This season", "Correction", "Status"]
    for title, statuses in (("FIXES IN THE MODEL NOW", ("confirmed",)),
                            ("WATCHING — showed up, but not consistently enough to change the model",
                             ("watching", "absorbed", "rejected"))):
        apply_section(ws, f"A{row}", title, merge_to=f"H{row}")
        rows = trend_rows([r for r in mt if r.get("status") in statuses])
        if statuses == ("confirmed",):
            cal = state.get("calibration", {})
            if cal.get("status") == "confirmed":
                rows.append(["Moneyline win % for underdogs (overrated — see below)", cal.get("n_conf", 0)
                             + cal.get("n_disc", 0), None, None, None, None, None,
                             "FIXED — recalibrated"])
            from .config import THRESHOLDS
            trend_cap = (state.get("bet_filters") or {}).get("ml_max_underdog")
            cap = min(THRESHOLDS.ml_max_underdog, trend_cap or 10 ** 6)
            source = "learned cap" if trend_cap and trend_cap <= THRESHOLDS.ml_max_underdog \
                else "Jameson's rule (set in config)"
            rows.append([f"Longshot moneylines: none longer than +{cap}", None, None, None,
                         None, None, None, f"ON — {source}"])
        last = _write_table(ws, row + 1, headers, rows or [["none"] + [None] * 7],
                            formats={3: fmt_pts, 4: fmt_pts, 6: fmt_pts, 7: fmt_pts},
                            aligns={1: "left", 8: "left"}, freeze=False, autofilter=False)
        row = last + 2

    cal = state.get("calibration", {})
    if cal.get("table"):
        apply_section(ws, f"A{row}", "LONGSHOT CHECK — how often underdogs actually won",
                      merge_to=f"H{row}")
        rows = [[f"{t['block']}: underdog {t['bucket']}", t["n"], t["actual"], t["market"],
                 t["model"], t["model_fixed"], None, None] for t in cal["table"]]
        last = _write_table(ws, row + 1, ["Underdog price", "Games", "Actually won",
                                          "Market said", "Model said (old)", "Model says (fixed)",
                                          "", ""], rows,
                            formats={3: "0.0%", 4: "0.0%", 5: "0.0%", 6: "0.0%"},
                            aligns={1: "left"}, freeze=False, autofilter=False)
        row = last + 2

    misses = state.get("misses", [])
    apply_section(ws, f"A{row}", "THIS SEASON'S MISSES — picked the wrong winner",
                  merge_to=f"H{row}")
    rows = [[f"Wk {m['week']}: {m['matchup']}", m["pick"], m["projected"], m["actual"],
             None, None, m.get("luck", ""), m.get("reasons", "")] for m in misses]
    last = _write_table(ws, row + 1, ["Game", "Picked", "Projected", "Actual", "", "",
                                      "Luck or model?", "Conditions present"],
                        rows or [["none yet"] + [None] * 7],
                        formats={3: fmt_pts, 4: fmt_pts}, aligns={1: "left", 7: "left", 8: "left"},
                        freeze=False, autofilter=False)
    _fit_row_heights(ws, row + 2, last, {7: 13, 8: 44})
    row = last + 2

    none = [r["text"] for r in mt if r.get("status") == "no pattern"]
    if none:
        apply_section(ws, f"A{row}", "TESTED, NO PATTERN (the line or the model already handles these)",
                      merge_to=f"H{row}")
        ws.cell(row=row + 1, column=1, value="; ".join(none)).alignment = Alignment(
            wrap_text=True, vertical="top")
        ws.merge_cells(start_row=row + 1, start_column=1, end_row=row + 1, end_column=8)
        ws.row_dimensions[row + 1].height = 60


def _sheet_reference(wb, backtest_summary, model_meta=None):
    ws = wb.create_sheet("Reference & Glossary")
    ws.tab_color = GRAY_BLUE
    set_widths(ws, {"A": 30, "B": 100})
    model_meta = model_meta or {}

    apply_header(ws, "A1", "REFERENCE & GLOSSARY", merge_to="B1", size=16)
    ws.row_dimensions[1].height = 30

    row = 3

    def section(title):
        nonlocal row
        apply_section(ws, f"A{row}", title, merge_to="B" + str(row))
        row += 1

    def entry(term, text, emphasis=False):
        nonlocal row
        c = ws.cell(row=row, column=1, value=term)
        c.font, c.fill, c.border, c.alignment = Font(bold=True, color="000000", size=11), fill(LABEL_FILL), thin_border(), left()
        d = ws.cell(row=row, column=2, value=_safe_text(text))
        d.font = Font(color="B71C1C" if emphasis else "000000", size=11, bold=emphasis)
        d.border, d.alignment = thin_border(), left()
        ws.row_dimensions[row].height = max(18, 15 * (len(text) // 105 + 1) + 3)
        row += 1

    section("READ THIS FIRST — WHAT THE VALIDATION SAYS")
    entry("Verdict", "This model has no demonstrated edge against NFL closing lines. It ships in ADVISORY MODE: "
                     "every sheet reports LEANs, not BETs, and stakes $0. That default is a measured finding, not "
                     "an unfinished feature.", emphasis=True)
    entry("Hold-out, bare ratings", f"{HOLDOUT['bare_ats']} ({HOLDOUT['seasons']}). {HOLDOUT['breakeven']}.")
    entry("Hold-out, deployed model", f"{HOLDOUT['deployed_ats']}. {HOLDOUT['mae']}. The lower error is more deference to the market, not model improvement.")
    entry("Moneyline", HOLDOUT["ml"] + ".")
    entry("The decisive test", "Regress actual results on both the closing line and the model's projection: " + HOLDOUT["coef"] + ".")
    entry("Tuning seasons looked good", "2013-20 showed 53.2% ATS and +1.6% ROI. That gap between tuning and hold-out IS the overfitting, made visible. Never quote tuning-season numbers as results.")
    entry("What would change this", "Closing line value. Log leans on the Bet Tracker at the numbers you can get; after ~40-50 picks, consistently positive CLV is the first real evidence. Flat or negative means the hold-out was right.")
    entry("Mode this run", ("Advisory (LEANs, $0)" if model_meta.get("advisory", True) else "LIVE STAKING — ADVISORY_MODE is off")
                           + (f"; home field {model_meta['hfa']:+.2f} pts" if model_meta.get("hfa") is not None else "")
                           + (f"; market prior weight {model_meta['market_prior_weight']:.0%}" if model_meta.get("market_prior_weight") is not None else "")
                           + (f"; depth chart snapshot {model_meta['qb_snapshot']}" if model_meta.get("qb_snapshot") else "") + ".")
    entry("Totals", "Shown on the slate as the market's number for context only. This is a margin model; it does not project totals, and a total is never a lean.")

    section("SHEETS IN THIS WORKBOOK")
    for name, text in SHEET_GUIDE:
        entry(name, text)

    section("HOW THE MODEL WORKS")
    entry("Power rating", "Each team's strength in points versus an average team on a neutral field, fit by ridge regression across every game so it is opponent-adjusted.")
    entry("Regression target", "Scoring margin. An EPA blend was designed and tested: accuracy degrades monotonically as EPA weight rises, so the fitted weight is zero.")
    entry("Quarterback", "Team and QB are fit jointly, so a rating reflects who is actually starting. About 15% of team-games are started by a non-primary QB, and that swing is worth ~6 points. A QB without enough starts is pooled at replacement level.")
    entry("Market prior", "Early in the season ratings are blended toward ratings backed out of posted spreads (Week 1 ≈ 80% market). The model has seen no current-season football; the line has priced every offseason move. The weight decays as games are played.")
    entry("Model line", "home rating − away rating + home field advantage. This is the spread the model would set.")
    entry("Edge (points)", "Model line minus the Vegas line. The model's disagreement with the market.")
    entry("Home field", "Fitted from data at ~2.1 points, not the folk-wisdom 3. It was 0.2 in the fanless 2020 season, which is good evidence the effect is crowd-driven.")
    entry("Key numbers", "Margin → probability by exponential tilting of the empirical margin distribution, which preserves the spikes at 3 and 7. A whole-number line therefore carries real push probability.")

    section("MARKET TERMS")
    entry("Vig / juice", "The book's built-in margin. Two sides at -110 imply 104.8% total probability; the 4.8% excess is the hold.")
    entry("De-vigging", "Stripping the vig to recover the market's true opinion. Comparing your model to raw implied odds overstates or understates your edge on every bet — this model always de-vigs first.")
    entry("Push", "The margin lands exactly on the spread and the stake is returned. Real money: whole-number spreads push about 2.7% of the time, and ignoring that overstates edge.")
    entry("Closing line value (CLV)", "Whether the number you bet was better than the number at kickoff. The earliest reliable signal that a model has genuine edge — it shows up in weeks, where profit takes seasons.")
    entry("Break-even at -110", "52.38%. Anything below that loses money no matter how it feels.")

    section("STAKING")
    entry("Kelly criterion", "Stake sized to the edge and the odds. Full Kelly maximizes long-run growth but swings violently.")
    entry("Half Kelly", f"This model stakes at {STAKING.kelly_fraction:.0%} of Kelly, capped at {STAKING.max_bet_pct:.1%} of bankroll and {STAKING.max_weekly_exposure_pct:.0%} per week — roughly three-quarters of the growth at half the volatility. In advisory mode every stake is $0.")

    section("WHAT THE BACKTEST FOUND")
    if backtest_summary:
        entry("Method", "Walk-forward: to predict week W the model only ever sees games finished before week W, and is refit from scratch each week. No result the model is scored on informs it.")
        entry("Games scored", f"{backtest_summary.get('n_games', 0):,} games, {backtest_summary.get('seasons','')}")
        entry("Model error (MAE)", f"{backtest_summary.get('model_mae', 0):.2f} points per game")
        entry("Closing line error (MAE)", f"{backtest_summary.get('market_mae', 0):.2f} points per game")
        entry("Verdict", backtest_summary.get("verdict", ""))
    entry("Situational factors", "Rest, weather, travel, divisional games and Week 17-18 spots were each measured against 5,431 games of closing lines. None showed mispricing at even |t|=2, so all ship at zero. They are not missing — they were tested and rejected.")
    entry("Injuries", "An aggregate injury-burden term was measured too: pooled it looks like an edge, but it fails season-clustering, loses money in six of twelve seasons, and stale absences carry more signal than fresh ones. It ships at zero; the roster data earns its place through the quarterback and through the Team Stats sheet.")

    section("HONEST LIMITS")
    entry("The line is very good", "The closing spread is among the most accurate forecasts in any domain. Most public models do not beat it, and a model that claims a large edge is usually leaking future information.")
    entry("Sample size", "A 53% ATS model needs hundreds of bets before its win rate is distinguishable from noise. Judge this by CLV first and P&L much later.")
    entry("Bet what you can lose", "Sizing rules only control the rate of ruin. They do not remove it.")
