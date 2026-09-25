"""
espn.py — live rosters and injury designations, straight from ESPN.

Why a second source when nflverse already publishes rosters and injury
reports: latency. nflverse republishes once a day, and the official injury
report only exists Wednesday through Friday. ESPN's feeds move within minutes
of a transaction, so a Tuesday run sees a player who was placed on IR Monday
night. Nothing here reaches the ratings -- the model has exactly one
player-level term, the quarterback, and that resolves through depth.py. This
is reporting: it tells the human who is actually on the field so he can
overrule a projection, which is worth more than a coefficient nobody
validated.

Access quirks, measured rather than assumed (2026-09-09):

  site.web.api.espn.com   200 with a browser User-Agent.
  site.api.espn.com       403 with a browser User-Agent, 200 with urllib's
                          default one. Backwards from every other API, so
                          _get_json tries both before giving up.

Two feeds:

  /teams/{id}/roster   one call per team, ~350KB. Every player under contract,
                       grouped offense / defense / specialTeam /
                       injuredReserveOrOut / suspended / practiceSquad.
  /injuries            one call, ~9MB, the 25 most recent designations per
                       team. 'Active' entries are the news that a player
                       RETURNED -- they are not injuries, and this module
                       keeps them so teamstats can decide what to do.

Both are cached under data/cache/ for six hours, the same TTL as the rest of
the season's data. A failure never raises: the weekly slate must not depend
on a third-party feed being up on a Sunday morning, so a bad response
degrades to an empty frame plus one printed WARNING.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd

from .data import TEAM_ALIASES, _cache_path, _is_stale

# ESPN's internal team ids, keyed by the nflverse abbreviation this repo uses
# everywhere else. ESPN's own abbreviations differ for two clubs (LAR, WSH).
ESPN_TEAM_IDS: dict[str, int] = {
    "ARI": 22, "ATL": 1, "BAL": 33, "BUF": 2, "CAR": 29, "CHI": 3,
    "CIN": 4, "CLE": 5, "DAL": 6, "DEN": 7, "DET": 8, "GB": 9,
    "HOU": 34, "IND": 11, "JAX": 30, "KC": 12, "LAC": 24, "LA": 14,
    "LV": 13, "MIA": 15, "MIN": 16, "NE": 17, "NO": 18, "NYG": 19,
    "NYJ": 20, "PHI": 21, "PIT": 23, "SEA": 26, "SF": 25, "TB": 27,
    "TEN": 10, "WAS": 28,
}
_TEAM_BY_ESPN_ID: dict[int, str] = {v: k for k, v in ESPN_TEAM_IDS.items()}

# data.TEAM_ALIASES already folds LAR into LA; ESPN also spells Washington
# WSH, which nothing else in the repo has ever needed.
_ESPN_ALIASES: dict[str, str] = {**TEAM_ALIASES, "WSH": "WAS"}

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# (host, send the browser User-Agent). Order matters -- see the module doc.
_HOSTS: list[tuple[str, bool]] = [
    ("https://site.web.api.espn.com", True),
    ("https://site.api.espn.com", False),
]

ROSTER_PATH = "/apis/site/v2/sports/football/nfl/teams/{espn_id}/roster"
INJURIES_PATH = "/apis/site/v2/sports/football/nfl/injuries"

TIMEOUT_SECONDS = 30
CACHE_TTL_HOURS = 6.0
ROSTER_WORKERS = 8

ROSTER_COLUMNS = [
    "team", "espn_id", "player", "position", "group", "jersey", "age",
    "years_exp", "status", "injury_status", "injury_date", "college",
    "fetched_utc",
]
INJURY_COLUMNS = [
    "team", "player", "position", "status", "injury", "location", "detail",
    "return_date", "updated", "short_comment", "long_comment",
    "espn_athlete_id", "fetched_utc",
]

_ATHLETE_ID_RE = re.compile(r"/id/(\d+)")


# ─────────────────────────────────────────────
# HTTP
# ─────────────────────────────────────────────

def _get_json(path: str) -> Any:
    """
    Fetch one ESPN path, trying each host in turn.

    The two hosts want opposite User-Agent behaviour, so the header is set per
    host rather than globally. Raises only when every host has failed, with
    all of the errors in the message so a 403 is distinguishable from a DNS
    outage.
    """
    errors: list[str] = []
    for host, send_ua in _HOSTS:
        req = urllib.request.Request(host + path)
        if send_ua:
            req.add_header("User-Agent", _UA)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
                return json.load(resp)
        except Exception as exc:                       # noqa: BLE001
            errors.append(f"{host}: {exc}")
    raise RuntimeError(f"ESPN {path} failed on every host — " + "; ".join(errors))


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _team_from(espn_team_id: Any, abbreviation: Optional[str]) -> Optional[str]:
    """nflverse abbreviation from whatever ESPN gave us, id preferred."""
    try:
        team = _TEAM_BY_ESPN_ID.get(int(espn_team_id))
    except (TypeError, ValueError):
        team = None
    if team is None and abbreviation:
        abbreviation = str(abbreviation).upper()
        team = _ESPN_ALIASES.get(abbreviation, abbreviation)
    return team


def _read_cache(path, columns: list[str]) -> Optional[pd.DataFrame]:
    """A cached frame if it is fresh and readable, else None."""
    if _is_stale(path, CACHE_TTL_HOURS):
        return None
    try:
        df = pd.read_parquet(path)
    except Exception:                                  # noqa: BLE001
        return None
    return df.reindex(columns=columns)


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})


# ─────────────────────────────────────────────
# ROSTERS
# ─────────────────────────────────────────────

def _latest_injury(item: dict) -> dict:
    """
    The most recent designation on a roster entry, or {}.

    ESPN's status.name is 'Day-To-Day' for every player in the
    injuredReserveOrOut group -- the actual IR / Out designation lives only
    in this list, so it is carried alongside the status rather than dropped.
    """
    injuries = item.get("injuries") or []
    if not injuries:
        return {}
    return max(injuries, key=lambda d: str(d.get("date") or ""))


def _roster_rows(team: str, payload: dict, fetched_utc: str) -> list[dict]:
    rows = []
    for group in payload.get("athletes") or []:
        group_name = group.get("position")
        for item in group.get("items") or []:
            latest = _latest_injury(item)
            rows.append({
                "team": team,
                "espn_id": str(item.get("id")) if item.get("id") is not None else None,
                "player": item.get("fullName") or item.get("displayName"),
                "position": (item.get("position") or {}).get("abbreviation"),
                "group": group_name,
                "jersey": str(item["jersey"]) if item.get("jersey") not in (None, "") else None,
                "age": item.get("age"),
                "years_exp": (item.get("experience") or {}).get("years"),
                "status": (item.get("status") or {}).get("name"),
                "injury_status": latest.get("status"),
                "injury_date": latest.get("date"),
                "college": (item.get("college") or {}).get("name"),
                "fetched_utc": fetched_utc,
            })
    return rows


def _fetch_team_roster(team: str, espn_id: int, fetched_utc: str) -> list[dict]:
    payload = _get_json(ROSTER_PATH.format(espn_id=espn_id))
    return _roster_rows(team, payload, fetched_utc)


def fetch_rosters(refresh: bool = False) -> pd.DataFrame:
    """
    Every player under contract with every team, one row each.

    Columns: team, espn_id, player, position, group, jersey, age, years_exp,
    status, injury_status, injury_date, college, fetched_utc.

    Thirty-two calls in an 8-thread pool; ~1.5 seconds cold. A single team
    failing is skipped with a WARNING and the other thirty-one are returned,
    because a partial roster beats no roster. The cache is written only when
    all 32 came back, so a transient one-team failure is retried next run
    instead of being frozen for six hours. If nothing came back at all the
    frame is empty with the right columns -- never an exception.
    """
    path = _cache_path("espn_rosters.parquet")
    if not refresh:
        cached = _read_cache(path, ROSTER_COLUMNS)
        if cached is not None:
            return cached

    fetched_utc = _now_utc()
    rows: list[dict] = []
    failed: list[str] = []

    with ThreadPoolExecutor(max_workers=ROSTER_WORKERS) as pool:
        futures = {
            pool.submit(_fetch_team_roster, team, espn_id, fetched_utc): team
            for team, espn_id in ESPN_TEAM_IDS.items()
        }
        for fut in as_completed(futures):
            team = futures[fut]
            try:
                rows.extend(fut.result())
            except Exception:                          # noqa: BLE001
                failed.append(team)

    if failed:
        print(f'WARNING: ESPN roster unavailable for {", ".join(sorted(failed))} '
              f'— falling back to nflverse for those teams')

    if not rows:
        return _empty(ROSTER_COLUMNS)

    df = pd.DataFrame(rows, columns=ROSTER_COLUMNS)
    df["age"] = pd.to_numeric(df["age"], errors="coerce").astype("Int64")
    df["years_exp"] = pd.to_numeric(df["years_exp"], errors="coerce").astype("Int64")
    df = df.sort_values(["team", "group", "position", "player"]).reset_index(drop=True)

    if not failed:
        try:
            df.to_parquet(path, index=False)
        except Exception:                              # noqa: BLE001
            pass
    return df


# ─────────────────────────────────────────────
# INJURIES
# ─────────────────────────────────────────────

def _athlete_id(athlete: dict) -> Optional[str]:
    """
    ESPN's athlete id, if this feed exposes it anywhere.

    The injuries feed omits the id field on the athlete object; the player
    card links still embed it (".../player/_/id/4040715/..."), so it is
    scraped from there when present.
    """
    if athlete.get("id") is not None:
        return str(athlete["id"])
    for link in athlete.get("links") or []:
        m = _ATHLETE_ID_RE.search(str(link.get("href") or ""))
        if m:
            return m.group(1)
    return None


def _injury_rows(payload: dict, fetched_utc: str) -> list[dict]:
    rows = []
    for team_block in payload.get("injuries") or []:
        team_id = team_block.get("id")
        for entry in team_block.get("injuries") or []:
            athlete = entry.get("athlete") or {}
            details = entry.get("details") or {}
            team = _team_from(team_id, (athlete.get("team") or {}).get("abbreviation"))
            rows.append({
                "team": team,
                "player": athlete.get("displayName"),
                "position": (athlete.get("position") or {}).get("abbreviation"),
                "status": entry.get("status"),
                "injury": details.get("type"),
                "location": details.get("location"),
                "detail": details.get("detail"),
                "return_date": details.get("returnDate"),
                "updated": entry.get("date"),
                "short_comment": entry.get("shortComment"),
                "long_comment": entry.get("longComment"),
                "espn_athlete_id": _athlete_id(athlete),
                "fetched_utc": fetched_utc,
            })
    return rows


def fetch_injuries(refresh: bool = False) -> pd.DataFrame:
    """
    ESPN's injury feed, every entry, one row each.

    Columns: team, player, position, status, injury, location, detail,
    return_date, updated, short_comment, long_comment, espn_athlete_id,
    fetched_utc.

    Deliberately unfiltered. The feed is the 25 most recent designations per
    team and about half of them are 'Active' -- news that a player came
    back. Deciding what counts as an injury, and which of a player's several
    entries is current, is teamstats' job; this just keeps the record.
    Never raises: a bad response is one WARNING and an empty frame.
    """
    path = _cache_path("espn_injuries.parquet")
    if not refresh:
        cached = _read_cache(path, INJURY_COLUMNS)
        if cached is not None:
            return cached

    fetched_utc = _now_utc()
    try:
        payload = _get_json(INJURIES_PATH)
        rows = _injury_rows(payload, fetched_utc)
    except Exception as exc:                           # noqa: BLE001
        print(f'WARNING: ESPN injury feed unavailable ({exc}) '
              f'— injury report will come from nflverse only')
        return _empty(INJURY_COLUMNS)

    if not rows:
        print('WARNING: ESPN injury feed returned no entries')
        return _empty(INJURY_COLUMNS)

    df = (pd.DataFrame(rows, columns=INJURY_COLUMNS)
            .sort_values(["team", "updated", "player"])
            .reset_index(drop=True))
    try:
        df.to_parquet(path, index=False)
    except Exception:                                  # noqa: BLE001
        pass
    return df
