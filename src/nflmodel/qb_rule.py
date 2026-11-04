"""
qb_rule.py -- Jameson's rule (2026-11-04): no bets ON a team whose starting
quarterback has fewer than 8 career starts AND fewer than 5 starts this season.
Either one clears him, so a rookie who has started 5 games is bettable.

Why it exists: a new starter is hard to price. The joint team + QB fit leaves a
long-time starter's value in the TEAM rating and gives an unrated backup the
pooled replacement level, so the model understates the drop (PHI with McKee,
2026 Weeks 6-8). The same bets over 2013-25 won 41-52% when the model said
58-61% (scripts/backup_qb_rule.py). It is a guardrail, not a source of profit.

Only bets ON that team are stopped. Betting against him is still allowed.

Starts are counted from the game file: played games before this one, in date
order, across every team he has played for. Names go through normalize_name so
'Michael Penix' and 'Michael Penix Jr.' are one man.
"""
from __future__ import annotations

from collections import defaultdict

import pandas as pd

from .config import THRESHOLDS
from .teamstats import normalize_name


def played_log(games: pd.DataFrame) -> dict[str, list[tuple[str, int]]]:
    """Each quarterback's played starts: normalized name -> [(gameday, season), ...]."""
    log: dict[str, list[tuple[str, int]]] = defaultdict(list)
    done = games[games["result"].notna()]
    for side in ("home", "away"):
        for qb, day, season in zip(done[f"{side}_qb_name"], done["gameday"], done["season"]):
            if isinstance(qb, str) and qb:
                log[normalize_name(qb)].append((str(day)[:10], int(season)))
    return log


def counts_before(log: dict, qb, season: int, gameday) -> tuple[int, int]:
    """(career starts, starts this season) in games played before `gameday`."""
    day = str(gameday)[:10]
    starts = [s for d, s in log.get(normalize_name(qb), ()) if d < day]
    return len(starts), sum(s == int(season) for s in starts)


def is_blocked(career: int, this_season: int, thresholds=THRESHOLDS) -> bool:
    """True when neither count clears the quarterback."""
    return (career < thresholds.qb_min_career_starts
            and this_season < thresholds.qb_min_season_starts)


def game_blocks(slate: pd.DataFrame, games: pd.DataFrame,
                thresholds=THRESHOLDS) -> tuple[dict[str, set], list[dict]]:
    """
    For the games in `slate` (QB names already resolved): game_id -> the teams
    that cannot be bet, plus one detail row per blocked team. An unknown
    quarterback is not blocked; the run warns about those separately.
    """
    log = played_log(games)
    blocks: dict[str, set] = {}
    details: list[dict] = []
    for _, g in slate.iterrows():
        for side in ("home", "away"):
            qb = g.get(f"{side}_qb_name")
            if not isinstance(qb, str) or not qb:
                continue
            career, now = counts_before(log, qb, g["season"], g["gameday"])
            if is_blocked(career, now, thresholds):
                team = g[f"{side}_team"]
                blocks.setdefault(g["game_id"], set()).add(team)
                details.append(dict(game_id=g["game_id"], team=team, qb=qb,
                                    career=career, this_season=now))
    return blocks, details


_history: dict[str, set] | None = None


def history_blocks() -> dict[str, set]:
    """game_id -> blocked teams for every game on file, for the replay. Cached."""
    global _history
    if _history is None:
        from .data import load_games
        games = load_games()
        _history = game_blocks(games[games["season"] >= 2013], games)[0]
    return _history


def describe(detail: dict) -> str:
    """'PHI: Tanner McKee (5 career starts, 3 this season)'"""
    return (f"{detail['team']}: {detail['qb']} ({detail['career']} career starts, "
            f"{detail['this_season']} this season)")
