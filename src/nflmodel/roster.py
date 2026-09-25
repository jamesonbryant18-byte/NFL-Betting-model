"""
roster.py — who is available to play, and how much that is worth.

Scope, stated plainly because it constrains everything below: this model has
exactly ONE player-level term, the quarterback. There are no ratings for any
other player. So keeping rosters current can reach the projection through
exactly two doors:

  1. The quarterback. If the resolved starter is on IR, suspended, or listed
     Out, the projection is wrong by up to ~6 points -- more than home field.
     This is the door that matters and it is wired in.

  2. An aggregate injury-burden term. Everyone else can only enter as a single
     number per team, because the ratings have nowhere else to put them. That
     term ships at ZERO unless measurement justifies it, exactly like every
     other situational adjustment in this repo. See
     scripts/measure_injuries.py.

Everything else here is reporting: it tells the human who is out so he can
overrule the model, which is worth more than a coefficient nobody validated.

Two sources, because they answer different questions:

  Weekly rosters   a season-long status -- ACT, RES (injured reserve,
                   suspended, PUP), CUT, DEV (practice squad), RET, EXE.
                   Available today, changes slowly.

  Injury report    the week-specific designation -- Out, Doubtful,
                   Questionable. Teams file Wednesday through Friday, so a
                   Tuesday run sees an empty or near-empty report. That is a
                   real limitation of running early, not a bug.
"""

from __future__ import annotations

import pandas as pd

from .config import CURRENT_SEASON
from .data import _cache_path, _is_stale, _normalize_team

INJURY_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "injuries/injuries_{season}.parquet"
)
SNAP_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "snap_counts/snap_counts_{season}.parquet"
)
PLAYERS_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "players/players.parquet"
)

ACTIVE_STATUS = "ACT"

# Statuses that mean "on this team's roster, but cannot play": injured
# reserve, PUP, suspended, exempt. These are the real absences.
#
# CUT, DEV and RET are deliberately NOT here, and the distinction matters more
# than it looks. A player who was cut in camp or left in free agency is not
# missing from the team -- he is not ON the team, and his replacement is
# already inside the team's rating and inside the market's price. Counting him
# as an absence made Carolina look like it was missing seven starters.
UNAVAILABLE_STATUS = {"RES", "EXE", "PUP", "NON", "SUS"}

# Injury-report designations that mean he is not playing. "Questionable" is
# deliberately excluded: it resolves to playing far more often than not, and
# treating it as an absence would overstate every team's burden.
OUT_DESIGNATIONS = {"Out", "Doubtful"}

# Injuries are published from 2009 but the early years are sparse; snap counts
# start in 2012. Anything earlier simply has no availability data.
INJURY_FIRST_SEASON = 2009
SNAP_FIRST_SEASON = 2012


def _load_cached(url: str, filename: str, season: int | None, refresh: bool) -> pd.DataFrame:
    path = _cache_path(filename)
    ttl = 6.0 if (season is None or season >= CURRENT_SEASON) else float("inf")
    if refresh or _is_stale(path, ttl):
        df = pd.read_parquet(url if season is None else url.format(season=season))
        df.to_parquet(path, index=False)
    else:
        df = pd.read_parquet(path)
    return df


def load_injuries(season: int, refresh: bool = False) -> pd.DataFrame:
    """
    The weekly injury report for one season.

    The schema drifts between seasons -- 2026 drops the report_secondary_injury
    columns that 2023 carries -- so this returns a stable subset rather than
    whatever that year happened to publish.
    """
    if season < INJURY_FIRST_SEASON:
        return pd.DataFrame(columns=["season", "week", "team", "gsis_id",
                                     "full_name", "position", "report_status"])
    try:
        df = _load_cached(INJURY_URL, f"injuries_{season}.parquet", season, refresh)
    except Exception:
        return pd.DataFrame(columns=["season", "week", "team", "gsis_id",
                                     "full_name", "position", "report_status"])

    keep = ["season", "week", "team", "gsis_id", "full_name", "position",
            "report_status", "practice_status", "practice_primary_injury"]
    for col in keep:
        if col not in df.columns:
            df[col] = None
    df = df[keep].copy()
    df["team"] = _normalize_team(df["team"])
    return df


