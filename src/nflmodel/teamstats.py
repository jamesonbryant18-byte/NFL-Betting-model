"""
teamstats.py — the team-level picture behind each projection.

Records, rosters and injuries, assembled for a human to read next to the
slate. Nothing here feeds the ratings: the model has one player-level term
(the quarterback, resolved in depth.py) and every situational factor it ever
measured came back at zero. What a person CAN do with this is overrule a
projection -- see that a team's left tackle and both starting corners are
out, and decide the lean is not worth logging. That judgment is worth more
than a coefficient nobody validated, so this module optimises for being read.

Two sources for the same facts, because they fail differently:

  ESPN       moves within minutes of a transaction, but it is a third-party
             feed that 403s on a whim (CLAUDE.md gotcha 7) and its injury
             list is capped at the 25 most recent items per team.
  nflverse   republishes daily, keeps the official Wednesday-Friday injury
             report, and is already cached on disk for the season -- so it
             works offline and is the fallback for every team ESPN misses.

The join between them is by NAME, normalised through normalize_name(),
because ESPN's injury feed does not carry a player id. Name joins are the
thing CLAUDE.md warns about for quarterbacks ("Michael Penix Jr." vs
"Michael Penix"), which is exactly why every join here strips suffixes and
punctuation first. This is reporting, so a missed join costs one duplicate
row, not a wrong projection.

Sign convention for ATS records, restated because it has already shipped
inverted once: spread_line is points the HOME team is favored by, and the
home side covers when result > spread_line. The away side's cover test is the
same inequality with both signs flipped, which is how _team_games() folds
both sides into one frame.

Nothing in this module raises for a network problem. team_stats_bundle()
wraps every stage so an outage degrades to an empty frame and a printed
WARNING; the weekly slate must never wait on a roster feed.
"""

from __future__ import annotations

import re
from typing import Any, Optional

import pandas as pd

from . import espn
from .data import TEAMS, _normalize_team

# ─────────────────────────────────────────────
# POSITIONS AND NAMES
# ─────────────────────────────────────────────

POSITION_GROUPS = ["QB", "RB", "WR", "TE", "OL", "DL", "LB", "DB", "ST"]
OTHER_GROUP = "OTHER"

# Every abbreviation either source uses, folded onto the nine groups above.
# ESPN says OT/G/PK, nflverse says T/OL/K, depth charts say LT/RG -- one map.
_POSITION_TO_GROUP: dict[str, str] = {
    "QB": "QB",
    "RB": "RB", "FB": "RB", "HB": "RB",
    "WR": "WR",
    "TE": "TE",
    "OT": "OL", "T": "OL", "G": "OL", "OG": "OL", "C": "OL", "OL": "OL",
    "LT": "OL", "RT": "OL", "LG": "OL", "RG": "OL",
    "DE": "DL", "DT": "DL", "NT": "DL", "DL": "DL", "EDGE": "DL",
    "LB": "LB", "ILB": "LB", "OLB": "LB", "MLB": "LB",
    "CB": "DB", "S": "DB", "SS": "DB", "FS": "DB", "DB": "DB", "SAF": "DB",
    "K": "ST", "PK": "ST", "P": "ST", "LS": "ST", "KR": "ST", "PR": "ST",
}

_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def position_group(pos: Any) -> str:
    """The nine-way position group for an abbreviation; 'OTHER' if unknown."""
    if pos is None or (isinstance(pos, float) and pd.isna(pos)):
        return OTHER_GROUP
    return _POSITION_TO_GROUP.get(str(pos).strip().upper(), OTHER_GROUP)


def normalize_name(name: Any) -> str:
    """
    A player name reduced to what both sources agree on.

    Lower-case, no periods or apostrophes, hyphens as spaces, generational
    suffixes dropped, whitespace collapsed. 'Michael Penix Jr.' and
    'Michael Penix' become the same key; so do "Ja'Marr" and "JaMarr". Used
    for every name join in this module, so the rule lives in one place.
    """
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return ""
    s = str(name).lower()
    s = s.replace(".", "").replace("'", "").replace("’", "")
    s = s.replace("-", " ")
    tokens = s.split()
    while len(tokens) > 1 and tokens[-1] in _NAME_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and pd.isna(value):
        return True
    try:
        if value is pd.NA or value is pd.NaT:
            return True
    except Exception:                                  # noqa: BLE001
        pass
    return str(value).strip() == ""


