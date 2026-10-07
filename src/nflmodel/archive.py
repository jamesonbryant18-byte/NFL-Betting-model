"""
archive.py — the permanent record of what the model said, and when.

output/ is gitignored and every file in it can be rebuilt from nflverse. That
is fine for a workbook and fatal for a prediction. Rebuilding Week 3's picks in
December scores them against lines the model never saw, injuries that had not
happened, and a ratings fit trained on the games being predicted. The rebuilt
file would look like a forecast and would actually be a memory.

So the picks are written once, to a tracked directory, and never regenerated.
An archived week is append-only: re-running the same week refuses to overwrite
a file whose games have already kicked off.

Layout:
    picks/<season>/week<NN>_picks.csv    straight-up ranking, as published
    picks/<season>/week<NN>_leans.csv    where the model disagreed with a price
    picks/<season>/week<NN>_meta.json    when it ran, which QBs it assumed
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone

import pandas as pd

from .config import REPO_ROOT

ARCHIVE_DIR = REPO_ROOT / "picks"

# Columns of the slate worth keeping. The full slate has intermediate
# probability columns that are reproducible from these.
LEAN_COLS = [
    "game_id", "home_team", "away_team", "spread_line", "projected_margin",
    "fair_spread", "spread_edge_pts", "home_win_prob", "home_ml", "away_ml",
    "ml_edge_home", "ml_edge_away", "recommendation", "bet_market",
    "bet_side", "bet_odds", "confidence", "bet_type", "bet_why",
    # Live-book provenance. Without these the CLV measurement compares the
    # close against one book's Tuesday number rather than the best price
    # actually on offer, which understates what the week was really worth.
    # Absent when the odds feed was down or --no-live-odds was passed.
    "odds_source", "n_books", "stored_spread_line",
    "best_home_spread", "best_home_spread_book",
    "best_away_spread", "best_away_spread_book",
    "best_home_ml", "best_home_ml_book",
    "best_away_ml", "best_away_ml_book",
    "selftune_adj", "trend_adj", "trend_notes", "wx_label",
    "factor_adj", "factor_inj", "factor_epa", "factor_rest", "factor_notes",
]


def week_dir(season: int) -> "pathlib.Path":
    d = ARCHIVE_DIR / str(season)
    d.mkdir(parents=True, exist_ok=True)
    return d


def kickoff_has_passed(games, season: int, week: int) -> bool:
    """
    Has the first game of this week already started?

    Used to refuse archiving a week after the fact. The check is on the
    EARLIEST kickoff, not the last: once any game has begun, a set of picks
    written now is no longer a forecast for the full slate.
    """
    if games is None or not len(games):
        return False
    try:
        wk = games[(games["season"] == season) & (games["week"] == week)]
        if wk.empty or wk["gameday"].isna().all():
            return False
        first = pd.to_datetime(wk["gameday"]).min()
        return bool(pd.Timestamp(first) < pd.Timestamp(datetime.now().date()))
    except Exception:
        return False


def archive_week(ranked, slate, starters, qb_source, season: int, week: int,
                 force: bool = False, games=None, extra_meta: dict | None = None) -> bool:
    """
    Write this week's picks to the tracked archive.

    Returns True if written. Refuses in two cases, both for the same reason --
    the archive is the only record that can ever settle whether this model
    works, and it is worth nothing if it can be written after the fact:

      1. The week is locked, i.e. review_week.py has already graded it.
      2. The week's first game has already kicked off and no archive exists.
         That is a REPLAY. Its picks were generated with today's code against
         a slate whose results are known, and while the ratings fit is
         leak-guarded, the picks were never published and never risked
         anything. Letting them into picks/ would manufacture a track record
         out of hindsight and the Bet Log would then show it as real history.

    Re-running before kickoff (lines moved, a starter changed) does update the
    archive, because that is still a forecast. `force=True` overrides both
    refusals and exists for backfilling a week that genuinely was published.
    """
    d = week_dir(season)
    picks_path = d / f"week{week:02d}_picks.csv"
    meta_path = d / f"week{week:02d}_meta.json"

    if not force and not picks_path.exists() and kickoff_has_passed(games, season, week):
        print(f'  archive: {season} week {week} has already kicked off and was '
              f'never published — not archiving a rebuilt prediction. '
              f'(scripts/run_week.py --archive-anyway overrides.)')
        return False

    if picks_path.exists() and not force:
        try:
            prior = json.loads(meta_path.read_text())
            if prior.get("locked"):
                print(f'  archive: week {week} is locked (games have started) '
                      f'— not overwriting {picks_path.name}')
                return False
        except Exception:
            pass

    keep = [c for c in LEAN_COLS if c in slate.columns]
    # LEAN in advisory mode, BET in decision mode: both are the model's priced call.
    leans = slate[slate["recommendation"].str.match(r"^(LEAN|BET) ")][keep]
    leans_path = d / f"week{week:02d}_leans.csv"

    # The projection BEFORE the trend fixes and the self-tune nudge, for every
    # game. The trend check learns from this, never from the fixed number --
    # otherwise next week it would fix its own fixes (audit 2026-09-26).
    ranked = ranked.copy()
    has_teams = {"away_team", "home_team"} <= set(slate.columns) and "matchup" in ranked.columns
    s_ = slate.assign(matchup=slate["away_team"] + " @ " + slate["home_team"]).set_index("matchup") \
        if has_teams else pd.DataFrame()
    for col in ("trend_adj", "selftune_adj", "factor_adj", "factor_inj",
                "factor_epa", "factor_rest", "factor_notes", "spread_line"):
        if col in s_.columns:
            ranked[col] = ranked["matchup"].map(s_[col])
    if "projected_margin" in s_.columns:
        home_margin = ranked["matchup"].map(s_["projected_margin"])
        zero = pd.Series(0.0, index=ranked.index)
        ranked["raw_margin"] = home_margin - sum(
            ranked.get(c, zero).fillna(0) for c in ("trend_adj", "selftune_adj", "factor_adj"))

    # A mid-week re-run only covers games not yet played. Carry the published
    # rows for the rest forward untouched, so Thursday's pick is never lost --
    # and keep WHEN it was published (audit: the rerun stamped it with its own
    # time and trend state, two days after the game).
    carried_meta = {}
    if picks_path.exists() and not force:
        prior = pd.read_csv(picks_path)
        try:
            prior_meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        except Exception:
            prior_meta = {}
        carried = prior[~prior["matchup"].isin(ranked["matchup"])]
        for m in carried["matchup"]:
            carried_meta[m] = (prior_meta.get("carried") or {}).get(m) or dict(
                generated_utc=prior_meta.get("generated_utc"),
                trend_fixes=prior_meta.get("trend_fixes"))
        if len(carried):
            ranked = pd.concat([carried, ranked], ignore_index=True)
        if leans_path.exists():
            pl = pd.read_csv(leans_path)
            pl = pl[~pl["game_id"].isin(slate["game_id"])]
            if len(pl):
                leans = pd.concat([pl, leans], ignore_index=True)

    ranked.to_csv(picks_path, index=False)
    leans.to_csv(leans_path, index=False)
    _keep_first_published(leans, d / f"week{week:02d}_first_leans.csv")

    meta = {
        "season": season,
        "week": week,
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_games": int(len(ranked)),
        "n_leans": int(len(leans)),
        "starters": {t: starters[t] for t in sorted(starters)},
        "starter_source": {t: qb_source.get(t, "?") for t in sorted(starters)},
        # Set by review_week.py once the games are played. Until then the week
        # is still a forecast and may legitimately be refreshed.
        "locked": False,
    }
    # What else the model knew when it said this: the weather forecast and
    # which miss-trend fixes were live.
    if extra_meta:
        meta.update(extra_meta)
    if carried_meta:
        meta["carried"] = carried_meta
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
    print(f'  archived: picks/{season}/week{week:02d}_*.csv')
    return True


def _keep_first_published(leans: pd.DataFrame, path: pathlib.Path) -> None:
    """
    Append any bet not seen before this week to weekNN_first_leans.csv, with
    the number it was first published at. Rows already there are never
    changed, so a Sunday re-run (priced near kickoff) cannot overwrite the
    Wednesday number that closing line value is measured from. A bet is the
    same bet if game, market and team match, whatever its line has moved to.
    """
    if leans is None or leans.empty or "bet_side" not in leans.columns:
        return
    fresh = leans.assign(
        published_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"))

    def keys(df):
        return list(zip(df["game_id"].astype(str), df["bet_market"].astype(str),
                        df["bet_side"].astype(str).str.split().str[0]))

    if path.exists():
        first = pd.read_csv(path)
        seen = set(keys(first))
        add = fresh[[k not in seen for k in keys(fresh)]]
        if add.empty:
            return
        fresh = pd.concat([first, add], ignore_index=True)
    fresh.to_csv(path, index=False)


def load_archived(season: int, week: int):
    """The picks as published, or (None, None) if that week was never run."""
    d = ARCHIVE_DIR / str(season)
    p, l = d / f"week{week:02d}_picks.csv", d / f"week{week:02d}_leans.csv"
    if not p.exists():
        return None, None
    picks = pd.read_csv(p)
    leans = pd.read_csv(l) if l.exists() else pd.DataFrame()
    return picks, leans


def lock_week(season: int, week: int) -> None:
    """Mark a week final so a later run cannot quietly rewrite its picks."""
    meta_path = ARCHIVE_DIR / str(season) / f"week{week:02d}_meta.json"
    if not meta_path.exists():
        return
    meta = json.loads(meta_path.read_text())
    meta["locked"] = True
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")