def load_snap_counts(season: int, refresh: bool = False) -> pd.DataFrame:
    if season < SNAP_FIRST_SEASON:
        return pd.DataFrame()
    try:
        return _load_cached(SNAP_URL, f"snap_counts_{season}.parquet", season, refresh)
    except Exception:
        return pd.DataFrame()


def _pfr_to_gsis(refresh: bool = False) -> dict[str, str]:
    """Snap counts key on PFR ids; everything else here keys on gsis."""
    try:
        players = _load_cached(PLAYERS_URL, "players.parquet", None, refresh)
    except Exception:
        return {}
    if "pfr_id" not in players.columns or "gsis_id" not in players.columns:
        return {}
    x = players[["pfr_id", "gsis_id"]].dropna()
    return dict(zip(x["pfr_id"], x["gsis_id"]))


def player_importance(season: int, refresh: bool = False) -> dict[str, float]:
    """
    How much of his team's football each player was on the field for, 0-1,
    measured over the PRIOR season.

    Prior season, not current, for two reasons: in Week 1 there is no current
    season to measure, and using the current one would let a player's snaps
    from games already played inform a projection of those same games.

    A player is weighted by the larger of his offensive and defensive share,
    which is just "was he a starter". This is a crude proxy for value -- it
    cannot tell a left tackle from a fullback -- and it is deliberately crude,
    because the alternative is a positional value model that this repo has no
    way to validate.

    The share is taken over the whole SEASON, not over the games he appeared
    in. Averaging over appearances scores a one-game fill-in like a franchise
    starter: KC's third quarterback played every snap of the Week 18 game
    where the starters rested, which averaged out to 0.75 -- a bigger loss
    than most actual starters.
    """
    snaps = load_snap_counts(season - 1, refresh=refresh)
    if snaps.empty:
        return {}

    snaps = snaps[snaps["game_type"] == "REG"] if "game_type" in snaps else snaps
    if snaps.empty:
        return {}

    # Denominator is the team's games, so a player who missed half the year
    # scores half of what the same player would have scored playing all of it.
    team_games = snaps.groupby("team")["game_id"].nunique()
    per_player_team = (snaps.groupby(["pfr_player_id", "team"])
                            [["offense_pct", "defense_pct"]].sum())
    denom = per_player_team.index.get_level_values("team").map(team_games)
    share = (per_player_team.div(denom, axis=0)
                            .groupby("pfr_player_id").sum()
                            .max(axis=1)
                            .clip(0, 1))

    xwalk = _pfr_to_gsis(refresh=refresh)
    return {xwalk[p]: float(v) for p, v in share.items() if p in xwalk}


