"""
scorecard.py — is the model good, or just lucky? (expert review 2026-10-29)

Read from the archive, i.e. what the model published, never from his Bet
Tracker (his own picks and prices are his; the model is graded on its own):

  straight up   the model's winners against simply taking the favorite, at
                publication and at the close, on the same games. Every pick
                AGAINST the favorite is listed, because that is the only place
                the model can beat the favorite at all.
  bets          the model's card against three yardsticks: the break-even win
                rate of its prices, the win rate it expected, and the win rate
                the CLOSING market expected. Plus the value at the price taken:
                the expected return of each bet if FanDuel's de-vigged close is
                the truth. That last one converges fastest; luck cannot move it.

The closing market is FanDuel's (closing.py); a close from another book is
flagged, never silently mixed in.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import archive as _archive
from .closing import close_for, load_closing, side_close, ticket
from .market import devig


def _payout(odds: float) -> float:
    return odds / 100.0 if odds > 0 else 100.0 / abs(odds)


def _break_even(odds: float) -> float:
    return -odds / (-odds + 100.0) if odds < 0 else 100.0 / (odds + 100.0)


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(v) else v


def _band(values) -> tuple[float, float]:
    """Mean and its standard error."""
    v = np.asarray([x for x in values if x is not None and not np.isnan(x)], dtype=float)
    if len(v) == 0:
        return float("nan"), float("nan")
    se = v.std(ddof=1) / np.sqrt(len(v)) if len(v) > 1 else float("nan")
    return float(v.mean()), float(se)


def _close_favorite(row, home: str, away: str):
    """The closing favorite (spread; moneyline on a pick'em), or None."""
    if row is None:
        return None
    cs = _num(row.get("close_spread"))
    if cs:
        return home if cs > 0 else away
    h, a = _num(row.get("close_home_ml")), _num(row.get("close_away_ml"))
    if h is None or a is None or h == a:
        return None
    return home if h < a else away


def _close_fair_home(row) -> float | None:
    """FanDuel's closing home win %, moneylines de-vigged."""
    if row is None:
        return None
    h, a = _num(row.get("close_home_ml")), _num(row.get("close_away_ml"))
    if h is None or a is None:
        return None
    return float(devig(h, a)[0])


# ── straight up ─────────────────────────────────────────────────────────

def straight_up(season: int, weeks, games: pd.DataFrame, archive_dir=None) -> pd.DataFrame:
    """
    One row per graded game (ties left out): the model's pick, the favorite at
    publication and at the close, who won, and what the closing market gave
    the model's pick.
    """
    played = games[(games.season == season) & games.result.notna()]
    rows = []
    for week in weeks:
        picks, _ = _archive.load_archived(season, week)
        if picks is None or len(picks) == 0:
            continue
        closing = load_closing(season, week, archive_dir)
        for _, p in picks.iterrows():
            home, away = (p.winner, p.loser) if bool(p.at_home) else (p.loser, p.winner)
            g = played[(played.week == week) & (played.home_team == home) & (played.away_team == away)]
            if g.empty or g.result.iloc[0] == 0:
                continue
            res = float(g.result.iloc[0])
            won = home if res > 0 else away
            fav_pub = p.winner if bool(p.get("market_favorite", True)) else p.loser
            crow = close_for(closing, home, away)
            fav_close = _close_favorite(crow, home, away)
            fair = _close_fair_home(crow)
            rows.append(dict(
                week=week, game_id=g.game_id.iloc[0], matchup=f"{away} @ {home}",
                pick=p.winner, opp=p.loser, said=float(p.win_prob),
                winner=won, fav_pub=fav_pub, fav_close=fav_close,
                model_right=p.winner == won, fav_pub_right=fav_pub == won,
                fav_close_right=None if fav_close is None else fav_close == won,
                against_pub=p.winner != fav_pub,
                market_said=None if fair is None else (fair if p.winner == home else 1 - fair)))
    return pd.DataFrame(rows)


def summarize_straight_up(su: pd.DataFrame) -> dict:
    """Model vs favorite on the same games, with the paired standard error."""
    if su.empty:
        return dict(n=0)
    m = su.model_right.astype(float).to_numpy()
    f = su.fav_pub_right.astype(float).to_numpy()
    diff, se = _band(m - f)
    has_close = su.fav_close_right.notna()
    against = su[su.against_pub]
    return dict(
        n=int(len(su)), model=int(m.sum()), fav_pub=int(f.sum()),
        n_close=int(has_close.sum()),
        model_on_close=int(su.loc[has_close, "model_right"].sum()),
        fav_close=int(su.loc[has_close, "fav_close_right"].astype(bool).sum()),
        diff_per_game=diff, diff_se=se,
        expected_model=float(su.said.sum()),
        expected_market=float(su.market_said.dropna().sum()),
        n_market=int(su.market_said.notna().sum()),
        against=int(len(against)), against_won=int(against.model_right.sum()))


# ── the model's bets ────────────────────────────────────────────────────

def _cover(mm, margin: float, home_line: float, bet_home: bool):
    ph, pp, pa = mm.cover_prob(margin, home_line)
    return (ph, pp, pa) if bet_home else (pa, pp, ph)


def _market_mean(mm, close_home_line: float, home_fair: float) -> float:
    """The margin the closing spread and its juice imply (pushes left out)."""
    from scipy.optimize import brentq

    def gap(m):
        ph, _, pa = mm.cover_prob(m, close_home_line)
        return ph / (ph + pa) - home_fair
    return brentq(gap, -40, 40)


def value_at_price(mm, market: str, bet_home: bool, tick, odds: float, crow) -> tuple:
    """
    (expected return per $1, chance to win) of a bet at the number and price
    actually taken, if FanDuel's de-vigged close is the true price. Spreads are
    key-number aware: the closing spread and its juice fix a margin
    distribution, and the bet's own number is priced on it, so buying a half
    point through 3 is worth what it is really worth. (None, None) if the close
    is missing.
    """
    if crow is None:
        return None, None
    if market == "MONEYLINE":
        fair = _close_fair_home(crow)
        if fair is None:
            return None, None
        p = fair if bet_home else 1 - fair
        return p * _payout(odds) - (1 - p), p
    cs = _num(crow.get("close_spread"))
    if cs is None or tick is None:
        return None, None
    ho, ao = _num(crow.get("close_home_spread_odds")), _num(crow.get("close_away_spread_odds"))
    home_fair = float(devig(ho, ao)[0]) if ho is not None and ao is not None else 0.5
    m = _market_mean(mm, cs, home_fair)
    home_line = -tick if bet_home else tick
    pw, pp, pl = _cover(mm, m, home_line, bet_home)
    return pw * _payout(odds) - pl, pw / max(1e-9, pw + pl)


def model_bets(season: int, weeks, games: pd.DataFrame, mm, archive_dir=None,
               pending: bool = False) -> pd.DataFrame:
    """
    Every bet the model published (weekNN_leans.csv, the Bet Log's source),
    settled, with the model's chance, the closing market's chance and the value
    at the price taken. `pending` also lists bets on games not yet played
    (out '', units NaN), for the ledger.
    """
    in_season = games[games.season == season]
    rows = []
    for week in weeks:
        _, leans = _archive.load_archived(season, week)
        if leans is None or len(leans) == 0:
            continue
        closing = load_closing(season, week, archive_dir)
        for _, l in leans.iterrows():
            side = str(l.get("bet_side") or "")
            if not side or side == "nan":
                continue
            g = in_season[(in_season.week == week) & (in_season.home_team == l.home_team)
                          & (in_season.away_team == l.away_team)]
            if g.empty or (pd.isna(g.result.iloc[0]) and not pending):
                continue
            market = str(l.bet_market).upper()
            bet_home = side.split()[0] == l.home_team
            odds = float(l.bet_odds)
            tick = ticket(side) if market == "SPREAD" else None
            if pd.isna(g.result.iloc[0]):
                units, out = float("nan"), ""
            else:
                margin = float(g.result.iloc[0]) * (1 if bet_home else -1)
                beat = margin + (tick if market == "SPREAD" else 0.0)
                units = _payout(odds) if beat > 0 else (0.0 if beat == 0 else -1.0)
                out = "W" if units > 0 else ("P" if units == 0 else "L")
            if market == "MONEYLINE":
                p_model = float(l.home_win_prob) if bet_home else 1 - float(l.home_win_prob)
            else:
                pw, pp, pl = _cover(mm, float(l.projected_margin), float(l.spread_line), bet_home)
                p_model = pw / max(1e-9, pw + pl)
            crow = close_for(closing, l.home_team, l.away_team)
            ev, p_close = value_at_price(mm, market, bet_home, tick, odds, crow)
            src = None if crow is None else str(crow.get("close_source") or "")
            if market == "MONEYLINE":
                edge = _num(l.get("ml_edge_home") if bet_home else l.get("ml_edge_away"))
            else:
                edge = _num(l.get("spread_edge_pts"))
                edge = None if edge is None else abs(edge)
            hm, am = _num(l.get("home_ml")), _num(l.get("away_ml"))
            if market == "SPREAD" and tick:
                favorite = tick < 0                      # laying points
            elif hm is not None and am is not None and hm != am:
                favorite = (hm < am) if bet_home else (am < hm)
            else:
                favorite = odds < -100
            team = side.split()[0]
            close_odds = None
            if crow is not None:
                close_odds = (_num(crow.get("close_home_spread_odds" if bet_home
                                            else "close_away_spread_odds"))
                              if market == "SPREAD" else side_close(crow, market, team))
            rows.append(dict(
                week=week, game=f"{l.away_team} @ {l.home_team}", bet=side, market=market,
                odds=odds, line=tick, edge=edge,
                favorite=bool(favorite),
                filler=str(l.get("confidence", "")) == "Filler",
                out=out, units=units,
                p_model=p_model, p_close=p_close, value_at_close=ev,
                break_even=_break_even(odds), close_source=src,
                not_fanduel=bool(src) and "fanduel" not in src.lower(),
                stake=_num(l.get("stake")),
                home_spread_odds=_num(l.get("home_spread_odds")),
                away_spread_odds=_num(l.get("away_spread_odds")),
                close=side_close(crow, market, team), close_odds=close_odds,
                still_bet_at="" if pd.isna(l.get("still_bet_at")) else str(l.get("still_bet_at"))))
    return pd.DataFrame(rows)


LEDGER_COLS = ["week", "game", "bet", "market", "line", "odds", "home_spread_odds",
               "away_spread_odds", "stake", "p_model", "edge", "favorite", "filler",
               "still_bet_at", "out", "units", "pnl_at_5", "close", "close_odds", "close_source",
               "p_close", "value_at_close"]


def bet_ledger(season: int, weeks, games: pd.DataFrame, mm, archive_dir=None) -> pd.DataFrame:
    """
    The graded ledger: one row per bet the model published (expert review
    round 2). Derived from the archive, which it never changes, and rebuilt
    whole each time. p_model is the bet's own chance (the cover chance for a
    spread, pushes left out); line is the ticket's number; home/away spread
    prices, stake and still_bet_at are archived from 2026 Week 8 on (the
    model's stake was a flat $5 from Week 4, half-Kelly before, and was not
    archived); units is the result per $1 and pnl_at_5 the dollars at his
    locked $5; close, close_odds and value_at_close are from the
    recorded close (FanDuel unless close_source says otherwise). A bet whose
    game is not played yet has a blank result.
    """
    b = model_bets(season, weeks, games, mm, archive_dir, pending=True)
    if b.empty:
        return pd.DataFrame(columns=LEDGER_COLS)
    b["units"] = b.units.astype(float).round(4)
    b["pnl_at_5"] = (b.units * 5).round(2)
    for c in ("p_model", "p_close", "value_at_close"):
        b[c] = b[c].astype(float).round(4)
    b["edge"] = b.edge.astype(float).round(3)
    return b[LEDGER_COLS]


def _price_bucket(market: str, odds: float, line) -> str:
    if market == "MONEYLINE":
        return ("ML -200 or shorter" if odds <= -200 else "ML -199 to -101" if odds < -100
                else "ML +100 to +150" if odds <= 150 else "ML +151 or longer")
    a = abs(line) if line is not None and line == line else 0.0
    return "spread within 3" if a <= 3 else "spread 3.5 to 7" if a <= 7 else "spread 7.5 or more"


def _edge_bucket(market: str, edge) -> str | None:
    if edge is None or edge != edge:
        return None
    if market == "MONEYLINE":
        return "ML edge 3-5%" if edge < 0.05 else "ML edge 5-8%" if edge < 0.08 else "ML edge 8%+"
    return ("spread edge 1.5-2.5" if edge < 2.5 else "spread edge 2.5-3.5" if edge < 3.5
            else "spread edge 3.5+")


SLICE_ORDER = {
    "market": ["spreads", "moneylines"],
    "side": ["favorites", "underdogs"],
    "price": ["spread within 3", "spread 3.5 to 7", "spread 7.5 or more", "ML -200 or shorter",
              "ML -199 to -101", "ML +100 to +150", "ML +151 or longer"],
    "edge": ["spread edge 1.5-2.5", "spread edge 2.5-3.5", "spread edge 3.5+",
             "ML edge 3-5%", "ML edge 5-8%", "ML edge 8%+"],
}


def slice_bets(b: pd.DataFrame) -> pd.DataFrame:
    """
    The model's bets by market, favorite/underdog, price and edge size: record,
    ROI and value at the close per slice. A slice is only good if its value at
    the close is above zero; a record by itself can be luck.
    """
    if b.empty:
        return pd.DataFrame()
    key = {
        "market": b.market.map({"SPREAD": "spreads", "MONEYLINE": "moneylines"}),
        "side": pd.Series(np.where(b.favorite.astype(bool), "favorites", "underdogs"), index=b.index),
        "price": pd.Series([_price_bucket(m, o, ln) for m, o, ln in zip(b.market, b.odds, b.line)],
                           index=b.index),
        "edge": pd.Series([_edge_bucket(m, e) for m, e in zip(b.market, b.edge)], index=b.index),
    }
    rows = []
    for group, labels in SLICE_ORDER.items():
        for label in labels:
            g = b[key[group] == label]
            if g.empty:
                continue
            roi, roi_se = _band(g.units)
            val, val_se = _band(g.value_at_close.dropna())
            rows.append(dict(group=group, slice=label, n=int(len(g)),
                             won=int((g.out == "W").sum()), lost=int((g.out == "L").sum()),
                             push=int((g.out == "P").sum()), roi=roi, roi_se=roi_se,
                             value=val, value_se=val_se))
    return pd.DataFrame(rows)


def summarize_bets(b: pd.DataFrame) -> dict:
    if b.empty:
        return dict(n=0)
    dec = b[b.out != "P"]
    roi, roi_se = _band(b.units)
    val, val_se = _band(b.value_at_close.dropna())
    pm = dec.p_model.to_numpy(float)
    pc = dec.p_close.dropna().to_numpy(float)
    return dict(
        n=int(len(b)), won=int((b.out == "W").sum()), lost=int((b.out == "L").sum()),
        push=int((b.out == "P").sum()), units=float(b.units.sum()), roi=roi, roi_se=roi_se,
        break_even=float(dec.break_even.mean()) if len(dec) else float("nan"),
        win_pct=float((dec.out == "W").mean()) if len(dec) else float("nan"),
        expected_model=float(pm.sum()), expected_model_sd=float(np.sqrt((pm * (1 - pm)).sum())),
        expected_close=float(pc.sum()), expected_close_sd=float(np.sqrt((pc * (1 - pc)).sum())),
        n_close=int(len(pc)), decided=int(len(dec)),
        value=val, value_se=val_se, n_value=int(b.value_at_close.notna().sum()),
        not_fanduel=int(b.not_fanduel.sum()))


def write_ledger(season: int, games: pd.DataFrame, mm=None, path=None):
    """
    Rebuild data/model_bet_ledger_<season>.csv from every archived week.
    Returns (path, ledger). review_week.py calls this every week.
    """
    from .config import REPO_ROOT
    if mm is None:
        from .trends import margin_model_for_history
        mm = margin_model_for_history()
    d = _archive.ARCHIVE_DIR / str(season)
    weeks = sorted(int(p.name[4:6]) for p in d.glob("week??_leans.csv"))
    led = bet_ledger(season, weeks, games, mm)
    path = path or REPO_ROOT / "data" / f"model_bet_ledger_{season}.csv"
    led.to_csv(path, index=False)
    return path, led
