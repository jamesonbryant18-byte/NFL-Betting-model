"""
history.py — every pick the model ever published, graded, with the bets
that were actually logged against it.

Three records exist and none of them knows about the others:

  picks/<season>/week<NN>_*        what the model said, frozen at publish
                                   time (archive.py refuses to rewrite it)
  data.load_games()                what actually happened, from nflverse
  the Bet Tracker (betlog.py)      what Jameson did about it, by hand

review_week.py joins the first two for ONE week and prints a verdict. This
module joins all three for EVERY archived week into one flat frame, so the
workbook can carry a running record that survives the weekly rebuild and so
the paper-trade decision gate in OPERATING.md (accumulate CLV over ~40-50
picks, then decide) is read off a table rather than reconstructed by hand.

Grading is deliberately a copy of review_week.py's rules rather than a
refactor of them. The archive is the only evidence that will ever settle
whether this model works; two graders that could drift apart would leave
that evidence arguable. If review_week changes, change grade_pick and
grade_lean to match -- the tests pin the current behaviour.

Nothing here is a model input. The frame is descriptive. A bad week in it
is, per review_week's own warning, almost always noise.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from . import archive as _archive
from .betlog import clv_for_row, normalize_matchup, parse_row

# Column order of the frame build_history returns. Fixed so the workbook
# sheet that renders it can rely on positions.
HISTORY_COLUMNS = [
    "season", "week", "gameday", "matchup", "away", "home",
    "pick", "pick_at_home", "win_prob", "tier", "proj_margin",
    "market_favorite", "moneyline",
    "lean", "lean_market", "lean_side", "lean_odds", "lean_conf", "lean_line",
    "lean_type", "lean_why",
    "played", "actual_winner", "home_score", "away_score", "result",
    "correct", "lean_result",
    "bet", "n_bets", "bet_market", "bet_side", "bet_line", "bet_odds",
    "bet_stake", "bet_result", "closing_line", "closing_odds",
    "clv_pts", "clv_prob", "model_edge",
    "locked", "generated_utc",
    "running_graded", "running_correct", "running_acc",
]

# Columns that hold numbers; NaN when unknown (see build_history).
NUMERIC_COLUMNS = [
    "win_prob", "proj_margin", "moneyline", "lean_odds", "lean_line",
    "home_score", "away_score", "result", "bet_line", "bet_odds", "bet_stake",
    "closing_line", "closing_odds", "clv_pts", "clv_prob", "model_edge",
]

# Confidence tiers in the order the Picks sheet and review_week print them.
TIER_ORDER = ["strong", "solid", "lean", "slight", "coin flip"]

# A tracker row without a week is matched to a game by date. Bets are logged
# from the Tuesday lines open to the Monday night kickoff, so a week of slack
# either side covers every honest entry without reaching into the next week's
# copy of the same matchup (which cannot recur inside seven days anyway).
DATE_MATCH_WINDOW = timedelta(days=7)

_PICKS_RE = re.compile(r"^week(\d+)_picks\.csv$")


# ─────────────────────────────────────────────
# SMALL HELPERS
# ─────────────────────────────────────────────

def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Field access that works for a dict, a Series, or None."""
    if obj is None:
        return default
    try:
        v = obj.get(key, default)
    except AttributeError:
        v = getattr(obj, key, default)
    return default if v is None else v


