"""
Closing lines: the last pregame number for every game, recorded by the
Wednesday run (review_week.py) so every bet -- the model's and his -- is
scored on closing line value (CLV).

CLV is the fastest honest test of an edge. Getting a better number than the
close, consistently, is beating the market, and it shows in weeks; wins and
losses take seasons to separate from luck.

Source, per game, first that has the game:
  1. FanDuel via Action Network (config.MY_BOOK, the book he bets): the last
     pregame number Action Network stored. Still served days after the game.
  2. DraftKings via Action Network, when FanDuel has no row for the game.
  3. nflverse spread_line / moneylines (the DraftKings close, frozen at kickoff).
Checked 2026-10-07 on 2026 weeks 1-4: Action Network's DraftKings spread
equals nflverse's DraftKings close on 54 of 63 games; the rest differ by
0.5-1 pt, most likely nflverse's last snapshot being earlier. FanDuel was
present for 62 of 64 games.

Action Network's scoreboard takes a week but no season, so it only serves the
current season; older seasons fall back to nflverse.

Files: picks/{season}/weekNN_closing.csv (tracked, written once per week).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from .archive import ARCHIVE_DIR
from .betlog import clv_for_row
from .config import CURRENT_SEASON, MY_BOOK

CLOSE_COLS = ["game_id", "away_team", "home_team", "close_spread",
              "close_home_spread_odds", "close_away_spread_odds",
              "close_home_ml", "close_away_ml", "close_source", "captured_utc"]


def closing_path(season: int, week: int, archive_dir=None) -> Path:
    return Path(archive_dir or ARCHIVE_DIR) / str(season) / f"week{week:02d}_closing.csv"


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(f) else f


def fetch_closing(season: int, week: int, games: pd.DataFrame,
                  book: Optional[str] = MY_BOOK, fetch=None) -> pd.DataFrame:
    """Closing numbers for every PLAYED game of the week, one row per game."""
    wk = games[(games.season == season) & (games.week == week)
               & games.played.fillna(False).astype(bool)]
    an = pd.DataFrame()
    if season == CURRENT_SEASON:
        try:
            if fetch is None:
                from .odds import fetch_action_network as fetch
            an = fetch(week)
        except Exception as e:                       # noqa: BLE001
            print(f"WARNING: Action Network closing lines unavailable ({e}); "
                  f"using nflverse (DraftKings) closes")
    rows = []
    for _, g in wk.iterrows():
        key = f"{g.away_team}@{g.home_team}"
        hit = None
        for b in (book or "fanduel", "draftkings"):
            if b == "draftkings" and hit is not None:
                break
            cand = an[(an["game"] == key) & (an["book"] == b)] if len(an) else an
            if len(cand) and _num(cand.iloc[0]["spread"]) is not None:
                # Same week number, different season: the start time says so.
                ct = pd.to_datetime(cand.iloc[0]["commence_time"], utc=True, errors="coerce")
                gd = pd.to_datetime(g.gameday, errors="coerce")
                if pd.notna(ct) and pd.notna(gd) and abs((ct.tz_convert(None).normalize() - gd).days) > 2:
                    continue
                hit = (cand.iloc[0], f"{b} (action network)")
                break
        if hit is not None:
            r, src = hit
            rows.append(dict(game_id=g.game_id, away_team=g.away_team, home_team=g.home_team,
                             close_spread=_num(r["spread"]),
                             close_home_spread_odds=_num(r["spread_odds"]),
                             close_away_spread_odds=_num(r["away_spread_odds"]),
                             close_home_ml=_num(r["home_ml"]), close_away_ml=_num(r["away_ml"]),
                             close_source=src))
        else:
            rows.append(dict(game_id=g.game_id, away_team=g.away_team, home_team=g.home_team,
                             close_spread=_num(g.spread_line),
                             close_home_spread_odds=_num(g.get("home_spread_odds")),
                             close_away_spread_odds=_num(g.get("away_spread_odds")),
                             close_home_ml=_num(g.get("home_moneyline")),
                             close_away_ml=_num(g.get("away_moneyline")),
                             close_source="draftkings (nflverse)"))
    out = pd.DataFrame(rows, columns=CLOSE_COLS[:-1])
    out["captured_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return out[CLOSE_COLS]


def record_closing(season: int, week: int, games: pd.DataFrame,
                   archive_dir=None, fetch=None) -> Optional[pd.DataFrame]:
    """
    Write the week's closing lines once, when every game is final, and
    return them. An existing file is never rewritten: a close is a fact
    about kickoff, and a later fetch can only be worse.
    """
    path = closing_path(season, week, archive_dir)
    if path.exists():
        return pd.read_csv(path)
    wk = games[(games.season == season) & (games.week == week)]
    if wk.empty or not wk.played.fillna(False).astype(bool).all():
        return None
    df = fetch_closing(season, week, games, fetch=fetch)
    if df.empty:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return df


def load_closing(season: int, week: int, archive_dir=None) -> Optional[pd.DataFrame]:
    path = closing_path(season, week, archive_dir)
    return pd.read_csv(path) if path.exists() else None


def close_for(closing: Optional[pd.DataFrame], home: str, away: str):
    """The closing row for one game, or None."""
    if closing is None or closing.empty:
        return None
    hit = closing[(closing.home_team == home) & (closing.away_team == away)]
    return None if hit.empty else hit.iloc[0]


def side_close(close_row, market: str, side_team: str):
    """The closing number from the bettor's side: ticket points for a spread,
    American odds for a moneyline. None if not recorded."""
    if close_row is None:
        return None
    is_home = side_team == close_row["home_team"]
    if str(market).upper() == "SPREAD":
        cs = _num(close_row["close_spread"])
        return None if cs is None else (-cs if is_home else cs)
    return _num(close_row["close_home_ml"] if is_home else close_row["close_away_ml"])


def ticket(bet_side: str) -> Optional[float]:
    """'TB +3.0' -> 3.0, 'MIN -1.5' -> -1.5, 'KC PK' -> 0.0."""
    parts = str(bet_side).split()
    if len(parts) < 2:
        return None
    if parts[1].upper() in ("PK", "PICK", "EVEN"):
        return 0.0
    return _num(parts[1])


def bet_clv(market: str, side_team: str, taken_line, taken_odds, close_row,
            pts_table=None) -> tuple:
    """(close, clv_pts, clv_prob) for one bet, same arithmetic as the tracker."""
    market = str(market).upper()
    close = side_close(close_row, market, side_team)
    if close is None:
        return (None, None, None)
    if market == "SPREAD":
        pts, prob = clv_for_row({"market": "SPREAD", "line_taken": taken_line,
                                 "closing_line": close}, pts_table)
    else:
        pts, prob = clv_for_row({"market": "MONEYLINE", "odds": taken_odds,
                                 "closing_odds": close}, pts_table)
    return (close, pts, prob)


def model_card(season: int, week: int, archive_dir=None) -> Optional[pd.DataFrame]:
    """
    The model's bets for the week AS FIRST PUBLISHED (weekNN_first_leans.csv),
    falling back to the final card for weeks before first-published numbers
    were kept (2026 weeks 1-4). CLV is measured from where a bet first went on
    the card; a Sunday re-run prices near the close and would hide it.
    """
    d = Path(archive_dir or ARCHIVE_DIR) / str(season)
    for name in (f"week{week:02d}_first_leans.csv", f"week{week:02d}_leans.csv"):
        p = d / name
        if p.exists():
            df = pd.read_csv(p)
            return df.assign(card_source="first published" if "first" in name else "final card")
    return None


def card_clv(season: int, week: int, archive_dir=None, pts_table=None) -> pd.DataFrame:
    """One row per model bet in the week with its CLV; empty if no closes yet."""
    card = model_card(season, week, archive_dir)
    closing = load_closing(season, week, archive_dir)
    if card is None or closing is None or card.empty:
        return pd.DataFrame()
    rows = []
    for _, l in card.iterrows():
        side = str(l.get("bet_side") or "")
        if not side:
            continue
        market = str(l.get("bet_market") or "").upper()
        row = close_for(closing, l["home_team"], l["away_team"])
        close, pts, prob = bet_clv(market, side.split()[0], ticket(side),
                                   _num(l.get("bet_odds")), row, pts_table)
        rows.append(dict(season=season, week=week, bet_side=side, market=market,
                         taken=ticket(side) if market == "SPREAD" else _num(l.get("bet_odds")),
                         close=close, clv_pts=pts, clv_prob=prob,
                         source=None if row is None else row["close_source"],
                         card_source=l["card_source"]))
    return pd.DataFrame(rows)


def summarize_clv(df: pd.DataFrame) -> dict:
    """n, average CLV and how often the close was beaten, spreads and moneylines apart."""
    out = {}
    if df is None or df.empty:
        return {"spread": {"n": 0}, "moneyline": {"n": 0}}
    for market, col in (("SPREAD", "clv_pts"), ("MONEYLINE", "clv_prob")):
        part = df[(df.market == market) & df[col].notna()]
        v = part[col].astype(float)
        out[market.lower()] = {"n": int(len(v)),
                               "avg": float(v.mean()) if len(v) else None,
                               "beat": int((v > 0).sum()), "same": int((v == 0).sum()),
                               "worse": int((v < 0).sum())}
    return out