def _text(value: Any) -> str:
    """A cell as display text: '' for any flavour of missing."""
    return "" if _is_blank(value) else str(value).strip()


# ─────────────────────────────────────────────
# RECORDS
# ─────────────────────────────────────────────

RECORD_COLUMNS = [
    "team", "wins", "losses", "ties", "record", "pf", "pa", "pd",
    "home_record", "away_record", "ats_wins", "ats_losses", "ats_pushes",
    "ats_record", "last_result", "games_played",
]


def _fmt_record(wins: int, losses: int, ties: int = 0) -> str:
    return f"{wins}-{losses}-{ties}" if ties > 0 else f"{wins}-{losses}"


def _team_games(games: pd.DataFrame, season: int, week: int) -> pd.DataFrame:
    """
    Played games of the season before `week`, one row per TEAM-game.

    Each game appears twice, once from each side, with margin and line
    expressed from that side's point of view. Negating both result and
    spread_line for the away side keeps the cover test a single inequality
    (margin > line) for everyone, which is the safest way to carry the
    home-favored sign convention through without a branch to get backwards.
    """
    g = games[(games["season"] == season)
              & (games["week"] < week)
              & games["result"].notna()]
    base = ["week", "gameday"] if "gameday" in g.columns else ["week"]

    home = pd.DataFrame({
        "team": g["home_team"], "opp": g["away_team"],
        "pf": g["home_score"], "pa": g["away_score"],
        "margin": g["result"], "line": g["spread_line"], "is_home": True,
    })
    away = pd.DataFrame({
        "team": g["away_team"], "opp": g["home_team"],
        "pf": g["away_score"], "pa": g["home_score"],
        "margin": -g["result"], "line": -g["spread_line"], "is_home": False,
    })
    for side in (home, away):
        for col in base:
            side[col] = g[col].values

    tg = pd.concat([home, away], ignore_index=True)
    tg["win"] = tg["margin"] > 0
    tg["loss"] = tg["margin"] < 0
    tg["tie"] = tg["margin"] == 0
    has_line = tg["line"].notna()
    tg["ats_win"] = has_line & (tg["margin"] > tg["line"])
    tg["ats_push"] = has_line & (tg["margin"] == tg["line"])
    tg["ats_loss"] = has_line & (tg["margin"] < tg["line"])
    return tg


def _last_result(tg: pd.DataFrame) -> str:
    """'W 27-20 vs DEN' / 'L 17-24 @ KC' from a team's most recent game."""
    if tg.empty:
        return ""
    order = ["week", "gameday"] if "gameday" in tg.columns else ["week"]
    last = tg.sort_values(order).iloc[-1]
    letter = "W" if last["win"] else ("L" if last["loss"] else "T")
    venue = "vs" if last["is_home"] else "@"
    return f'{letter} {int(last["pf"])}-{int(last["pa"])} {venue} {last["opp"]}'


def team_records(games: pd.DataFrame, season: int, week: int) -> pd.DataFrame:
    """
    Straight-up and against-the-spread records entering `week`.

    One row for every team in data.TEAMS, whether or not it has played --
    Week 1 gives 32 rows of 0-0, which is what a summary sheet wants. Only
    played games (result not null) before the given week count, so an
    unplayed game on the schedule is never a loss.

    Columns: team, wins, losses, ties, record, pf, pa, pd, home_record,
    away_record, ats_wins, ats_losses, ats_pushes, ats_record, last_result,
    games_played.
    """
    tg = _team_games(games, season, week)
    rows = []
    for team in TEAMS:
        t = tg[tg["team"] == team]
        h, a = t[t["is_home"]], t[~t["is_home"]]
        w, l, ti = int(t["win"].sum()), int(t["loss"].sum()), int(t["tie"].sum())
        aw, al, ap = int(t["ats_win"].sum()), int(t["ats_loss"].sum()), int(t["ats_push"].sum())
        pf, pa = int(t["pf"].fillna(0).sum()), int(t["pa"].fillna(0).sum())
        rows.append({
            "team": team,
            "wins": w, "losses": l, "ties": ti,
            "record": _fmt_record(w, l, ti),
            "pf": pf, "pa": pa, "pd": pf - pa,
            "home_record": _fmt_record(int(h["win"].sum()), int(h["loss"].sum()),
                                       int(h["tie"].sum())),
            "away_record": _fmt_record(int(a["win"].sum()), int(a["loss"].sum()),
                                       int(a["tie"].sum())),
            "ats_wins": aw, "ats_losses": al, "ats_pushes": ap,
            "ats_record": f"{aw}-{al}-{ap}",
            "last_result": _last_result(t),
            "games_played": int(len(t)),
        })
    return pd.DataFrame(rows, columns=RECORD_COLUMNS)


