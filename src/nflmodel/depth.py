"""
depth.py — who is actually starting at quarterback this week.

The ratings fit learns a quarterback's value from games he has PLAYED. For an
upcoming slate nflverse leaves the starter columns null, so the model has to be
told who is under center, and that answer is worth up to ~6 points of margin --
more than home field.

Until now the answer came from `ratings.projected_starters`, which carries the
previous starter forward. That is right mid-season and badly wrong in Week 1:
it cannot see a single offseason move. Checked against the live 2026 Week 1
depth charts it was wrong for 8 of 32 teams.

This module reads the real thing. nflverse republishes ESPN's depth charts
daily and stamps each pull with `dt`, so the file is a series of snapshots and
the newest one is today's board. Weekly rosters give each player's roster
status, which is what catches a depth chart that has gone stale behind an
injury.

No part of this touches the backtest. Historical fits use the quarterback who
actually took the snaps, which is recorded in the game file; depth charts are
consulted only for games that have not been played, where they leak nothing.
"""

from __future__ import annotations

import pandas as pd

from .config import CACHE_DIR, CURRENT_SEASON
from .data import _cache_path, _is_stale, _normalize_team, qb_identity_map

DEPTH_CHART_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "depth_charts/depth_charts_{season}.parquet"
)
ROSTER_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "weekly_rosters/roster_weekly_{season}.parquet"
)

# Roster statuses that mean a player cannot start on Sunday. A depth chart is
# published daily but can still lag a same-day injury designation; the roster
# file is the cross-check.
INACTIVE_STATUS = {"RES", "CUT", "IR", "PUP", "NON", "SUS", "EXE", "RET"}

# Where a resolved starter came from, worst to best. Printed each run so a
# wrong quarterback is visible rather than silent.
SOURCE_DEPTH_CHART = "depth chart"
SOURCE_CARRY_FORWARD = "carry-forward"
SOURCE_SLATE = "game file"
SOURCE_OVERRIDE = "override"


def _load_cached(url: str, filename: str, refresh: bool, season: int) -> pd.DataFrame:
    """Fetch a season-scoped nflverse parquet, cached like everything else."""
    path = _cache_path(filename)
    ttl = 6.0 if season >= CURRENT_SEASON else float("inf")
    if refresh or _is_stale(path, ttl):
        df = pd.read_parquet(url.format(season=season))
        df.to_parquet(path, index=False)
    else:
        df = pd.read_parquet(path)
    return df


def load_depth_charts(season: int, refresh: bool = False) -> pd.DataFrame:
    df = _load_cached(DEPTH_CHART_URL, f"depth_charts_{season}.parquet", refresh, season)
    df = df.copy()
    df["team"] = _normalize_team(df["team"])
    return df


def load_weekly_rosters(season: int, refresh: bool = False) -> pd.DataFrame:
    df = _load_cached(ROSTER_URL, f"roster_weekly_{season}.parquet", refresh, season)
    df = df.copy()
    df["team"] = _normalize_team(df["team"])
    return df


def depth_chart_starters(
    season: int,
    week: int,
    refresh: bool = False,
    exclude_unavailable: bool = True,
    asof=None,
) -> tuple[dict[str, str], str | None, list[tuple[str, str]]]:
    """
    Each team's highest available quarterback from the most recent depth chart.

    "Available" is the point of the exclusion. A depth chart still lists a
    quarterback who went on injured reserve on Tuesday, and taking QB1 blindly
    projects a team with a starter who cannot dress. So this walks DOWN the
    chart -- QB1, then QB2, then QB3 -- until it finds one who is neither on
    an unavailable roster status nor listed Out or Doubtful for the week.

    Teams missing from the newest snapshot fall back to their own most recent
    one, so a partial publish degrades one team instead of the slate.

    Returns (team -> gsis_id, snapshot timestamp, promotions), where a
    promotion is a (team, reason) pair for a team whose listed starter was
    skipped. Those are printed, never silent.
    """
    try:
        dc = load_depth_charts(season, refresh=refresh)
    except Exception:
        return {}, None, []

    qbs = dc[dc["pos_abb"] == "QB"].dropna(subset=["gsis_id"]).copy()
    if qbs.empty:
        return {}, None, []

    # The file holds every daily snapshot of the season, so "most recent"
    # means January when replaying Week 5 -- which would hand the model the
    # starting quarterbacks for games it is about to predict. Only snapshots
    # published before kickoff are admissible.
    if asof is not None:
        cutoff = pd.Timestamp(asof)
        if cutoff.tzinfo is None:
            cutoff = cutoff.tz_localize("UTC")
        stamps = pd.to_datetime(qbs["dt"], utc=True, errors="coerce")
        qbs = qbs[stamps < cutoff]
        if qbs.empty:
            return {}, None, []

    snapshot = str(qbs["dt"].max())

    # Newest snapshot per team, keeping every rank so we can walk down it.
    newest_dt = qbs.groupby("team")["dt"].transform("max")
    qbs = qbs[qbs["dt"] == newest_dt]

    blocked: set[str] = set()
    if exclude_unavailable:
        from .roster import unavailable_ids
        try:
            blocked = unavailable_ids(season, week, refresh=refresh)
        except Exception:
            blocked = set()

    starters: dict[str, str] = {}
    promotions: list[tuple[str, str]] = []

    for team, grp in qbs.sort_values("pos_rank").groupby("team"):
        listed = grp.iloc[0]
        available = grp[~grp["gsis_id"].isin(blocked)]
        if available.empty:
            # Everyone on the chart is unavailable. Keep QB1 rather than
            # inventing a starter, and let the human see it.
            starters[team] = listed["gsis_id"]
            promotions.append((team, "every listed QB is unavailable"))
            continue
        chosen = available.iloc[0]
        starters[team] = chosen["gsis_id"]
        if chosen["gsis_id"] != listed["gsis_id"]:
            promotions.append(
                (team, f'{listed["player_name"]} unavailable — '
                       f'promoted {chosen["player_name"]}'))

    return starters, snapshot, promotions


