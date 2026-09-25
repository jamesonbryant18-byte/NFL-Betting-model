"""
shop.py — put live multi-book prices into the weekly run.

The model has been measured at zero incremental signal against the closing
line. The price you actually get filled at has not been measured at zero, and
half a point of spread is worth more than anything these ratings can find.
This module is therefore the highest-value part of the pipeline, which is an
uncomfortable thing for a ratings model to admit.

What it changes
---------------
Before: every number came from nflverse's stored `spread_line`, which is a
single book (DraftKings). One book, one price, take it or leave it.

After: six real books are polled live. The *median* across them becomes the
market number the model is measured against, and the *best* available number
on each side is reported alongside, with the book holding it.

The de-vig trap
---------------
It is tempting to de-vig using the best home price from one book and the best
away price from another. Do not. De-vigging assumes a matched pair from a
single book, and it infers the true probabilities by stripping out the
overround the pair carries. Combining the two best sides shrinks that
overround -- on a live 2026 Week 3 pair, 4.30% collapses to 2.34% -- and a
smaller overround de-vigs to smaller fair probabilities. Every edge, computed
as model minus fair, comes out bigger. On both sides. On every game. In the
direction that makes the model look good, which is exactly the direction no
number in this repo is allowed to drift without being caught.

(With realistic vig, six books are not enough to push the overround below 1.0
outright. The bias is quieter than that, and quieter is worse -- it never
announces itself as an impossible number.)

So the split is deliberate and load-bearing:

    fair probability   <- the CONSENSUS pair (matched, one source)
    edge               <- model probability minus that fair probability
    the price you take <- the best available, reported separately

Shopping improves the fill. It must never be allowed to improve the edge
estimate, because that number is the one deciding whether to bet at all.
"""

from __future__ import annotations

import pandas as pd

from . import odds


def _key(away: str, home: str) -> str:
    return f"{away}@{home}"