def unavailable(
    season: int,
    week: int,
    refresh: bool = False,
) -> pd.DataFrame:
    """
    Everyone who cannot play this week, by team, with why and how much it costs.

    Two independent reasons, reported separately because they mean different
    things: a roster status (IR, suspended, PUP, released) is a settled fact,
    while an injury designation is this week's news and may not exist yet.

    Returns columns: team, gsis_id, full_name, position, reason, detail,
    importance.
    """
    from .depth import load_weekly_rosters

    rows = []
    importance = player_importance(season, refresh=refresh)

    try:
        rosters = load_weekly_rosters(season, refresh=refresh)
    except Exception:
        rosters = pd.DataFrame()

    if not rosters.empty:
        wk = rosters[rosters["week"] <= week]
        if not wk.empty:
            latest = (wk.sort_values("week")
                        .drop_duplicates(subset=["gsis_id"], keep="last"))
            benched = latest[latest["status"].isin(UNAVAILABLE_STATUS)
                             & latest["gsis_id"].notna()]
            for _, r in benched.iterrows():
                imp = importance.get(r["gsis_id"], 0.0)
                if imp <= 0:
                    continue          # never played meaningful snaps -- not news
                rows.append({
                    "team": r["team"], "gsis_id": r["gsis_id"],
                    "full_name": r.get("full_name"), "position": r.get("position"),
                    "reason": "roster",
                    "detail": f'{r.get("status")}/{r.get("status_description_abbr")}',
                    "importance": imp,
                })

    inj = load_injuries(season, refresh=refresh)
    if not inj.empty:
        this_week = inj[(inj["week"] == week)
                        & inj["report_status"].isin(OUT_DESIGNATIONS)]
        seen = {r["gsis_id"] for r in rows}
        for _, r in this_week.iterrows():
            if r["gsis_id"] in seen:
                continue
            rows.append({
                "team": r["team"], "gsis_id": r["gsis_id"],
                "full_name": r.get("full_name"), "position": r.get("position"),
                "reason": "injury", "detail": r.get("report_status"),
                "importance": importance.get(r["gsis_id"], 0.0),
            })

    if not rows:
        return pd.DataFrame(columns=["team", "gsis_id", "full_name", "position",
                                     "reason", "detail", "importance"])
    return (pd.DataFrame(rows)
              .sort_values(["team", "importance"], ascending=[True, False])
              .reset_index(drop=True))


def injury_burden(season: int, week: int, refresh: bool = False) -> dict[str, float]:
    """
    One number per team: starter-equivalents unavailable.

    A team missing two full-time starters scores about 2.0. This is the only
    form in which non-quarterback availability could ever reach the ratings,
    and it reaches them at weight ZERO until a measurement says otherwise.
    """
    out = unavailable(season, week, refresh=refresh)
    if out.empty:
        return {}
    return out.groupby("team")["importance"].sum().to_dict()


def unavailable_ids(season: int, week: int, refresh: bool = False) -> set[str]:
    """Player ids that cannot start, for the quarterback resolver."""
    out = unavailable(season, week, refresh=refresh)
    if out.empty:
        return set()
    return set(out["gsis_id"].dropna())


def season_burden(season: int, refresh: bool = False) -> pd.DataFrame:
    """
    Injury burden for every team and week of a season, in one pass.

    Same definition as injury_burden(), computed season-wide because the
    measurement script needs thirteen seasons of it and calling the per-week
    path ~230 times would re-derive player importance every time.

    Returns columns: season, week, team, burden.
    """
    from .depth import load_weekly_rosters

    importance = player_importance(season, refresh=refresh)
    if not importance:
        return pd.DataFrame(columns=["season", "week", "team", "burden"])

    frames = []

    try:
        rosters = load_weekly_rosters(season, refresh=refresh)
    except Exception:
        rosters = pd.DataFrame()

    if not rosters.empty:
        r = rosters[rosters["status"].isin(UNAVAILABLE_STATUS)].copy()
        r = r.dropna(subset=["gsis_id"])
        frames.append(r[["week", "team", "gsis_id"]])

    inj = load_injuries(season, refresh=refresh)
    if not inj.empty:
        i = inj[inj["report_status"].isin(OUT_DESIGNATIONS)].copy()
        i = i.dropna(subset=["gsis_id"])
        frames.append(i[["week", "team", "gsis_id"]])

    if not frames:
        return pd.DataFrame(columns=["season", "week", "team", "burden"])

    # A player on injured reserve is usually ALSO on the injury report as Out.
    # Dropping to one row per player-week is what stops him being charged
    # against his team twice.
    allf = (pd.concat(frames, ignore_index=True)
              .drop_duplicates(subset=["week", "team", "gsis_id"]))
    allf["burden"] = allf["gsis_id"].map(importance).fillna(0.0)
    out = (allf.groupby(["week", "team"], as_index=False)["burden"].sum())
    out.insert(0, "season", season)
    return out