def qb_depth_order(season: int, week: int, refresh: bool = False,
                   asof=None) -> dict[str, list[tuple[str, str]]]:
    """
    Each team's quarterbacks in listed order: [(gsis_id, name), ...].

    Exists so a run can price what an uncertain starter is actually worth.
    "ATL starter is Doubtful" is a warning nobody acts on; "ATL: Penix instead
    of Rush moves this line 1.8 points" is a decision. The largest single
    prediction error of the 2026 season was a quarterback the model had wrong,
    not a rating it had wrong, so knowing WHICH uncertainty matters is worth
    more than another parameter.
    """
    try:
        dc = load_depth_charts(season, refresh=refresh)
    except Exception:
        return {}

    qbs = dc[dc["pos_abb"] == "QB"].dropna(subset=["gsis_id"]).copy()
    if qbs.empty:
        return {}

    if asof is not None:
        cutoff = pd.Timestamp(asof)
        if cutoff.tzinfo is None:
            cutoff = cutoff.tz_localize("UTC")
        stamps = pd.to_datetime(qbs["dt"], utc=True, errors="coerce")
        qbs = qbs[stamps < cutoff]
        if qbs.empty:
            return {}

    newest = qbs.groupby("team")["dt"].transform("max")
    qbs = qbs[qbs["dt"] == newest]

    out: dict[str, list[tuple[str, str]]] = {}
    for team, grp in qbs.sort_values("pos_rank").groupby("team"):
        seen, order = set(), []
        for _, r in grp.iterrows():
            gid = r["gsis_id"]
            if gid in seen:
                continue
            seen.add(gid)
            order.append((gid, r["player_name"]))
        out[team] = order
    return out


def resolve_starters(
    history: pd.DataFrame,
    games: pd.DataFrame,
    season: int,
    week: int,
    slate_names: dict[str, str] | None = None,
    overrides: dict[str, str] | None = None,
    use_depth_chart: bool = True,
    refresh: bool = False,
) -> tuple[dict[str, str], dict[str, str], str | None, list[tuple[str, str, str]]]:
    """
    Best available starting quarterback per team, by name, for an upcoming week.

    Four layers, each beating the one below it:

      1. --qb overrides, because you can see a Sunday-morning report that no
         feed has caught up to.
      2. The published depth chart, which is stamped with the moment it was
         pulled and is refreshed daily.
      3. Whatever the game file already carries for this slate. nflverse now
         pre-fills the starters for the upcoming week -- which the rest of
         this model long assumed it did not -- so this is usually populated
         and usually right.
      4. The carried-forward previous starter, which is the only layer that
         cannot see the offseason and is therefore the last resort.

    Names resolve through the player id, never by string match: the depth
    chart says "Michael Penix Jr." where the game file says "Michael Penix",
    and a string match would hand back replacement level without saying so.

    Returns (team -> qb name, team -> which layer answered, snapshot stamp,
    notes). A note is anything the human should look at before trusting the
    projection: the two sources naming different quarterbacks, or a listed
    starter skipped because he is unavailable. Reported, never silent -- two
    sources splitting is exactly the case where a model should not guess
    quietly.
    """
    from .ratings import projected_starters

    starters = projected_starters(history, season, week)
    source = {t: SOURCE_CARRY_FORWARD for t in starters}

    for team, name in (slate_names or {}).items():
        if isinstance(name, str) and name:
            starters[team] = name
            source[team] = SOURCE_SLATE

    snapshot = None
    notes: list[tuple[str, str]] = []

    if use_depth_chart:
        asof = None
        if games is not None and "gameday" in games.columns:
            wk = games[(games["season"] == season) & (games["week"] == week)]
            if not wk.empty and wk["gameday"].notna().any():
                asof = pd.to_datetime(wk["gameday"]).min()

        by_id, snapshot, promotions = depth_chart_starters(
            season, week, refresh=refresh, asof=asof)
        notes.extend(promotions)
        canon = qb_identity_map(games)
        for team, gsis_id in by_id.items():
            # An id with no NFL history has no rating either and would fall to
            # replacement level -- which for a genuine rookie is correct, but
            # is not a reason to discard a name the game file already has.
            name = canon.get(gsis_id)
            if name is None:
                continue
            prior = (slate_names or {}).get(team)
            if isinstance(prior, str) and prior and prior != name:
                notes.append((team, f'game file says {prior}, depth chart says '
                                    f'{name} — using {name}; override with '
                                    f'--qb {team}="{prior}" if that is wrong'))
            starters[team] = name
            source[team] = SOURCE_DEPTH_CHART

    for team, name in (overrides or {}).items():
        starters[team] = name
        source[team] = SOURCE_OVERRIDE

    return starters, source, snapshot, notes
