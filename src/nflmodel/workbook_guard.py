"""
workbook_guard.py — is Excel holding this week's workbook open? (expert
review round 2, fix 9)

Twice the game-day card never reached his workbook: 2026 Week 5 was rebuilt
while Excel had the file open and his next save put Friday's card back; Week
7's Sunday run went to a scratch copy because the open window had unsaved
tracker rows, so the archive kept Wednesday's card. A run now asks Excel
first. If the week's workbook is open, the archive is still updated (it
always runs first), and the new workbook is saved BESIDE his, never over it.

Also: the card's changes since the last build, and --qb overrides that the
depth chart contradicts for a quarterback who is not on the injury report
(2026 Week 7: TB="Jalon Daniels" was passed after Mayfield was back).
"""
from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

import pandas as pd

# Asks Excel only when it is already running: `is running` never launches it.
_SCRIPT = '''
if application "Microsoft Excel" is running then
    tell application "Microsoft Excel"
        set ns to name of every workbook
        set ss to saved of every workbook
    end tell
    set out to ""
    repeat with i from 1 to count of ns
        set out to out & (item i of ns) & tab & ((item i of ss) as string) & linefeed
    end repeat
    return out
else
    return "NOT RUNNING"
end if
'''


def excel_state(path) -> dict:
    """
    {'open': bool, 'saved': bool | None, 'how': str} for the workbook at `path`.
    Asks Excel (AppleScript) when it is running; if that fails, an Excel owner
    file (~$name) beside the workbook counts as open with unknown save state.
    """
    path = Path(path)
    try:
        out = subprocess.run(["osascript", "-e", _SCRIPT], capture_output=True,
                             text=True, timeout=15)
        if out.returncode == 0:
            text = out.stdout.strip()
            if text == "NOT RUNNING":
                return dict(open=False, saved=None, how="Excel not running")
            for line in text.splitlines():
                name, _, saved = line.partition("\t")
                if name.strip() == path.name:
                    return dict(open=True, saved=saved.strip().lower() == "true",
                                how="asked Excel")
            return dict(open=False, saved=None, how="asked Excel")
    except (OSError, subprocess.SubprocessError):
        pass
    owner = path.with_name("~$" + path.name)
    if owner.exists():
        return dict(open=True, saved=None, how="Excel owner file")
    return dict(open=False, saved=None, how="no owner file (Excel not asked)")


def side_path(path, now: datetime | None = None) -> Path:
    """Where the new workbook goes when his is open: beside it, stamped."""
    path = Path(path)
    now = now or datetime.now()
    return path.with_name(f"{path.stem} (new {now:%a %H%M}).xlsx")


def _bets(df: pd.DataFrame | None) -> dict:
    if df is None or len(df) == 0 or "bet_side" not in df.columns:
        return {}
    out = {}
    for _, r in df.iterrows():
        side = r.get("bet_side")
        if isinstance(side, str) and side:
            odds = r.get("bet_odds")
            price = "" if odds is None or pd.isna(odds) else f" {float(odds):+.0f}"
            label = side if str(r.get("bet_market", "")).upper() == "MONEYLINE" else side + price
            out[r["game_id"]] = label
    return out


def card_changes(before: pd.DataFrame | None, after: pd.DataFrame) -> list[str]:
    """
    What changed on the card for games still to be played, vs the last
    archived build: added, dropped, and a new number or price.
    """
    old = _bets(before[before.game_id.isin(after.game_id)] if before is not None
                and "game_id" in before.columns else None)
    new = _bets(after)
    lines = []
    for gid in sorted(set(old) | set(new)):
        o, n = old.get(gid), new.get(gid)
        if o == n:
            continue
        if o is None:
            lines.append(f"added    {n}")
        elif n is None:
            lines.append(f"dropped  {o}")
        else:
            lines.append(f"changed  {o}  ->  {n}")
    return lines


def stale_overrides(overrides: dict, chart: dict, injuries: pd.DataFrame | None,
                    norm) -> list[str]:
    """
    Overrides the depth chart contradicts. The chart naming the injured
    starter is the usual reason for an override (Lamar listed, Huntley
    starts), so that is only noted; a charted starter who is NOT on the
    injury report is the stale case.
    """
    lines = []
    for team, name in (overrides or {}).items():
        listed = chart.get(team)
        if not listed or norm(listed) == norm(name):
            continue
        if injuries is None:
            lines.append(f'{team}: --qb "{name}" over the depth chart\'s {listed} (injury '
                         f'report unavailable): confirm {listed} is out.')
            continue
        status = None
        if len(injuries):
            hit = injuries[(injuries.team == team)
                           & (injuries.player.map(norm) == norm(listed))]
            if len(hit):
                status = str(hit.iloc[0].status)
        if status is None:
            lines.append(f'WARNING: --qb {team}="{name}" may be STALE: the depth chart lists '
                         f'{listed}, who is not on the injury report. If {listed} plays, '
                         f'drop the override and re-run.')
        else:
            lines.append(f'{team}: --qb "{name}" over the depth chart\'s {listed} '
                         f'({status} on the injury report). Keep it only if {listed} '
                         f'is confirmed out.')
    return lines