def attach_live_odds(slate_games: pd.DataFrame, season: int, week: int,
                     max_dev: float = 1.0, verbose: bool = True,
                     book: str | None = None):
    """
    Replace stored lines with live consensus and attach best-price columns.

    Returns (slate_games, report). On any failure the frame comes back
    untouched and the report says why -- a dead odds feed must degrade to the
    stored line, never take the week down.
    """
    out = slate_games.copy()
    report = {"ok": False, "reason": None, "n_matched": 0, "n_games": len(out),
              "books": [], "moved": [], "rejected": 0, "source": "nflverse"}

    # Keep the stored numbers so the run can show what shopping was worth.
    for col, new in (("spread_line", "stored_spread_line"),
                     ("home_moneyline", "stored_home_ml"),
                     ("away_moneyline", "stored_away_ml")):
        if col in out.columns:
            out[new] = out[col]

    try:
        raw = odds.live_odds(season, week)
    except Exception as ex:                      # noqa: BLE001 - never fatal
        report["reason"] = f"{type(ex).__name__}: {ex}"
        return out, report

    if raw is None or not len(raw):
        report["reason"] = "no rows returned from any odds source"
        return out, report

    if book:
        return _attach_single_book(out, raw, book, report, verbose)

    best = odds.best_lines(raw, max_dev=max_dev)
    if not len(best):
        report["reason"] = "no usable book rows after the outlier guard"
        return out, report

    best = best.set_index("game")

    # The consensus MONEYLINE pair must come from one source to stay matched.
    # Action Network publishes an explicit consensus book; median across books
    # is the fallback and is still a matched pair in the same sense.
    cons = raw[raw.book == "consensus"].set_index("game")
    med_h = raw[~raw.book.isin(["consensus", "open"])].groupby("game").home_ml.median()
    med_a = raw[~raw.book.isin(["consensus", "open"])].groupby("game").away_ml.median()

    new_cols = {c: [] for c in (
        "spread_line", "home_moneyline", "away_moneyline",
        "best_home_spread", "best_home_spread_book", "best_home_spread_odds",
        "best_away_spread", "best_away_spread_book", "best_away_spread_odds",
        "best_home_ml", "best_home_ml_book", "best_away_ml", "best_away_ml_book",
        "n_books", "odds_source")}

    matched = 0
    moved = []
    for _, g in out.iterrows():
        k = _key(g.away_team, g.home_team)
        if k not in best.index:
            # Unmatched game keeps its stored numbers untouched.
            new_cols["spread_line"].append(g.get("spread_line"))
            new_cols["home_moneyline"].append(g.get("home_moneyline"))
            new_cols["away_moneyline"].append(g.get("away_moneyline"))
            for c in new_cols:
                if c not in ("spread_line", "home_moneyline", "away_moneyline"):
                    new_cols[c].append(None if c != "odds_source" else "nflverse")
            continue

        b = best.loc[k]
        matched += 1

        spread = b.get("consensus_spread")
        if pd.isna(spread):
            spread = g.get("spread_line")
        else:
            old = g.get("spread_line")
            if pd.notna(old) and float(old) != float(spread):
                moved.append((k, float(old), float(spread)))

        if k in cons.index:
            h_ml = cons.loc[k, "home_ml"]
            a_ml = cons.loc[k, "away_ml"]
        else:
            h_ml, a_ml = med_h.get(k), med_a.get(k)
        if pd.isna(h_ml) or pd.isna(a_ml):
            h_ml, a_ml = g.get("home_moneyline"), g.get("away_moneyline")

        new_cols["spread_line"].append(float(spread) if pd.notna(spread) else None)
        new_cols["home_moneyline"].append(float(h_ml) if pd.notna(h_ml) else None)
        new_cols["away_moneyline"].append(float(a_ml) if pd.notna(a_ml) else None)
        for c in ("best_home_spread", "best_home_spread_book", "best_home_spread_odds",
                  "best_away_spread", "best_away_spread_book", "best_away_spread_odds",
                  "best_home_ml", "best_home_ml_book", "best_away_ml", "best_away_ml_book",
                  "n_books"):
            v = b.get(c)
            new_cols[c].append(None if (v is None or (not isinstance(v, str) and pd.isna(v))) else v)
        new_cols["odds_source"].append("live")

    for c, vals in new_cols.items():
        out[c] = vals

    report.update(ok=True, n_matched=matched,
                  books=sorted(raw[~raw.book.isin(["consensus", "open"])].book.unique()),
                  moved=moved,
                  rejected=int(best["n_rejected"].fillna(0).sum()),
                  source="live" if matched else "nflverse")

    if verbose:
        print(f"  live odds: {matched}/{len(out)} games from "
              f"{len(report['books'])} books ({', '.join(report['books'])})")
        if report["rejected"]:
            print(f"  [odds] {report['rejected']} outlier book row(s) rejected "
                  f"(>{max_dev}pt from median) — a mis-signed feed manufactures "
                  f"phantom edge, so they are dropped, not shopped")
        if moved:
            print(f"  [odds] consensus differs from the stored line on "
                  f"{len(moved)} game(s):")
            for k, old, new in moved[:6]:
                print(f"           {k:<10} stored {old:+.1f} -> consensus {new:+.1f}")
    return out, report


