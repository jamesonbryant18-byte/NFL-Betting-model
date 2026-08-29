"""
odds.py -- live per-book NFL odds.

Replaces the static nflverse `spread_line` for live-slate use.

Sources (all free, all keyless):
  action_network  6 real books + consensus + opening line.  THE line-shopping source.
  espn            DraftKings only, but carries the nflverse `espn` game id.
  bovada          one extra book, keyless, no UA needed.

SIGN CONVENTION (matches nflverse `spread_line`):
    spread > 0  =>  HOME favored by that many points.
Every adapter converts into this convention. Verified in-repo against
data/cache/dataset_2010_2025.parquet.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Iterable

import pandas as pd

# nflverse abbreviations are canonical.
ESPN_TEAM_FIX = {"LAR": "LA", "WSH": "WAS"}
AN_TEAM_FIX = {"JAC": "JAX"}

AN_BOOKS = {
    15: "consensus", 30: "open", 68: "draftkings", 69: "fanduel",
    75: "betmgm", 79: "bet365", 123: "caesars", 247: "unibet",
}
# Books that are actual bookmakers you can bet at (excludes consensus/open).
AN_REAL_BOOKS = {68, 69, 75, 79, 123, 247}

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

COLUMNS = ["game", "commence_time", "book", "spread", "spread_odds",
           "away_spread_odds", "home_ml", "away_ml", "home_team", "away_team",
           "espn_id", "source"]


def _get(url: str, ua: bool = True, timeout: int = 20):
    req = urllib.request.Request(url)
    if ua:
        req.add_header("User-Agent", _UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _frame(rows) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=COLUMNS)
    if len(df):
        # Bovada sends epoch-ms, ESPN/Action Network send ISO-8601. Normalize
        # to a single tz-aware UTC timestamp or downstream comparisons silently
        # compare a string to an int.
        t = df["commence_time"]
        num = pd.to_numeric(t, errors="coerce")
        out = pd.to_datetime(t.where(num.isna()), errors="coerce", utc=True)
        if num.notna().any():
            ep = pd.to_datetime(num.dropna(), unit="ms", errors="coerce", utc=True)
            out = out.fillna(ep.reindex(df.index))
        df["commence_time"] = out
    return df.sort_values(["game", "book"]).reset_index(drop=True)


# ───────────────────────── ESPN (DraftKings only) ─────────────────────────

ESPN_SCOREBOARD = ("https://site.api.espn.com/apis/site/v2/sports/football/nfl"
                   "/scoreboard?seasontype={st}&week={wk}&dates={season}")


def fetch_espn(season: int, week: int, seasontype: int = 2) -> pd.DataFrame:
    """DraftKings lines + the ESPN event id that nflverse already stores.

    NOTE: ESPN labels the pregame number "close" -- it is the CURRENT line,
    and ESPN deletes odds entirely once a game reaches STATUS_FINAL.
    """
    d = _get(ESPN_SCOREBOARD.format(st=seasontype, wk=week, season=season), ua=False)
    rows = []
    for e in d.get("events", []):
        c = e["competitions"][0]
        tm = {x["homeAway"]: x["team"]["abbreviation"] for x in c["competitors"]}
        home = ESPN_TEAM_FIX.get(tm.get("home"), tm.get("home"))
        away = ESPN_TEAM_FIX.get(tm.get("away"), tm.get("away"))
        for o in c.get("odds", []):
            if o.get("provider", {}).get("id") != "100":   # 200 = live in-game
                continue
            ps, ml = o.get("pointSpread") or {}, o.get("moneyline") or {}
            hcl = ((ps.get("home") or {}).get("close") or {})
            acl = ((ps.get("away") or {}).get("close") or {})
            line = _num(hcl.get("line"))
            spread = -line if line is not None else (
                -float(o["spread"]) if o.get("spread") is not None else None)
            rows.append([f"{away}@{home}", e["date"], "draftkings", spread,
                         _num(hcl.get("odds")), _num(acl.get("odds")),
                         _num(((ml.get("home") or {}).get("close") or {}).get("odds")),
                         _num(((ml.get("away") or {}).get("close") or {}).get("odds")),
                         home, away, int(e["id"]), "espn"])
    return _frame(rows)


def _num(v):
    try:
        return None if v is None else float(str(v).replace("+", ""))
    except (TypeError, ValueError):
        return None


# ─────────────────────── Action Network (multi-book) ───────────────────────

AN_URL = ("https://api.actionnetwork.com/web/v2/scoreboard/nfl"
          "?period=game&seasonType={st}&week={wk}&bookIds={books}")


def fetch_action_network(week: int, seasontype: str = "reg",
                         books: Iterable[int] = tuple(AN_BOOKS)) -> pd.DataFrame:
    """6 real books + consensus + open. Requires a User-Agent header."""
    url = AN_URL.format(st=seasontype, wk=week,
                        books=",".join(str(b) for b in books))
    d = _get(url)
    rows = []
    for e in d.get("games", []):
        tm = {t["id"]: AN_TEAM_FIX.get(t["abbr"], t["abbr"]) for t in e["teams"]}
        home, away = tm.get(e["home_team_id"]), tm.get(e["away_team_id"])
        for bid, mk in (e.get("markets") or {}).items():
            name = AN_BOOKS.get(int(bid), f"book_{bid}")
            ev = (mk or {}).get("event") or {}
            sp = {o["side"]: o for o in ev.get("spread", []) if not o.get("is_live")}
            ml = {o["side"]: o for o in ev.get("moneyline", []) if not o.get("is_live")}
            if "home" not in sp and "home" not in ml:
                continue
            spread = -float(sp["home"]["value"]) if "home" in sp else None
            rows.append([f"{away}@{home}", e["start_time"], name, spread,
                         _num(sp.get("home", {}).get("odds")),
                         _num(sp.get("away", {}).get("odds")),
                         _num(ml.get("home", {}).get("odds")),
                         _num(ml.get("away", {}).get("odds")),
                         home, away, None, "action_network"])
    return _frame(rows)


# ───────────────────────────── Bovada ─────────────────────────────

BOVADA_URL = ("https://www.bovada.lv/services/sports/event/coupon/events/A/"
              "description/football/nfl?marketFilterId=def&preMatchOnly=true&lang=en")

BOVADA_NAME_FIX = {"Washington Commanders": "WAS", "Los Angeles Rams": "LA"}


def fetch_bovada(name_to_abbr: dict) -> pd.DataFrame:
    d = _get(BOVADA_URL)
    rows = []
    for grp in d:
        for e in grp.get("events", []):
            comp = e.get("competitors", [])
            home = next((c["name"] for c in comp if c.get("home")), None)
            away = next((c["name"] for c in comp if not c.get("home")), None)
            h = name_to_abbr.get(home); a = name_to_abbr.get(away)
            if not h or not a:
                continue
            spread = sph = spa = mlh = mla = None
            for dg in e.get("displayGroups", []):
                for m in dg.get("markets", []):
                    if m.get("period", {}).get("description") != "Game":
                        continue
                    desc = m.get("description")
                    for o in m.get("outcomes", []):
                        is_home = o.get("description") == home
                        pr = o.get("price", {})
                        if desc == "Point Spread" and is_home:
                            spread = -float(pr["handicap"]); sph = _am(pr.get("american"))
                        elif desc == "Point Spread":
                            spa = _am(pr.get("american"))
                        elif desc == "Moneyline":
                            if is_home: mlh = _am(pr.get("american"))
                            else: mla = _am(pr.get("american"))
            rows.append([f"{a}@{h}", e.get("startTime"), "bovada", spread,
                         sph, spa, mlh, mla, h, a, None, "bovada"])
    return _frame(rows)


def _am(v):
    if v in (None, "EVEN", ""):
        return 100.0 if v == "EVEN" else None
    try:
        return float(str(v).replace("+", ""))
    except ValueError:
        return None


# ─────────────────────── line shopping ───────────────────────

BOOK_PRIORITY = ["action_network", "espn", "bovada"]


def dedupe(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (game, book). ESPN duplicates Action Network's DraftKings."""
    d = df.copy()
    d["_p"] = d.source.map({s: i for i, s in enumerate(BOOK_PRIORITY)}).fillna(99)
    return (d.sort_values(["game", "book", "_p"])
             .drop_duplicates(subset=["game", "book"], keep="first")
             .drop(columns="_p").reset_index(drop=True))