def _num(v: Any) -> Optional[float]:
    """float or None; NaN, blanks and unparseable text all become None."""
    if v is None or isinstance(v, bool):
        return None if v is None else float(v)
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _text(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and math.isnan(v):
        return ""
    return str(v).strip()


def _bool(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "y", "t")
    try:
        return bool(v) and not (isinstance(v, float) and math.isnan(v))
    except (TypeError, ValueError):
        return False


def _as_date(v: Any) -> Optional[date]:
    """A gameday from the games frame (Timestamp, NaT, str) as a date."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return None if pd.isna(v) else v.date()
    if isinstance(v, date):
        return v
    try:
        ts = pd.to_datetime(v, errors="coerce")
    except (TypeError, ValueError):
        return None
    return None if pd.isna(ts) else ts.date()


def _read_csv_or_empty(path: Path) -> pd.DataFrame:
    """A header-only or missing CSV is an empty frame, not an exception."""
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


# ─────────────────────────────────────────────
# THE ARCHIVE
# ─────────────────────────────────────────────

def load_all_archives(archive_dir=None) -> list[dict]:
    """
    Every archived week, oldest first.

    Each entry is {season, week, picks, leans, meta}. `leans` may be an
    empty frame (a week with no disagreement is still a week) and `meta`
    may be {} (a week archived before the meta file existed). The archive
    root is read from archive.ARCHIVE_DIR at call time rather than imported
    once, so tests can point it at a temporary directory the way
    test_archive_refuses_to_rewrite_a_locked_week does.
    """
    root = Path(archive_dir) if archive_dir is not None else Path(_archive.ARCHIVE_DIR)
    if not root.is_dir():
        return []

    out: list[dict] = []
    for season_dir in root.iterdir():
        if not season_dir.is_dir() or not season_dir.name.isdigit():
            continue
        season = int(season_dir.name)
        for picks_path in season_dir.glob("week*_picks.csv"):
            m = _PICKS_RE.match(picks_path.name)
            if not m:
                continue
            week = int(m.group(1))
            stem = f"week{week:02d}"
            picks = _read_csv_or_empty(picks_path)
            leans = _read_csv_or_empty(season_dir / f"{stem}_leans.csv")
            meta_path = season_dir / f"{stem}_meta.json"
            meta: dict = {}
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text())
                except (OSError, ValueError):
                    meta = {}
            out.append({"season": season, "week": week, "picks": picks,
                        "leans": leans, "meta": meta})

    out.sort(key=lambda a: (a["season"], a["week"]))
    return out


# ─────────────────────────────────────────────
# GRADING — a copy of review_week.py's rules
# ─────────────────────────────────────────────

def grade_pick(pick, game) -> dict:
    """
    Score one straight-up pick against one game.

    `pick` carries winner / loser / at_home as archived; `game` is the
    matching games.csv row, or None when nflverse has no such game. Returns
    played, actual_winner, home_score, away_score, result and correct, where
    correct is 'Y', 'N' or '' (ungraded).

    A tie is played but ungraded -- review_week skips result == 0 rather
    than calling the pick wrong, because a pick was never offered 'tie' as
    an option. actual_winner reads 'TIE' so the row explains itself.
    """
    result = _num(_get(game, "result"))
    if game is None or result is None:
        return {"played": False, "actual_winner": "", "home_score": None,
                "away_score": None, "result": None, "correct": ""}

    home = _text(_get(game, "home_team"))
    away = _text(_get(game, "away_team"))
    hs, as_ = _num(_get(game, "home_score")), _num(_get(game, "away_score"))
    out = {"played": True,
           "home_score": int(hs) if hs is not None else None,
           "away_score": int(as_) if as_ is not None else None,
           "result": result}

    if result == 0:
        out.update(actual_winner="TIE", correct="")
        return out

    actual = home if result > 0 else away
    picked = _text(_get(pick, "winner"))
    out.update(actual_winner=actual, correct="Y" if actual == picked else "N")
    return out


def grade_lean(lean, game) -> str:
    """
    'WIN', 'LOSS', 'PUSH' or '' for one archived lean against one game.

    Identical arithmetic to review_week.py: the side is the first token of
    bet_side; a moneyline wins when the side won outright; a spread is
    judged with the line AS PUBLISHED on the lean row (spread_line, in the
    home-favored-by convention), flipped to the bettor's side. A rebuilt or
    closing line is never used -- the lean is graded against the number it
    was made at, or it is not a record of the lean.

    review_week only knows win/not-win. This adds PUSH for the exact landing
    (and for a tie on a moneyline) so a returned stake is not booked as a
    loss. Ungradeable (unplayed, no lean, no line) is ''.
    """
    result = _num(_get(game, "result"))
    if lean is None or game is None or result is None:
        return ""

    side_text = _text(_get(lean, "bet_side"))
    if not side_text:
        return ""
    side = side_text.split()[0]
    home = _text(_get(game, "home_team"))
    market = _text(_get(lean, "bet_market")).upper()

    if market == "MONEYLINE":
        if result == 0:
            return "PUSH"
        return "WIN" if (result > 0) == (side == home) else "LOSS"

    line = _num(_get(lean, "spread_line"))
    if line is None:
        return ""
    margin = result if side == home else -result
    line = line if side == home else -line
    if margin > line:
        return "WIN"
    if margin == line:
        return "PUSH"
    return "LOSS"


# ─────────────────────────────────────────────
# JOINING THE TRACKER
# ─────────────────────────────────────────────

def match_bets(bets: list[dict], season: int, week: int, matchup: str,
               gameday: Optional[date]) -> list[dict]:
    """
    The tracker rows that were bets on this game.

    `bets` are parse_row dicts. A row matches on normalised matchup plus
    the week when the week was typed; a row with no week falls back to the
    date, which must sit within DATE_MATCH_WINDOW of kickoff. A row with
    neither week nor date matches on matchup alone.

    A typed date is also required to fall inside the season it is being
    matched to (an NFL season spans the calendar year and the next), so a
    week-1 bet from one year does not attach itself to week 1 of every
    later season as well.
    """
    target = normalize_matchup(matchup)
    if not target:
        return []
    gd = _as_date(gameday)
    out = []
    for b in bets:
        if b.get("matchup") != target:
            b = _loose_match(b, target)
            if b is None:
                continue
        bd = b.get("date")
        if bd is not None and season is not None and bd.year not in (int(season), int(season) + 1):
            continue
        wk = b.get("week")
        if wk is not None:
            if int(wk) != int(week):
                continue
        elif bd is not None and gd is not None:
            if abs(bd - gd) > DATE_MATCH_WINDOW:
                continue
        out.append(b)
    return out


def _loose_match(b: dict, target: str) -> Optional[dict]:
    """
    A hand-typed matchup that names this game less exactly: 'TEN @ NY' for
    TEN @ NYG (2026 Week 3 -- a win the review could not see). One team must
    match exactly and the other must be the start of the real code; a row
    with neither week nor date never matches loosely, because only the week
    makes it unambiguous (a team plays once a week).

    Returns a COPY with the game's codes in matchup and bet_side, so the
    graders (which key on the side's team code) see NYG, not NY. The tracker
    itself is never changed. None when it is not this game.
    """
    typed_away, sep, typed_home = str(b.get("matchup") or "").partition(" @ ")
    away, _, home = target.partition(" @ ")
    if not sep or (b.get("week") is None and b.get("date") is None):
        return None

    def fits(typed: str, real: str) -> bool:
        return typed == real or (len(typed) >= 2 and real.startswith(typed))

    exact = (typed_away == away) + (typed_home == home)
    if exact == 0 or not (fits(typed_away, away) and fits(typed_home, home)):
        return None

    side = str(b.get("bet_side") or "")
    word, space, rest = side.partition(" ")
    if word and word not in (away, home):
        hits = [t for t, typed in ((away, typed_away), (home, typed_home))
                if word == typed or (len(word) >= 2 and t.startswith(word))]
        if len(hits) == 1:
            side = hits[0] + space + rest
    return {**b, "matchup": target, "bet_side": side}


def _parsed_bets(tracker_rows) -> list[dict]:
    """Raw tracker rows (or already-parsed dicts) as parse_row dicts."""
    out = []
    for r in tracker_rows or []:
        if isinstance(r, dict) and "matchup" in r and "bet_side" in r:
            out.append(r)
        else:
            out.append(parse_row(r))
    return out


def _game_index(games: Optional[pd.DataFrame], season: int, week: int) -> dict:
    """(home, away) -> games row for one week, or {} if the frame lacks it."""
    if games is None or len(games) == 0:
        return {}
    need = {"season", "week", "home_team", "away_team"}
    if not need.issubset(games.columns):
        return {}
    wk = games[(games["season"] == season) & (games["week"] == week)]
    index: dict = {}
    for _, g in wk.iterrows():
        key = (_text(g["home_team"]), _text(g["away_team"]))
        index.setdefault(key, g)
    return index


def _lean_type(lean, pick: str, home: str) -> str:
    """ON MODEL'S PICK / VALUE — AGAINST PICK for an archived lean.

    Archives from before 2026-09-14 have no bet_type column, so it is derived
    from the side and the pick, the same rule model.project uses.
    """
    if lean is None:
        return ""
    stored = _text(_get(lean, "bet_type"))
    if stored:
        return stored
    side = _text(_get(lean, "bet_side")).split()
    if not side:
        return ""
    return "ON MODEL'S PICK" if side[0] == pick else "VALUE — AGAINST PICK"


def _lean_index(leans: Optional[pd.DataFrame]) -> dict:
    """(home, away) -> first lean row for that game."""
    if leans is None or len(leans) == 0:
        return {}
    if not {"home_team", "away_team"}.issubset(leans.columns):
        return {}
    index: dict = {}
    for _, l in leans.iterrows():
        index.setdefault((_text(l["home_team"]), _text(l["away_team"])), l)
    return index


# ─────────────────────────────────────────────
# THE FRAME
# ─────────────────────────────────────────────

def build_history(games: Optional[pd.DataFrame], tracker_rows,
                  pts_table=None, archive_dir=None) -> pd.DataFrame:
    """
    One row per archived pick, graded, with any logged bet attached.

    Rows are ordered season, week, rank -- the order the picks were
    published -- and the running_* columns accumulate in that order, so the
    last row's running_acc is the model's straight-up record to date.

    A game the archive has but the games frame does not (nflverse lagging,
    a cached frame from before the schedule changed) still appears, just
    ungraded; the archive is the record, the games frame only scores it.

    Several tracker rows can legitimately belong to one game (a spread and
    a moneyline, say). The first is shown in the bet_* columns and n_bets
    says how many there were; the tracker itself remains the full record.
    """
    bets = _parsed_bets(tracker_rows)
    rows: list[dict] = []

    for arc in load_all_archives(archive_dir):
        season, week = int(arc["season"]), int(arc["week"])
        picks, leans, meta = arc["picks"], arc["leans"], arc["meta"] or {}
        if picks is None or len(picks) == 0:
            continue
        if "rank" in picks.columns:
            picks = picks.sort_values("rank", kind="stable")

        game_idx = _game_index(games, season, week)
        lean_idx = _lean_index(leans)
        locked = _bool(meta.get("locked", False))
        generated = _text(meta.get("generated_utc", ""))

        for _, p in picks.iterrows():
            winner, loser = _text(p.get("winner")), _text(p.get("loser"))
            at_home = _bool(p.get("at_home"))
            home, away = (winner, loser) if at_home else (loser, winner)
            matchup = normalize_matchup(p.get("matchup")) or f"{away} @ {home}"

            game = game_idx.get((home, away))
            gameday = _as_date(_get(game, "gameday"))
            graded = grade_pick(p, game)

            lean = lean_idx.get((home, away))
            lean_result = grade_lean(lean, game) if lean is not None else ""

            # A game carried forward by a mid-week rerun keeps the time it
            # was actually published, not the rerun's.
            carried = (meta.get("carried") or {}).get(matchup) or {}
            row_generated = _text(carried.get("generated_utc") or generated)

            matched = match_bets(bets, season, week, matchup, gameday)
            first = matched[0] if matched else None
            clv_pts, clv_prob = clv_for_row(first, pts_table) if first else (None, None)

            rows.append({
                "season": season, "week": week, "gameday": gameday,
                "matchup": matchup, "away": away, "home": home,
                "pick": winner, "pick_at_home": at_home,
                "win_prob": _num(p.get("win_prob")),
                "tier": _text(p.get("confidence")),
                "proj_margin": _num(p.get("proj_margin")),
                "market_favorite": _bool(p.get("market_favorite")),
                "moneyline": _num(p.get("moneyline")),
                "lean": _text(_get(lean, "recommendation")),
                "lean_market": _text(_get(lean, "bet_market")).upper(),
                "lean_side": _text(_get(lean, "bet_side")),
                "lean_odds": _num(_get(lean, "bet_odds")),
                "lean_conf": _text(_get(lean, "confidence")),
                "lean_line": _num(_get(lean, "spread_line")),
                "lean_type": _lean_type(lean, winner, home),
                "lean_why": _text(_get(lean, "bet_why")),
                "played": graded["played"],
                "actual_winner": graded["actual_winner"],
                "home_score": graded["home_score"],
                "away_score": graded["away_score"],
                "result": graded["result"],
                "correct": graded["correct"],
                "lean_result": lean_result,
                "bet": "Y" if first else "N",
                "n_bets": len(matched),
                "bet_market": first["market"] if first else "",
                "bet_side": first["bet_side"] if first else "",
                "bet_line": first["line_taken"] if first else None,
                "bet_odds": first["odds"] if first else None,
                "bet_stake": first["stake"] if first else None,
                "bet_result": first["result"] if first else "",
                "closing_line": first["closing_line"] if first else None,
                "closing_odds": first["closing_odds"] if first else None,
                "clv_pts": clv_pts,
                "clv_prob": clv_prob,
                "model_edge": first["model_edge"] if first else None,
                "locked": locked,
                "generated_utc": row_generated,
            })

    hist = pd.DataFrame(rows, columns=HISTORY_COLUMNS)
    # Missing numbers are NaN in a float64 column, never None in an object
    # column, so the dtype does not change between an unplayed week and a
    # played one (pandas would otherwise leave an all-None column as object).
    for col in NUMERIC_COLUMNS:
        hist[col] = pd.to_numeric(hist[col], errors="coerce").astype(float)
    graded_flag = hist["correct"].isin(["Y", "N"])
    hist["running_graded"] = graded_flag.cumsum().astype(int)
    hist["running_correct"] = (hist["correct"] == "Y").cumsum().astype(int)
    hist["running_acc"] = (hist["running_correct"] / hist["running_graded"]
                           ).where(hist["running_graded"] > 0)
    return hist


# ─────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────

def _ratio(num: float, den: float) -> Optional[float]:
    return float(num) / float(den) if den else None


def _mean(series: pd.Series) -> Optional[float]:
    s = pd.to_numeric(series, errors="coerce").dropna()
    return float(s.mean()) if len(s) else None


def summarize_history(hist: pd.DataFrame) -> dict:
    """
    The numbers the workbook's history header shows, from a build_history
    frame.

    overall   straight-up record over every graded pick
    by_tier   calibration: what the model said (mean win_prob) against what
              happened (share correct), per confidence tier, over graded
              picks only so the two are comparable. Tiers with no picks are
              omitted, as review_week does.
    leans     WIN / LOSS / PUSH counts over graded leans
    by_week   the same per archived week, oldest first
    clv       average closing line value over logged bets that have a close

    Ratios are None, not 0.0, when there is nothing to divide by; a 0%
    accuracy and an unplayed week must not look alike.
    """
    if hist is None or len(hist) == 0:
        return {"overall": {"graded": 0, "correct": 0, "accuracy": None},
                "by_tier": [], "leans": {"graded": 0, "wins": 0, "losses": 0,
                                         "pushes": 0},
                "by_week": [], "clv": {"n": 0, "avg_clv_pts": None,
                                       "avg_clv_prob": None}}

    graded_mask = hist["correct"].isin(["Y", "N"])
    correct_mask = hist["correct"] == "Y"
    g, c = int(graded_mask.sum()), int(correct_mask.sum())
    overall = {"graded": g, "correct": c, "accuracy": _ratio(c, g)}

    by_tier = []
    tiers = list(hist["tier"].astype(str).unique())
    ordered = [t for t in TIER_ORDER if t in tiers] + \
              sorted(t for t in tiers if t not in TIER_ORDER)
    for tier in ordered:
        t = hist[hist["tier"].astype(str) == tier]
        tg = t[t["correct"].isin(["Y", "N"])]
        n_correct = int((tg["correct"] == "Y").sum())
        by_tier.append({
            "tier": tier, "n": int(len(t)), "graded": int(len(tg)),
            "correct": n_correct,
            "said": _mean(tg["win_prob"]) if len(tg) else None,
            "actual": _ratio(n_correct, len(tg)),
        })

    lr = hist["lean_result"].astype(str)
    wins, losses, pushes = (int((lr == "WIN").sum()), int((lr == "LOSS").sum()),
                            int((lr == "PUSH").sum()))
    leans = {"graded": wins + losses + pushes, "wins": wins,
             "losses": losses, "pushes": pushes}

    by_week = []
    for (season, week), w in hist.groupby(["season", "week"], sort=True):
        wg = w[w["correct"].isin(["Y", "N"])]
        wc = int((wg["correct"] == "Y").sum())
        wlr = w["lean_result"].astype(str)
        by_week.append({
            "season": int(season), "week": int(week), "n": int(len(w)),
            "graded": int(len(wg)), "correct": wc,
            "accuracy": _ratio(wc, len(wg)),
            "leans_graded": int(wlr.isin(["WIN", "LOSS", "PUSH"]).sum()),
            "leans_won": int((wlr == "WIN").sum()),
        })

    with_bet = hist[hist["bet"] == "Y"]
    clv = {"n": int(len(with_bet)),
           "avg_clv_pts": _mean(with_bet["clv_pts"]),
           "avg_clv_prob": _mean(with_bet["clv_prob"])}

    return {"overall": overall, "by_tier": by_tier, "leans": leans,
            "by_week": by_week, "clv": clv}
