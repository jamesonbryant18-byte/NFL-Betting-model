"""
data.py — all external data acquisition, with local caching.

Sources (all free):
  games.csv   nflverse/nfldata  — schedules, closing spreads, moneylines,
                                  rest days, weather, starting QBs, 1999+
  pbp         nflverse-data     — play-by-play with EPA, 1999+

Everything is cached under data/cache/ as parquet. Delete the cache to force
a refresh; the current season's files auto-expire after CACHE_TTL_HOURS.
"""

from __future__ import annotations

import time
import warnings
from pathlib import Path

import pandas as pd

from .config import CACHE_DIR, CURRENT_SEASON

warnings.filterwarnings("ignore", category=FutureWarning)

GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
PBP_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/pbp/"
    "play_by_play_{season}.parquet"
)

QB_STATS_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/stats_player/"
    "stats_player_week_{season}.parquet"
)
# The ratings history starts in 2010; nothing earlier is fit.
QB_CHECK_FIRST_SEASON = 2010

CACHE_TTL_HOURS = 6

# Franchises that changed abbreviation. We normalize to the current code so a
# team's history is continuous across the relocation.
TEAM_ALIASES = {
    "OAK": "LV",
    "SD": "LAC",
    "STL": "LA",
    "LAR": "LA",
    "SL": "LA",
    "ARZ": "ARI",
    "BLT": "BAL",
    "CLV": "CLE",
    "HST": "HOU",
    "JAC": "JAX",
}

TEAMS = [
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
    "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
    "LA", "LAC", "LV", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SEA", "SF", "TB", "TEN", "WAS",
]

# Home stadium timezone offsets from Eastern, used for the body-clock
# adjustment. Negative = further west.
TEAM_TZ_OFFSET = {
    "ARI": -3, "ATL": 0, "BAL": 0, "BUF": 0, "CAR": 0, "CHI": -1,
    "CIN": 0, "CLE": 0, "DAL": -1, "DEN": -2, "DET": 0, "GB": -1,
    "HOU": -1, "IND": 0, "JAX": 0, "KC": -1, "LA": -3, "LAC": -3,
    "LV": -3, "MIA": 0, "MIN": -1, "NE": 0, "NO": -1, "NYG": 0,
    "NYJ": 0, "PHI": 0, "PIT": 0, "SEA": -3, "SF": -3, "TB": 0,
    "TEN": -1, "WAS": 0,
}


def _normalize_team(s: pd.Series) -> pd.Series:
    return s.replace(TEAM_ALIASES)


