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
from .closing import close_for, load_closing, ticket
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


def model_bets(season: int, weeks, games: pd.DataFrame, mm, archive_dir=None) -> pd.DataFrame:
    """
    Every bet the model published (weekNN_leans.csv, the Bet Log's source),
    settled, with the model's chance, the closing market's chance and the value
    at the price taken.
    """
    played = games[(games.season == season) & games.result.notna()]
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
            g = played[(played.week == week) & (played.home_team == l.home_team)
                       & (played.away_team == l.away_team)]
            if g.empty:
                continue
            market = str(l.bet_market).upper()
            bet_home = side.split()[0] == l.home_team
            odds = float(l.bet_odds)
            tick = ticket(side) if market == "SPREAD" else None
            margin = float(g.result.iloc[0]) * (1 if bet_home else -1)
            beat = margin + (tick if market == "SPREAD" else 0.0)
            units = _payout(odds) if beat > 0 else (0.0 if beat == 0 else -1.0)
            if market == "MONEYLINE":
                p_model = float(l.home_win_prob) if bet_home else 1 - float(l.home_win_prob)
            else:
                pw, pp, pl = _cover(mm, float(l.projected_margin), float(l.spread_line), bet_home)
                p_model = pw / max(1e-9, pw + pl)
            crow = close_for(closing, l.home_team, l.away_team)
            ev, p_close = value_at_price(mm, market, bet_home, tick, odds, crow)
            src = None if crow is None else str(crow.get("close_source") or "")
            rows.append(dict(
                week=week, bet=side, market=market, odds=odds,
                filler=str(l.get("confidence", "")) == "Filler",
                out="W" if units > 0 else ("P" if units == 0 else "L"), units=units,
                p_model=p_model, p_close=p_close, value_at_close=ev,
                break_even=_break_even(odds), close_source=src,
                not_fanduel=bool(src) and "fanduel" not in src.lower()))
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