def _attach_single_book(out: pd.DataFrame, raw: pd.DataFrame, book: str,
                        report: dict, verbose: bool):
    """
    Price every game off ONE book -- the one actually being bet at.

    Spread, spread juice and the moneyline pair all come from that book, so the
    de-vig pair is matched by construction and the edge is measured against the
    exact number that will be on the ticket. A game the book is not carrying
    keeps the stored nflverse line and is flagged, never silently mixed.
    """
    d = odds.dedupe(raw)
    mine = d[d.book == book].set_index("game")
    report["books"] = [book]
    missing, moved, matched = [], [], 0
    cols = {c: [] for c in ("spread_line", "home_moneyline", "away_moneyline",
                            "home_spread_odds", "away_spread_odds",
                            "n_books", "odds_source")}
    for _, g in out.iterrows():
        k = _key(g.away_team, g.home_team)
        r = mine.loc[k] if k in mine.index else None
        if r is not None and pd.notna(r.get("spread")) \
                and pd.notna(r.get("home_ml")) and pd.notna(r.get("away_ml")):
            matched += 1
            old = g.get("spread_line")
            if pd.notna(old) and float(old) != float(r.spread):
                moved.append((k, float(old), float(r.spread)))
            vals = dict(spread_line=float(r.spread),
                        home_moneyline=float(r.home_ml),
                        away_moneyline=float(r.away_ml),
                        home_spread_odds=r.get("spread_odds"),
                        away_spread_odds=r.get("away_spread_odds"),
                        n_books=1, odds_source=book)
            for c in ("home_spread_odds", "away_spread_odds"):
                if vals[c] is None or pd.isna(vals[c]):
                    vals[c] = g.get(c)
        else:
            missing.append(k)
            vals = dict(spread_line=g.get("spread_line"),
                        home_moneyline=g.get("home_moneyline"),
                        away_moneyline=g.get("away_moneyline"),
                        home_spread_odds=g.get("home_spread_odds"),
                        away_spread_odds=g.get("away_spread_odds"),
                        n_books=0, odds_source="nflverse")
        for c in cols:
            cols[c].append(vals[c])
    for c, v in cols.items():
        out[c] = v

    report.update(ok=matched > 0, n_matched=matched, moved=moved,
                  missing=missing, source=book if matched else "nflverse",
                  single_book=book,
                  reason=None if matched else f"{book} not in the odds feed")
    if verbose:
        print(f"  odds: {matched}/{len(out)} games priced at {book.upper()} only")
        for k in missing:
            print(f"  WARNING: {book} has no line for {k} — using the stored "
                  f"nflverse line; check {book} before betting it")
        for k, old, new in moved:
            print(f"           {k:<10} stored {old:+.1f} -> {book} {new:+.1f}")
    return out, report


def shopping_value(slate: pd.DataFrame) -> pd.DataFrame:
    """
    For each recommended bet, the best price and what shopping it is worth.

    Spread gain is in points. Moneyline gain is in cents of American odds,
    which is what actually lands in the account.
    """
    rows = []
    active = slate[slate.recommendation.str.match(r"^(LEAN|BET) ", na=False)]
    for _, g in active.iterrows():
        side = str(g.bet_side).split()[0] if g.bet_side else ""
        is_home = side == g.home_team
        market = str(g.bet_market).upper()

        if market == "SPREAD":
            book = g.get("best_home_spread_book" if is_home else "best_away_spread_book")
            best = g.get("best_home_spread" if is_home else "best_away_spread")
            cons = g.get("spread_line")
            if book is None or best is None or pd.isna(best) or pd.isna(cons):
                continue
            # A home backer wants the SMALLEST spread; an away backer the largest.
            gain = (cons - best) if is_home else (best - cons)
            rows.append(dict(bet=g.bet_side, market="spread", book=book,
                             best=f"{-best:+.1f}" if is_home else f"{best:+.1f}",
                             consensus=f"{-cons:+.1f}" if is_home else f"{cons:+.1f}",
                             gain=f"{gain:+.1f} pts"))
        else:
            book = g.get("best_home_ml_book" if is_home else "best_away_ml_book")
            best = g.get("best_home_ml" if is_home else "best_away_ml")
            # project_slate renames these to home_ml/away_ml; the raw game file
            # calls them home_moneyline/away_moneyline. Accept either, or the
            # moneyline rows silently vanish from the table (they did).
            cons = g.get("home_ml" if is_home else "away_ml")
            if cons is None or pd.isna(cons):
                cons = g.get("home_moneyline" if is_home else "away_moneyline")
            if book is None or best is None or pd.isna(best) or pd.isna(cons):
                continue
            rows.append(dict(bet=g.bet_side, market="moneyline", book=book,
                             best=f"{best:+.0f}", consensus=f"{cons:+.0f}",
                             gain=f"{best - cons:+.0f}"))
    return pd.DataFrame(rows)