# ─────────────────────────────────────────────
# ROSTERS
# ─────────────────────────────────────────────

ROSTER_TABLE_COLUMNS = [
    "team", "player", "position", "pos_group", "jersey", "age", "years_exp",
    "status", "injury_status", "source",
]

# nflverse roster codes -> the words ESPN uses, so one status column reads
# the same whichever source filled it. CUT and RET are excluded upstream:
# a released player is not on the team.
NFLVERSE_STATUS = {
    "ACT": "Active",
    "RES": "Reserve/IR",
    "DEV": "Practice Squad",
    "EXE": "Exempt",
    "SUS": "Suspended",
    "PUP": "PUP",
    "NON": "Non-Football Injury",
}
_NFLVERSE_EXCLUDE = {"CUT", "RET"}

_GROUP_ORDER = {g: i for i, g in enumerate(POSITION_GROUPS)}
_GROUP_ORDER[OTHER_GROUP] = len(POSITION_GROUPS)


def _sort_roster(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["_grp"] = df["pos_group"].map(_GROUP_ORDER).fillna(len(POSITION_GROUPS))
    df["_jersey"] = pd.to_numeric(df["jersey"], errors="coerce")
    df["_pos"] = df["position"].map(_text)
    df = (df.sort_values(["team", "_grp", "_pos", "_jersey", "player"],
                         na_position="last")
            .drop(columns=["_grp", "_jersey", "_pos"])
            .reset_index(drop=True))
    return df


# ESPN's status.name is a placeholder for two kinds of player: everyone in
# the injuredReserveOrOut group reads 'Day-To-Day', and a handful of active-
# group players who were just suspended or ruled out read 'News'. Measured on
# the live feed (2026-09-09): 243 of 243 IR-group players were 'Day-To-Day'
# and their real designation -- 193 IR, 50 Out -- lived only in the latest
# injury entry. A status column that says 'Day-To-Day' for an IR player
# cannot be filtered on, which is the whole reason the column exists.
_ESPN_PLACEHOLDER_STATUS = {"day-to-day", "news"}
_DESIGNATION_TO_STATUS = {
    "injured reserve": "Injured Reserve",
    "out": "Out",
    "suspension": "Suspended",
}


def _espn_roster_status(group: Any, status: Any, injury_status: Any) -> Any:
    """The roster status a filter can use, derived where ESPN's is a placeholder."""
    g = _text(group)
    s = _text(status)
    designation = _DESIGNATION_TO_STATUS.get(_text(injury_status).lower())
    if g == "practiceSquad":
        return "Practice Squad"
    if g == "suspended":
        return "Suspended"
    if g == "injuredReserveOrOut":
        return designation or "Injured Reserve"
    if s.lower() in _ESPN_PLACEHOLDER_STATUS and designation:
        return designation
    if s.lower() == "news":
        return "Active"
    return status


def _espn_roster_rows(raw: pd.DataFrame) -> pd.DataFrame:
    status = [
        _espn_roster_status(g, s, i)
        for g, s, i in zip(raw["group"], raw["status"], raw["injury_status"])
    ]
    df = pd.DataFrame({
        "team": raw["team"],
        "player": raw["player"],
        "position": raw["position"],
        "pos_group": raw["position"].map(position_group),
        "jersey": raw["jersey"],
        "age": raw["age"],
        "years_exp": raw["years_exp"],
        "status": pd.Series(status, index=raw.index, dtype="object"),
        "injury_status": raw["injury_status"],
        "source": "espn",
    })
    return df[df["player"].notna()]


def _nflverse_roster_rows(rosters: pd.DataFrame, teams: list[str],
                          week: int) -> pd.DataFrame:
    """
    The nflverse weekly roster for `teams`, as of the latest week <= `week`.

    The file has one row per player per week, so a player's current status
    is his most recent row on or before the requested week. Keyed by gsis_id
    where present and by name otherwise -- undrafted rookies sometimes arrive
    before their id does.
    """
    r = rosters[rosters["team"].isin(teams) & (rosters["week"] <= week)].copy()
    if r.empty:
        return pd.DataFrame(columns=ROSTER_TABLE_COLUMNS)

    r["_key"] = r["gsis_id"].where(r["gsis_id"].notna(),
                                   "name:" + r["full_name"].astype(str))
    r = (r.sort_values("week")
          .drop_duplicates(subset=["team", "_key"], keep="last"))
    r = r[~r["status"].isin(_NFLVERSE_EXCLUDE)]

    position = r["position"]
    if "depth_chart_position" in r.columns:
        position = position.where(position.notna(), r["depth_chart_position"])

    age = pd.Series([None] * len(r), index=r.index, dtype="object")
    if "birth_date" in r.columns:
        born = pd.to_datetime(r["birth_date"], errors="coerce")
        today = pd.Timestamp.now().normalize()
        age = ((today - born).dt.days / 365.25).apply(
            lambda v: int(v) if pd.notna(v) else None)

    jersey = r["jersey_number"].apply(
        lambda v: str(int(v)) if pd.notna(v) else None)

    df = pd.DataFrame({
        "team": r["team"],
        "player": r["full_name"],
        "position": position,
        "pos_group": position.map(position_group),
        "jersey": jersey,
        "age": age,
        "years_exp": r["years_exp"],
        "status": r["status"].map(lambda s: NFLVERSE_STATUS.get(s, s)),
        "injury_status": None,
        "source": "nflverse",
    })
    return df[df["player"].notna()]


def roster_table(season: int, week: int, refresh: bool = False) -> pd.DataFrame:
    """
    Everyone on every team, one row each, from ESPN with nflverse filling in.

    ESPN first because it is current to the minute. Any team ESPN could not
    return -- a 403, a timeout, or the whole feed being down -- is filled from
    the nflverse weekly roster already cached on disk, so the table is always
    complete and the `source` column says which is which.

    Practice squad and injured reserve players are included. They ARE the
    team's roster; the status column lets a sheet filter hide them, whereas
    dropping them here would make a team that just lost its left tackle to IR
    look like it never had one.

    Columns: team, player, position, pos_group, jersey, age, years_exp,
    status, injury_status, source. Sorted by team, position group, position,
    jersey.
    """
    frames = []

    try:
        raw = espn.fetch_rosters(refresh=refresh)
    except Exception as exc:                           # noqa: BLE001
        print(f"WARNING: ESPN rosters failed unexpectedly ({exc}) — using nflverse")
        raw = pd.DataFrame(columns=espn.ROSTER_COLUMNS)
    if not raw.empty:
        frames.append(_espn_roster_rows(raw))

    have = set(raw["team"].dropna().unique()) if not raw.empty else set()
    missing = [t for t in TEAMS if t not in have]
    if missing:
        try:
            from .depth import load_weekly_rosters
            rosters = load_weekly_rosters(season, refresh=refresh)
            frames.append(_nflverse_roster_rows(rosters, missing, week))
        except Exception as exc:                       # noqa: BLE001
            print(f"WARNING: nflverse roster unavailable for {season} ({exc}) "
                  f'— no roster for {", ".join(missing)}')

    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame(columns=ROSTER_TABLE_COLUMNS)

    df = pd.concat(frames, ignore_index=True).reindex(columns=ROSTER_TABLE_COLUMNS)
    for col in ("age", "years_exp"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("Int64")
    return _sort_roster(df)


# ─────────────────────────────────────────────
# INJURIES
# ─────────────────────────────────────────────

INJURY_TABLE_COLUMNS = [
    "team", "player", "position", "status", "injury", "practice_status",
    "expected_return", "updated", "comment", "source",
]

# Designations that mean the player is not playing this week. Questionable
# is deliberately not here -- it resolves to playing more often than not.
OUT_STATUSES = {"Out", "Injured Reserve", "Suspension", "Doubtful"}

# Sort order within a team: certain absences first, practice notes last.
_SEVERITY = {
    "out": 0, "injured reserve": 0, "suspension": 0, "doubtful": 0,
    "questionable": 1,
    "day-to-day": 2,
}


def _severity(status: Any) -> int:
    s = _text(status).lower()
    if s in _SEVERITY:
        return _SEVERITY[s]
    if s.startswith("practice:"):
        return 3
    if any(k in s for k in ("reserve", "out", "suspen", "unable", "doubtful")):
        return 0
    return 2


def _practice_label(practice_status: Any) -> str:
    """nflverse's long practice strings as the three words people use."""
    s = _text(practice_status).lower()
    if not s:
        return ""
    if "did not" in s or "dnp" in s:
        return "DNP"
    if "limited" in s:
        return "Limited"
    if "full" in s:
        return "Full"
    return _text(practice_status)


def _first_text(*values: Any) -> str:
    """The first non-blank value as text -- the precedence rule in one place."""
    for v in values:
        t = _text(v)
        if t:
            return t
    return ""


def _return_text(value: Any) -> str:
    """ESPN's returnDate as 'YYYY-MM-DD', or '' when there is none."""
    t = _text(value)
    if not t:
        return ""
    ts = pd.to_datetime(t, errors="coerce")
    return "" if pd.isna(ts) else ts.strftime("%Y-%m-%d")


def _espn_current_injuries(raw: pd.DataFrame) -> pd.DataFrame:
    """
    ESPN's feed reduced to one CURRENT designation per player.

    The feed is a news log: every designation change is an entry, so a player
    who went Questionable, then Out, then back to Active has three rows.
    'Active' entries are the return news and are dropped; among the rest the
    latest per (team, name) is the one that stands.
    """
    if raw.empty:
        return pd.DataFrame(columns=["team", "_key", "player", "position",
                                     "e_status", "e_injury", "e_return",
                                     "e_updated", "e_comment"])
    df = raw[raw["status"].notna()
             & (raw["status"].astype(str).str.lower() != "active")
             & raw["player"].notna()
             & raw["team"].notna()].copy()
    df["_key"] = df["player"].map(normalize_name)
    df["_when"] = pd.to_datetime(df["updated"], utc=True, errors="coerce")
    df = (df.sort_values(["_when", "updated"], na_position="first")
            .drop_duplicates(subset=["team", "_key"], keep="last"))
    return pd.DataFrame({
        "team": df["team"], "_key": df["_key"],
        "player": df["player"], "position": df["position"],
        "e_status": df["status"], "e_injury": df["injury"],
        "e_return": df["return_date"], "e_updated": df["updated"],
        "e_comment": df["short_comment"],
    })


def _nflverse_week_injuries(season: int, week: int, refresh: bool) -> pd.DataFrame:
    """
    The official injury report for one week, with the reported injury.

    roster.load_injuries() returns a stable subset that omits
    report_primary_injury; when it is missing the raw season parquet is
    consulted for that one column. Any failure there costs the column, not
    the table.
    """
    from . import roster

    inj = roster.load_injuries(season, refresh=refresh)
    if inj.empty or "week" not in inj.columns:
        return pd.DataFrame(columns=["team", "_key", "player", "position",
                                     "n_status", "n_practice", "n_report_injury",
                                     "n_practice_injury"])

    if "report_primary_injury" not in inj.columns:
        try:
            raw = roster._load_cached(roster.INJURY_URL,
                                      f"injuries_{season}.parquet", season, refresh)
            if "report_primary_injury" in raw.columns:
                extra = raw[["season", "week", "team", "gsis_id",
                             "report_primary_injury"]].drop_duplicates(
                    subset=["season", "week", "team", "gsis_id"])
                extra = extra.copy()
                extra["team"] = _normalize_team(extra["team"])
                inj = inj.merge(extra, on=["season", "week", "team", "gsis_id"],
                                how="left")
        except Exception:                              # noqa: BLE001
            pass
    if "report_primary_injury" not in inj.columns:
        inj["report_primary_injury"] = None

    wk = inj[(inj["week"] == week)
             & (inj["report_status"].notna() | inj["practice_status"].notna())
             & inj["full_name"].notna()].copy()
    wk["_key"] = wk["full_name"].map(normalize_name)
    wk = wk.drop_duplicates(subset=["team", "_key"], keep="last")
    return pd.DataFrame({
        "team": wk["team"], "_key": wk["_key"],
        "player": wk["full_name"], "position": wk["position"],
        "n_status": wk["report_status"], "n_practice": wk["practice_status"],
        "n_report_injury": wk["report_primary_injury"],
        "n_practice_injury": wk["practice_primary_injury"],
    })


def injury_table(season: int, week: int, refresh: bool = False) -> pd.DataFrame:
    """
    Every current injury designation, ESPN and the official report merged.

    Both sources describe the same players; ESPN is faster and carries the
    specific injury and an expected return, the official report carries the
    practice participation that ESPN does not. Rows join on
    (team, normalize_name(player)). Where both speak, ESPN's status and
    injury win; where only the practice report speaks, the status reads
    'Practice: DNP' / 'Practice: Limited' / 'Practice: Full' so a resting
    veteran is visibly not an injury.

    Columns: team, player, position, status, injury, practice_status,
    expected_return, updated, comment, source. Sorted by team, then by how
    certain the absence is: Out / IR / Suspension / Doubtful, then
    Questionable, then Day-To-Day, then practice notes.
    """
    try:
        e_raw = espn.fetch_injuries(refresh=refresh)
    except Exception as exc:                           # noqa: BLE001
        print(f"WARNING: ESPN injuries failed unexpectedly ({exc}) — nflverse only")
        e_raw = pd.DataFrame(columns=espn.INJURY_COLUMNS)
    e = _espn_current_injuries(e_raw)

    try:
        n = _nflverse_week_injuries(season, week, refresh)
    except Exception as exc:                           # noqa: BLE001
        print(f"WARNING: nflverse injury report unavailable ({exc}) — ESPN only")
        n = pd.DataFrame(columns=["team", "_key", "player", "position",
                                  "n_status", "n_practice", "n_report_injury",
                                  "n_practice_injury"])

    if e.empty and n.empty:
        return pd.DataFrame(columns=INJURY_TABLE_COLUMNS)

    m = e.merge(n, on=["team", "_key"], how="outer", suffixes=("_e", "_n"),
                indicator=True)

    rows = []
    for _, r in m.iterrows():
        from_espn = r["_merge"] in ("both", "left_only")
        from_nfl = r["_merge"] in ("both", "right_only")
        practice = _practice_label(r.get("n_practice"))
        status = _first_text(r.get("e_status"), r.get("n_status"))
        if not status and practice:
            status = f"Practice: {practice}"
        rows.append({
            "team": r["team"],
            "player": _first_text(r.get("player_e"), r.get("player_n")),
            "position": _first_text(r.get("position_e"), r.get("position_n")),
            "status": status,
            "injury": _first_text(r.get("e_injury"), r.get("n_report_injury"),
                                  r.get("n_practice_injury")),
            "practice_status": practice,
            "expected_return": _return_text(r.get("e_return")),
            "updated": _text(r.get("e_updated")),
            "comment": _text(r.get("e_comment")),
            "source": ("espn+nflverse" if from_espn and from_nfl
                       else "espn" if from_espn else "nflverse"),
        })

    df = pd.DataFrame(rows, columns=INJURY_TABLE_COLUMNS)
    df["_sev"] = df["status"].map(_severity)
    df = (df.sort_values(["team", "_sev", "player"])
            .drop(columns="_sev")
            .reset_index(drop=True))
    return df


# ─────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────

SUMMARY_COLUMNS = [
    "team", "record", "wins", "losses", "ties", "pf", "pa", "pd",
    "home_record", "away_record", "ats_record", "last_result",
    "rating", "rank", "starting_qb", "qb_source", "roster_size",
    "n_injured", "n_out", "injured_list", *POSITION_GROUPS,
]
INJURED_LIST_MAX = 12

# How a roster row is tagged in the position-group text. Active players are
# listed bare and first; everyone else carries why he is not on the field.
_STATUS_TAGS = {
    "practice squad": "PS",
    "injured reserve": "IR",
    "reserve/ir": "IR",
    "suspended": "SUSP",
    "suspension": "SUSP",
    "out": "OUT",
    "exempt": "EXE",
    "pup": "PUP",
    "non-football injury": "NFI",
}
_BARE_STATUSES = {"active", "day-to-day", ""}


def _roster_tag(status: Any, injury_status: Any) -> str:
    """
    '' for a player who can dress, else a short reason like 'IR'.

    The status column is authoritative. The injury designation is consulted
    only behind ESPN's placeholder statuses ('Day-To-Day', 'News'), so a
    roster frame that did not pass through _espn_roster_status still tags
    its IR players correctly.
    """
    s = _text(status).lower()
    i = _text(injury_status).lower()
    if s == "practice squad":
        return "PS"
    if s in _ESPN_PLACEHOLDER_STATUS and i in ("injured reserve", "out", "suspension"):
        return _STATUS_TAGS[i]
    if s in _STATUS_TAGS:
        return _STATUS_TAGS[s]
    if s in _BARE_STATUSES | {"news"}:
        return ""
    return _text(status).upper()


def _group_text(rows: pd.DataFrame) -> str:
    if rows.empty:
        return ""
    tagged = [(_roster_tag(r["status"], r["injury_status"]), _text(r["player"]))
              for _, r in rows.iterrows()]
    active = [name for tag, name in tagged if not tag and name]
    other = [f"{name} ({tag})" for tag, name in tagged if tag and name]
    return ", ".join(active + other)


def _ret_short(expected_return: Any) -> str:
    t = _text(expected_return)
    if not t:
        return ""
    ts = pd.to_datetime(t, errors="coerce")
    return "" if pd.isna(ts) else f"ret {ts.month}/{ts.day}"


def _injured_text(rows: pd.DataFrame) -> str:
    """'Name (POS) - injury - status - ret M/D; ...', capped at 12 entries."""
    if rows.empty:
        return ""
    parts = []
    for _, r in rows.iterrows():
        head = _text(r["player"])
        pos = _text(r["position"])
        if pos:
            head = f"{head} ({pos})"
        bits = [head, _text(r["injury"]), _text(r["status"]),
                _ret_short(r["expected_return"])]
        parts.append(" - ".join(b for b in bits if b))
    text = "; ".join(parts[:INJURED_LIST_MAX])
    if len(parts) > INJURED_LIST_MAX:
        text += f"; +{len(parts) - INJURED_LIST_MAX} more"
    return text


def team_summary(
    games: pd.DataFrame,
    season: int,
    week: int,
    ratings: Optional[pd.DataFrame] = None,
    starters: Optional[dict[str, str]] = None,
    qb_source: Optional[dict[str, str]] = None,
    roster: Optional[pd.DataFrame] = None,
    injuries: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    One row per team: record, rating, quarterback, and who is hurt.

    Always exactly 32 rows in data.TEAMS, whatever was or was not supplied --
    a sheet built on this must not change shape because ESPN was down.
    `ratings` is model.power_ratings() (team, rating, rank); `roster` and
    `injuries` are roster_table() and injury_table() or None.

    The position-group columns list names, active players first, with anyone
    who cannot dress tagged -- 'Name (IR)', 'Name (PS)' -- so a glance at the
    OL cell shows both who starts and who is missing.

    Sorted by rank when ratings are given, else by team.
    """
    records = team_records(games, season, week).set_index("team")

    rating_map: dict[str, float] = {}
    rank_map: dict[str, int] = {}
    if ratings is not None and not ratings.empty and "team" in ratings.columns:
        rating_map = dict(zip(ratings["team"], ratings["rating"]))
        if "rank" in ratings.columns:
            rank_map = dict(zip(ratings["team"], ratings["rank"]))
    starters = starters or {}
    qb_source = qb_source or {}

    roster = roster if roster is not None else pd.DataFrame(columns=ROSTER_TABLE_COLUMNS)
    injuries = injuries if injuries is not None else pd.DataFrame(columns=INJURY_TABLE_COLUMNS)
    roster = roster.reindex(columns=ROSTER_TABLE_COLUMNS)
    injuries = injuries.reindex(columns=INJURY_TABLE_COLUMNS)

    rows = []
    for team in TEAMS:
        rec = records.loc[team]
        tr = roster[roster["team"] == team]
        ti = injuries[injuries["team"] == team]
        row = {
            "team": team,
            "record": rec["record"],
            "wins": int(rec["wins"]), "losses": int(rec["losses"]), "ties": int(rec["ties"]),
            "pf": int(rec["pf"]), "pa": int(rec["pa"]), "pd": int(rec["pd"]),
            "home_record": rec["home_record"], "away_record": rec["away_record"],
            "ats_record": rec["ats_record"], "last_result": rec["last_result"],
            "rating": (float(rating_map[team]) if team in rating_map
                       and pd.notna(rating_map[team]) else None),
            "rank": (int(rank_map[team]) if team in rank_map
                     and pd.notna(rank_map[team]) else None),
            "starting_qb": starters.get(team),
            "qb_source": qb_source.get(team),
            "roster_size": int((tr["status"].map(_text) == "Active").sum()),
            "n_injured": int(len(ti)),
            "n_out": int(ti["status"].map(_text).isin(OUT_STATUSES).sum()),
            "injured_list": _injured_text(ti),
        }
        for grp in POSITION_GROUPS:
            row[grp] = _group_text(tr[tr["pos_group"] == grp])
        rows.append(row)

    df = pd.DataFrame(rows, columns=SUMMARY_COLUMNS)
    if rank_map:
        df = df.sort_values(["rank", "team"], na_position="last")
    else:
        df = df.sort_values("team")
    return df.reset_index(drop=True)


# ─────────────────────────────────────────────
# BUNDLE
# ─────────────────────────────────────────────

def _roster_source(roster: pd.DataFrame) -> str:
    if roster is None or roster.empty:
        return "none"
    kinds = set(roster["source"].dropna().unique())
    if kinds == {"espn"}:
        return "espn"
    if kinds == {"nflverse"}:
        return "nflverse"
    return "mixed"


def _injury_source(injuries: pd.DataFrame) -> str:
    if injuries is None or injuries.empty:
        return "none"
    kinds = set(injuries["source"].dropna().unique())
    has_espn = bool(kinds & {"espn", "espn+nflverse"})
    has_nfl = bool(kinds & {"nflverse", "espn+nflverse"})
    if has_espn and has_nfl:
        return "espn+nflverse"
    if has_espn:
        return "espn"
    return "nflverse"


def team_stats_bundle(
    games: pd.DataFrame,
    season: int,
    week: int,
    ratings: Optional[pd.DataFrame] = None,
    starters: Optional[dict[str, str]] = None,
    qb_source: Optional[dict[str, str]] = None,
    refresh: bool = False,
) -> dict:
    """
    Everything the TEAM STATS sheet needs, in one call that cannot fail.

    Returns {'summary', 'roster', 'injuries', 'records': DataFrames,
    'sources': {'roster': espn|nflverse|mixed|none,
                'injuries': espn+nflverse|espn|nflverse|none}}.

    Each stage is wrapped separately: a dead ESPN feed costs the roster and
    injury detail, never the records or the summary, and never the weekly
    run that called this. Whatever went wrong is printed as a WARNING and the
    `sources` dict says what the sheet is actually built from.
    """
    try:
        records = team_records(games, season, week)
    except Exception as exc:                           # noqa: BLE001
        print(f"WARNING: team records failed ({exc})")
        records = pd.DataFrame(columns=RECORD_COLUMNS)

    try:
        roster = roster_table(season, week, refresh=refresh)
    except Exception as exc:                           # noqa: BLE001
        print(f"WARNING: roster table failed ({exc}) — rosters omitted")
        roster = pd.DataFrame(columns=ROSTER_TABLE_COLUMNS)

    try:
        injuries = injury_table(season, week, refresh=refresh)
    except Exception as exc:                           # noqa: BLE001
        print(f"WARNING: injury table failed ({exc}) — injuries omitted")
        injuries = pd.DataFrame(columns=INJURY_TABLE_COLUMNS)

    try:
        summary = team_summary(games, season, week, ratings=ratings,
                               starters=starters, qb_source=qb_source,
                               roster=roster, injuries=injuries)
    except Exception as exc:                           # noqa: BLE001
        print(f"WARNING: team summary failed ({exc})")
        summary = pd.DataFrame(columns=SUMMARY_COLUMNS)

    return {
        "summary": summary,
        "roster": roster,
        "injuries": injuries,
        "records": records,
        "sources": {
            "roster": _roster_source(roster),
            "injuries": _injury_source(injuries),
        },
    }