def _cache_path(name: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / name


def _is_stale(path: Path, ttl_hours: float = CACHE_TTL_HOURS) -> bool:
    if not path.exists():
        return True
    age_hours = (time.time() - path.stat().st_mtime) / 3600
    return age_hours > ttl_hours


# ─────────────────────────────────────────────
# GAMES / SCHEDULE / CLOSING LINES
# ─────────────────────────────────────────────

def qb_identity_map(df: pd.DataFrame) -> dict[str, str]:
    """
    gsis_id -> the canonical spelling of that quarterback's name.

    nflverse spells the same player several ways across seasons -- "Mitch
    Trubisky" and "Mitchell Trubisky", "Gardner Minshew" and "Gardner
    Minshew II", "Michael Penix" and "Michael Penix Jr." -- and carries a
    handful of outright typos ("Kurt Waner", "Justin Herbery"). The player id
    is stable where the name is not, so the id picks the name.

    The canonical spelling is the most frequent one for that id, which keeps
    the label a human recognizes while merging the history under it.
    """
    pairs = pd.concat([
        df[["home_qb_id", "home_qb_name"]].rename(
            columns={"home_qb_id": "id", "home_qb_name": "name"}),
        df[["away_qb_id", "away_qb_name"]].rename(
            columns={"away_qb_id": "id", "away_qb_name": "name"}),
    ]).dropna()
    if pairs.empty:
        return {}
    return (pairs.groupby("id")["name"]
                 .agg(lambda s: s.value_counts().idxmax())
                 .to_dict())


def _canonicalize_qb_names(df: pd.DataFrame) -> pd.DataFrame:
    """
    Collapse every spelling of a quarterback onto one name.

    This is not cosmetic. The ratings fit keys quarterbacks by NAME, so two
    spellings of one player are two separate rated players splitting his
    starts between them -- and each half is likelier to fall under
    min_qb_starts and get pooled into replacement level. It also breaks the
    join against depth charts, which use the fuller spelling.
    """
    canon = qb_identity_map(df)
    if not canon:
        return df
    for side in ("home", "away"):
        mapped = df[f"{side}_qb_id"].map(canon)
        df[f"{side}_qb_name"] = mapped.fillna(df[f"{side}_qb_name"])
    return df


def load_qb_attempts(season: int, refresh: bool = False) -> pd.DataFrame:
    """Every player with a pass attempt, per team per week, for one season."""
    path = _cache_path(f"qb_attempts_{season}.parquet")
    ttl = CACHE_TTL_HOURS if season >= CURRENT_SEASON else float("inf")

    if refresh or _is_stale(path, ttl):
        df = pd.read_parquet(QB_STATS_URL.format(season=season),
                             columns=["season", "week", "team", "player_id",
                                      "player_display_name", "attempts"])
        df = df[df["attempts"] > 0]
        df.to_parquet(path, index=False)
    else:
        df = pd.read_parquet(path)

    df["team"] = _normalize_team(df["team"])
    return df


def correct_stale_qbs(df: pd.DataFrame, attempts: pd.DataFrame) -> pd.DataFrame:
    """
    Replace a played game's listed starter who never threw a pass.

    nflverse pre-fills home_qb / away_qb with the PROBABLE starter before
    kickoff and does not always correct it afterwards. 2026 Week 3 still
    listed Jayden Daniels for WAS (he sat; Mariota threw all 31 passes) and
    Drew Lock for SEA (Darnold threw 45). The same stale entries run through
    history -- 33 team-games in 2024 alone (IND Week 8 lists Flacco;
    Richardson started). The ratings fit keys quarterbacks on these fields,
    so each one credits a game to a player who did not play it, and the
    review flags a correct input as wrong.

    The rule is deliberately narrow: only a listed QB with ZERO pass attempts
    for that team that week is replaced, by the team's attempts leader. A
    starter hurt early (2026 Week 1 SEA: Darnold, a few snaps) threw at least
    one pass and keeps the listing, which is nflverse's convention and the
    one the model was validated on. Weeks with no stats published yet are
    left alone.
    """
    if attempts.empty:
        return df
    leader = (attempts.sort_values("attempts")
                      .groupby(["season", "week", "team"]).tail(1)
                      .set_index(["season", "week", "team"]))
    threw = set(zip(attempts["season"], attempts["week"], attempts["team"],
                    attempts["player_id"]))
    canon = qb_identity_map(df)

    df = df.copy()
    played = df["result"].notna()
    for side in ("home", "away"):
        team_col, id_col, name_col = (f"{side}_team", f"{side}_qb_id",
                                      f"{side}_qb_name")
        for i in df.index[played]:
            key = (df.at[i, "season"], df.at[i, "week"], df.at[i, team_col])
            if key not in leader.index:
                continue                   # no stats for that game yet
            qid = df.at[i, id_col]
            if isinstance(qid, str) and (*key, qid) in threw:
                continue                   # the listed QB did play
            new = leader.loc[key]
            df.at[i, id_col] = new["player_id"]
            df.at[i, name_col] = canon.get(new["player_id"],
                                           new["player_display_name"])
    return df


def _qb_attempts_all(seasons) -> pd.DataFrame:
    frames = []
    for season in seasons:
        try:
            frames.append(load_qb_attempts(season))
        except Exception as e:
            warnings.warn(f"QB check skipped for {season}: no player stats ({e})")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_games(refresh: bool = False) -> pd.DataFrame:
    """
    Every NFL game 1999-present with closing lines and context.

    Sign conventions, which matter enormously and are easy to get backwards:
      result      = home_score - away_score  (positive = home won)
      spread_line = points the HOME team is favored by
                    (positive = home favored, negative = home is the dog)
      home covers when result > spread_line
    """
    path = _cache_path("games.parquet")

    if refresh or _is_stale(path):
        df = pd.read_csv(GAMES_URL, low_memory=False)
        df.to_parquet(path, index=False)
    else:
        df = pd.read_parquet(path)

    df["home_team"] = _normalize_team(df["home_team"])
    df["away_team"] = _normalize_team(df["away_team"])

    # A listed starter who never threw a pass did not start -- see
    # correct_stale_qbs. Before canonicalizing, so the fix gets the canon name.
    seasons = sorted(s for s in df.loc[df["result"].notna(), "season"].unique()
                     if s >= QB_CHECK_FIRST_SEASON)
    df = correct_stale_qbs(df, _qb_attempts_all(seasons))

    # One quarterback, one name -- see _canonicalize_qb_names.
    df = _canonicalize_qb_names(df)

    # Derived fields used throughout the model.
    df["played"] = df["result"].notna()
    df["neutral"] = df["location"].astype(str).str.lower().ne("home")
    df["home_covered"] = df["result"] > df["spread_line"]
    df["push"] = df["result"] == df["spread_line"]
    df["gameday"] = pd.to_datetime(df["gameday"], errors="coerce")

    return df


# ─────────────────────────────────────────────
# PLAY-BY-PLAY → TEAM-GAME EPA
# ─────────────────────────────────────────────

_PBP_COLS = [
    "game_id", "season", "week", "posteam", "defteam",
    "home_team", "away_team", "epa", "success", "play_type",
    "wp", "qtr", "interception", "fumble_lost", "penalty",
]


def load_pbp(season: int, refresh: bool = False) -> pd.DataFrame:
    """Play-by-play for one season, trimmed to the columns we use."""
    path = _cache_path(f"pbp_{season}.parquet")
    ttl = CACHE_TTL_HOURS if season >= CURRENT_SEASON else float("inf")

    if refresh or _is_stale(path, ttl):
        df = pd.read_parquet(PBP_URL.format(season=season), columns=_PBP_COLS)
        df.to_parquet(path, index=False)
    else:
        df = pd.read_parquet(path)

    for col in ("posteam", "defteam", "home_team", "away_team"):
        df[col] = _normalize_team(df[col])

    return df


def team_game_epa(seasons: list[int], refresh: bool = False) -> pd.DataFrame:
    """
    Collapse play-by-play into one row per team per game.

    Garbage time is excluded (win probability outside 5-95%), because those
    plays reflect score state rather than team quality and they meaningfully
    distort season EPA for teams that blow a lot of games open or get blown
    out themselves.
    """
    frames = []

    for season in seasons:
        try:
            pbp = load_pbp(season, refresh=refresh)
        except Exception:
            # A season with no play-by-play published yet (the current one,
            # before kickoff) is expected, not an error. Skip it; the schedule
            # and posted lines for that season still load from games.csv.
            continue

        scrimmage = pbp[
            pbp["play_type"].isin(["pass", "run"])
            & pbp["posteam"].notna()
            & pbp["epa"].notna()
        ].copy()

        competitive = scrimmage[
            scrimmage["wp"].between(0.05, 0.95) | scrimmage["wp"].isna()
        ]

        off = (
            competitive.groupby(["game_id", "season", "week", "posteam"])
            .agg(
                off_epa=("epa", "mean"),
                off_success=("success", "mean"),
                off_plays=("epa", "size"),
            )
            .reset_index()
            .rename(columns={"posteam": "team"})
        )

        deff = (
            competitive.groupby(["game_id", "season", "week", "defteam"])
            .agg(
                def_epa=("epa", "mean"),
                def_success=("success", "mean"),
                def_plays=("epa", "size"),
            )
            .reset_index()
            .rename(columns={"defteam": "team"})
        )

        merged = off.merge(deff, on=["game_id", "season", "week", "team"], how="outer")
        frames.append(merged)

    if not frames:
        return pd.DataFrame(columns=[
            "game_id", "season", "week", "team", "off_epa", "off_success",
            "off_plays", "def_epa", "def_success", "def_plays", "net_epa",
        ])

    out = pd.concat(frames, ignore_index=True)

    # Net EPA per play: how much better a team was than its opponent on a
    # per-play basis. This is the core team-quality signal.
    out["net_epa"] = out["off_epa"] - out["def_epa"]

    return out


def build_dataset(seasons: list[int], refresh: bool = False,
                  with_epa: bool | None = None) -> pd.DataFrame:
    """
    The modeling table: one row per game, with both teams' EPA attached.

    with_epa=None (the default) decides automatically: the tuned model runs at
    epa_margin_weight = 0, so the EPA columns are multiplied by zero and pulling
    ~14MB of play-by-play per season is pure waste. Pass True to force it.
    """
    from .config import RATINGS

    if with_epa is None:
        with_epa = RATINGS.epa_margin_weight != 0.0

    games = load_games(refresh=refresh)
    games = games[games["season"].isin(seasons)].copy()

    if not with_epa:
        for side in ("home", "away"):
            for col in ("off_epa", "def_epa", "off_success", "def_success", "net_epa"):
                games[f"{side}_{col}"] = float("nan")
        return games

    epa = team_game_epa(seasons, refresh=refresh)

    home_epa = epa.rename(
        columns={c: f"home_{c}" for c in
                 ["off_epa", "def_epa", "off_success", "def_success", "net_epa"]}
    )[["game_id", "team", "home_off_epa", "home_def_epa",
       "home_off_success", "home_def_success", "home_net_epa"]]

    away_epa = epa.rename(
        columns={c: f"away_{c}" for c in
                 ["off_epa", "def_epa", "off_success", "def_success", "net_epa"]}
    )[["game_id", "team", "away_off_epa", "away_def_epa",
       "away_off_success", "away_def_success", "away_net_epa"]]

    df = games.merge(
        home_epa, left_on=["game_id", "home_team"], right_on=["game_id", "team"],
        how="left",
    ).drop(columns=["team"])

    df = df.merge(
        away_epa, left_on=["game_id", "away_team"], right_on=["game_id", "team"],
        how="left",
    ).drop(columns=["team"])

    return df