def consensus_line(df: pd.DataFrame) -> pd.Series:
    """Median spread across real books -- the robust reference number.

    Use THIS, not any single book, as the market number the model is
    measured against. It is the only quantity here that is resistant to a
    single stale or mis-signed feed entry.
    """
    real = df[~df.book.isin(["consensus", "open"])].dropna(subset=["spread"])
    return real.groupby("game").spread.median()


def best_lines(df: pd.DataFrame, max_dev: float = 1.0,
               real_books_only: bool = True) -> pd.DataFrame:
    """Best available number per side, across books, with an outlier guard.

    max_dev: discard any book whose spread sits more than this many points
    from the slate median for that game. Measured on a live 2026 wk1 slate,
    7% of book-game rows deviate >=1pt and the worst was 3.0pts (BetMGM,
    GB@MIN, apparently sign-inverted in the Action Network feed). Ungurarded
    max/min shopping selects exactly those rows and manufactures edge.
    Set max_dev=None to disable (not recommended).
    """
    d = dedupe(df)
    if real_books_only:
        d = d[~d.book.isin(["consensus", "open"])]
    med = consensus_line(df)
    out = []
    for game, g in d.groupby("game"):
        m = med.get(game)
        gs = g.dropna(subset=["spread"])
        n_all = len(gs)
        if max_dev is not None and m is not None and len(gs):
            gs = gs[(gs.spread - m).abs() <= max_dev]
        row = {"game": game, "consensus_spread": m,
               "n_books": n_all, "n_books_used": len(gs),
               "n_rejected": n_all - len(gs)}
        if len(gs):
            ih, ia = gs.spread.idxmin(), gs.spread.idxmax()
            row.update(best_home_spread=gs.loc[ih, "spread"],
                       best_home_spread_book=gs.loc[ih, "book"],
                       best_home_spread_odds=gs.loc[ih, "spread_odds"],
                       best_away_spread=gs.loc[ia, "spread"],
                       best_away_spread_book=gs.loc[ia, "book"],
                       best_away_spread_odds=gs.loc[ia, "away_spread_odds"])
        for side in ("home_ml", "away_ml"):
            s = g.dropna(subset=[side])
            if len(s):
                i = s[side].idxmax()
                row[f"best_{side}"] = s.loc[i, side]
                row[f"best_{side}_book"] = s.loc[i, "book"]
        out.append(row)
    return pd.DataFrame(out).sort_values("game").reset_index(drop=True)


def live_odds(season: int, week: int, seasontype: int = 2,
              name_to_abbr: dict | None = None) -> pd.DataFrame:
    """All sources, one frame. Failures in any single source are non-fatal."""
    frames = []
    for fn in (lambda: fetch_action_network(week, "reg" if seasontype == 2 else "pre"),
               lambda: fetch_espn(season, week, seasontype),
               lambda: fetch_bovada(name_to_abbr or {})):
        try:
            f = fn()
            if len(f):
                frames.append(f)
        except (urllib.error.URLError, urllib.error.HTTPError, ValueError, KeyError) as ex:
            print(f"  [odds] source failed: {type(ex).__name__}: {ex}")
    if not frames:
        return _frame([])
    return pd.concat(frames, ignore_index=True).sort_values(["game", "book"]).reset_index(drop=True)
