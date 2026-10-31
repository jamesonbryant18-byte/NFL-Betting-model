"""
replay.py — the deployed model, replayed game by game on 2013-2025.

One definition of "the model as it runs live", so every check measures the
same thing: the factor refit, the win-% calibration, the ablation and the
expert review's grade. Before 2026-10-29 the factor lab, the trend checker and
the reviewers each rebuilt the stack their own way, and the win-% correction
ended up fit on a different model from the one it was applied to.

Each piece stays in its own column, so dropping one is a subtraction:

  base     frozen walk-forward projection: ratings + joint QB + home field +
           market prior, each game projected from earlier games plus its own
           line (as the game-day run sees it).
           data/cache/base_projections_2013_2025.parquet
  trend    confirmed miss-trend fixes (data/trends.json), tested on the frozen
           projection exactly as run_week tests them
  fac_*    game factors (config.FACTORS), one column per term; fac = the sum
  proj     base + trend + fac
  wp       home win %: run_week's margin distribution, then the recalibration

The weekly self-tune is off (2026-10-29) and is not part of the replay; the
ablation script adds it back to measure it.

Hold-out rule: `deployed()` FITS the factor weights on 2013-2020 only, and
the win-% side walk-forward, as live does it: each 2021-2025 season gets the
win-% slope fit on every earlier season (live refits it every week) and a
key-number margin table built only from earlier seasons' scores (expert review
round 2: a table that includes the scored seasons flattered the hold-out by
about 0.3 pt straight up). `d.attrs["win_plan"]` holds, per season, the slope
and the last season in its margin table. `deployed(live=True)` uses the shipped
numbers instead (config.FACTORS and trends.json, fit on every season): right
for "what does the live model do", in-sample for 2021-25, never quoted as a
hold-out result.

    from nflmodel import replay
    d = replay.deployed()
    hold = d[d.season.between(2021, 2025)]
    replay.scorecard(hold)
    replay.card_summary(replay.card(hold))
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from .config import CACHE_DIR, FACTORS
from .market import devig
from .trends import (MARGIN_CANDIDATES, MAX_TOTAL_SHIFT, TRENDS_FILE, _logit,
                     calibrate, fit_logistic_slope, margin_model_for_history, win_probs)

TUNE = list(range(2013, 2021))
HOLD = list(range(2021, 2026))
ALPHAS = [1, 3, 10, 30, 100, 300, 1000, 3000]

# Factor feature (factors_2013_2025.parquet) -> its column here.
FACTOR_TERMS = {"inj_total": "fac_inj", "eff_epa": "fac_epa", "rt_rest_diff": "fac_rest"}

# The weights the 2026 Week 4-7 archive was written with (factor_inj/_epa/_rest
# are weight x feature). Later weeks record theirs in weekNN_meta.json.
ARCHIVED_WEIGHTS = dict(inj_total=0.703, eff_epa=1.191, rt_rest_diff=0.087)
ARCHIVE_COLS = {"inj_total": "factor_inj", "eff_epa": "factor_epa", "rt_rest_diff": "factor_rest"}


def load() -> pd.DataFrame:
    """Frozen projections, closing prices and factor inputs, one row per graded game."""
    base = pd.read_parquet(CACHE_DIR / "base_projections_2013_2025.parquet")
    ds = pd.read_parquet(CACHE_DIR / "dataset_2010_2025.parquet")[
        ["game_id", "home_spread_odds", "away_spread_odds", "gameday", "weekday", "div_game"]]
    fac = pd.read_parquet(CACHE_DIR / "factors_2013_2025.parquet")[["game_id", *FACTOR_TERMS]]
    d = base.merge(ds, on="game_id", how="left").merge(fac, on="game_id", how="left")
    d = d[d.result.notna() & d.spread_line.notna()]
    d = d.sort_values(["season", "week", "game_id"]).reset_index(drop=True)
    d["base"] = d.projected_margin
    return d


def trend_shift(d: pd.DataFrame, state: dict | None = None, fit: str = "disc") -> np.ndarray:
    """
    Points the confirmed margin fixes add to the home side. fit="disc" uses the
    2013-2020 fit (hold-out), "all" the live one. The subject is decided on the
    frozen projection, as in run_week.
    """
    state = state if state is not None else json.loads(TRENDS_FILE.read_text())
    joint = state.get("joint", {})
    if joint.get("status") != "confirmed" or not joint.get("keys"):
        return np.zeros(len(d))
    fns = {k: fn for k, _, fn in MARGIN_CANDIDATES}
    f = d.assign(projected_margin=d.base)
    shift = np.zeros(len(d))
    for key, beta in zip(joint["keys"], joint["beta_disc" if fit == "disc" else "beta_all"]):
        try:
            s = np.asarray(fns[key](f), dtype=float)
        except (KeyError, AttributeError) as e:
            raise RuntimeError(f"trend fix '{key}' needs game context the replay does not "
                               f"load ({e}); add it to replay.load()") from e
        shift += np.nan_to_num(s) * float(beta)
    return np.clip(shift, -MAX_TOTAL_SHIFT, MAX_TOTAL_SHIFT)


def _ridge(X, y, alpha):
    mu, sd = X.mean(0), X.std(0) + 1e-12
    Z = (X - mu) / sd
    b = np.linalg.solve(Z.T @ Z + alpha * np.eye(Z.shape[1]), Z.T @ (y - y.mean()))
    return b / sd, mu


def fit_factor_weights(d: pd.DataFrame, cols, target, seasons=TUNE) -> tuple[dict, float]:
    """
    Points per unit of each factor: ridge on the model's miss, penalty picked by
    leave-one-season-out inside `seasons`, then fit on all of `seasons`. The
    same procedure as scripts/factor_lab.py; the intercept is dropped (home
    field is already in the projection).
    """
    cols = list(cols)
    fit = d.season.isin(seasons).to_numpy()
    X = d[cols].fillna(0.0).to_numpy()
    y = np.asarray(target, dtype=float)
    best, best_a = np.inf, None
    for a in ALPHAS:
        err = 0.0
        for s in seasons:
            tr = fit & (d.season != s).to_numpy()
            te = (d.season == s).to_numpy()
            w, mu = _ridge(X[tr], y[tr], a)
            err += np.abs(y[te] - ((X[te] - mu) @ w + y[tr].mean())).sum()
        if err < best:
            best, best_a = err, a
    w, _ = _ridge(X[fit], y[fit], best_a)
    return dict(zip(cols, (float(v) for v in w))), float(best_a)


def add_factors(d: pd.DataFrame, weights: dict) -> pd.DataFrame:
    """fac_inj / fac_epa / fac_rest (points to the home side) and their sum, fac."""
    d = d.copy()
    for feat, col in FACTOR_TERMS.items():
        d[col] = float(weights.get(feat, 0.0)) * d[feat].fillna(0.0)
    d["fac"] = d[list(FACTOR_TERMS.values())].sum(axis=1)
    return d


_MARGIN_MODELS: dict = {}


def margin_model(through_season: int | None = None):
    """The key-number margin table from final scores up to `through_season` (None = every season)."""
    if through_season not in _MARGIN_MODELS:
        _MARGIN_MODELS[through_season] = margin_model_for_history(through_season)
    return _MARGIN_MODELS[through_season]


def win_pct(margins, b: float | None, mm=None) -> np.ndarray:
    """Home win % from a home margin: the margin distribution, then logit(p') = b logit(p)."""
    p = win_probs(margins, mm if mm is not None else margin_model())
    return calibrate(p, dict(a=0.0, b=b)) if b else p


def fit_win_slope(d: pd.DataFrame, margin_col: str = "proj", seasons=TUNE, mm=None) -> float:
    """The recalibration slope b, fit on `seasons` on the given margin (table: through the last of them)."""
    seasons = list(seasons)
    mm = mm if mm is not None else margin_model(max(seasons))
    m = d.season.isin(seasons).to_numpy() & (d.result != 0).to_numpy()
    p = win_probs(d.loc[m, margin_col], mm)
    return float(fit_logistic_slope(_logit(p), (d.result[m] > 0).to_numpy().astype(float)))


def win_plan(d: pd.DataFrame, margin_col: str = "proj", live: bool = False,
             state: dict | None = None) -> dict:
    """
    Per season: (win-% slope, last season in its margin table). Clean replay:
    2013-2020 share the fit on 2013-2020; each later season is fit on every
    season before it, with a table from those seasons only. Live: the shipped
    slope (trends.json) and every season's scores.
    """
    seasons = sorted(int(s) for s in d.season.unique())
    if live:
        state = state if state is not None else json.loads(TRENDS_FILE.read_text())
        cal = state.get("calibration") or {}
        b = cal.get("b") if cal.get("status") == "confirmed" else None
        return {s: (b, None) for s in seasons}
    b_tune = fit_win_slope(d, margin_col, TUNE)
    plan = {}
    for s in seasons:
        if s <= TUNE[-1]:
            plan[s] = (b_tune, TUNE[-1])
        else:
            plan[s] = (fit_win_slope(d, margin_col, range(TUNE[0], s)), s - 1)
    return plan


def apply_win_pct(d: pd.DataFrame, margins, plan: dict, recalibrate: bool = True) -> np.ndarray:
    """Home win % for every row of `d`, each season with its own slope and margin table."""
    m = np.asarray(margins, dtype=float)
    out = np.full(len(d), np.nan)
    season = d.season.to_numpy()
    for s, (b, thru) in plan.items():
        idx = season == s
        if idx.any():
            out[idx] = win_pct(m[idx], b if recalibrate else None, margin_model(thru))
    return out


def deployed(live: bool = False, factors: dict | None = None, state: dict | None = None,
             d: pd.DataFrame | None = None, trend=None) -> pd.DataFrame:
    """
    The deployed stack on every game 2013-2025.

    live=False: factor weights and win-% slope fit on 2013-2020 only (the
                factors in use are config.FACTORS's non-zero keys), trend fix
                at its 2013-2020 size. 2021-2025 is a clean test.
    live=True:  config.FACTORS and trends.json as shipped.
    factors:    override the factor weights ({} = no factors).
    trend:      override the trend fix points per game (a candidate rule).
    """
    state = state if state is not None else json.loads(TRENDS_FILE.read_text())
    d = load() if d is None else d.copy()
    d["trend"] = (trend_shift(d, state, "all" if live else "disc") if trend is None
                  else np.asarray(trend, dtype=float))
    if factors is None:
        keys = [k for k, v in FACTORS.items() if v]
        if live or not keys:
            factors = {k: FACTORS[k] for k in keys}
        else:
            factors, _ = fit_factor_weights(d, keys, d.result - (d.base + d.trend))
    d = add_factors(d, factors)
    d["proj"] = d.base + d.trend + d.fac
    plan = win_plan(d, live=live, state=state)
    d["wp"] = apply_win_pct(d, d.proj, plan)
    b = plan[min(plan)][0]
    d.attrs.update(factor_weights=factors, win_slope=b, win_plan=plan, live=live)
    return d


# ── scoring ─────────────────────────────────────────────────────────────

def _paired(a, b):
    x = np.asarray(a, float) - np.asarray(b, float)
    se = x.std(ddof=1) / np.sqrt(len(x)) if len(x) > 1 else np.nan
    return float(x.mean()), float(se), float(x.mean() / se) if se and se > 0 else float("nan")


def market_wp(d: pd.DataFrame) -> np.ndarray:
    """The market's home win %: the closing moneylines de-vigged (NaN where missing)."""
    out = np.full(len(d), np.nan)
    for i, (h, a) in enumerate(zip(d.home_moneyline, d.away_moneyline)):
        if pd.notna(h) and pd.notna(a):
            out[i] = devig(float(h), float(a))[0]
    return out


def scorecard(d: pd.DataFrame, wp_col: str = "wp", margin_col: str = "proj") -> dict:
    """
    Straight-up picks against the closing favorite, margin error against the
    line, and win % against the de-vigged closing moneyline, on the same games.
    """
    res = d.result.to_numpy(float)
    line = d.spread_line.to_numpy(float)
    wp = d[wp_col].to_numpy(float)
    decided = res != 0
    pick_home = wp >= 0.5
    model_right = (pick_home == (res > 0)).astype(float)
    # The favorite: the closing spread, or the moneyline on a pick'em.
    mkt = market_wp(d)
    fav_home = np.where(line != 0, line > 0, np.nan_to_num(mkt, nan=0.5) >= 0.5)
    fav_right = (fav_home == (res > 0)).astype(float)
    disagree = (pick_home != fav_home) & decided
    diff, se, t = _paired(model_right[decided], fav_right[decided])

    y = (res > 0).astype(float)
    ok = decided & ~np.isnan(mkt)
    p = np.clip(wp, 1e-6, 1 - 1e-6)
    q = np.clip(mkt, 1e-6, 1 - 1e-6)
    ll = lambda v: -(y[ok] * np.log(v) + (1 - y[ok]) * np.log(1 - v))
    slope = fit_logistic_slope(_logit(wp[decided]), y[decided])
    pick_p = np.where(pick_home, wp, 1 - wp)
    pick_mkt = np.where(pick_home, mkt, 1 - mkt)
    err_m = np.abs(res - d[margin_col].to_numpy(float))
    err_l = np.abs(res - line)
    dm, sem, tm = _paired(err_m, err_l)
    return dict(
        games=int(len(d)), decided=int(decided.sum()),
        su_model=float(model_right[decided].mean()), su_favorite=float(fav_right[decided].mean()),
        su_diff=diff, su_diff_se=se, su_diff_t=t,
        wins_model=int(model_right[decided].sum()), wins_favorite=int(fav_right[decided].sum()),
        disagree=int(disagree.sum()), disagree_won=int(model_right[disagree].sum()),
        expected_wins_model=float(pick_p[decided].sum()),
        expected_wins_market=float(np.nansum(pick_mkt[decided])),
        mae_model=float(err_m.mean()), mae_line=float(err_l.mean()), mae_diff_t=tm,
        brier_model=float(((wp[ok] - y[ok]) ** 2).mean()),
        brier_market=float(((mkt[ok] - y[ok]) ** 2).mean()),
        logloss_model=float(ll(p[ok]).mean()), logloss_market=float(ll(q[ok]).mean()),
        calibration_slope=float(slope),
    )


def calibration_table(d: pd.DataFrame, wp_col: str = "wp",
                      bins=(0.5, 0.55, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.01)) -> pd.DataFrame:
    """
    What the model said for its pick vs how often the pick won, in 5-pt bands
    from 50%, with the count and how many standard errors off each band is.
    """
    x = d[d.result != 0]
    p = np.maximum(x[wp_col], 1 - x[wp_col])
    won = np.where(x[wp_col] >= 0.5, x.result > 0, x.result < 0)
    t = pd.DataFrame(dict(said=p, won=won.astype(float)))
    t["band"] = pd.cut(t.said, list(bins), right=False)
    out = t.groupby("band", observed=True).agg(n=("won", "size"), said=("said", "mean"),
                                               won=("won", "mean")).reset_index()
    out["off"] = out.won - out.said
    out["z"] = out.off / np.sqrt(out.said * (1 - out.said) / out.n)
    return out


def _payout(odds):
    return odds / 100.0 if odds > 0 else 100.0 / abs(odds)


def card(d: pd.DataFrame, wp_col: str = "wp", margin_col: str = "proj", model=None) -> pd.DataFrame:
    """
    The weekly card, replayed at closing numbers and prices with the live rules
    themselves (NFLModel._recommend and _weekly_card, config.THRESHOLDS and
    config.STAKING): which bets qualify, the top card_max by chance to win,
    topped up to card_min with labeled filler. One row per bet, settled.
    """
    from .model import NFLModel
    mdl = model or NFLModel()
    plan = d.attrs.get("win_plan") or {}
    out = []
    for (season, week), wk in d.groupby(["season", "week"], sort=True):
        mm = margin_model(plan[season][1] if season in plan else None)
        rows = []
        for _, g in wk.iterrows():
            proj, line, hwp = float(g[margin_col]), float(g.spread_line), float(g[wp_col])
            ph, pp, pa = mm.cover_prob(proj, line)
            hml, aml = g.home_moneyline, g.away_moneyline
            if pd.notna(hml) and pd.notna(aml):
                fh, fa = devig(float(hml), float(aml))
                eh, ea = hwp - fh, (1 - hwp) - fa
            else:
                hml = aml = None
                eh = ea = np.nan
            rec = mdl._recommend(proj, line, proj - line, ph, pp, pa, hwp, hml, aml, eh, ea,
                                 g.home_team, g.away_team, g.home_spread_odds, g.away_spread_odds)
            rows.append(dict(game_id=g.game_id, home_team=g.home_team, away_team=g.away_team,
                             home_win_prob=hwp, spread_line=line, projected_margin=proj,
                             spread_edge_pts=proj - line, home_cover_prob=ph,
                             away_cover_prob=pa, push_prob=pp, home_ml=hml, away_ml=aml,
                             ml_edge_home=eh, ml_edge_away=ea, bet_type="", bet_why="",
                             result=g.result, **rec))
        slate = mdl._weekly_card(pd.DataFrame(rows), wk[["game_id", "home_spread_odds",
                                                          "away_spread_odds"]])
        for _, r in slate[slate.bet_side != ""].iterrows():
            home = r.bet_side.split()[0] == r.home_team
            team_margin = r.result if home else -r.result
            if r.bet_market == "SPREAD":
                team_margin += r.spread_line * (-1 if home else 1)
            units = _payout(float(r.bet_odds)) if team_margin > 0 else (0.0 if team_margin == 0 else -1.0)
            out.append(dict(season=season, week=week, game_id=r.game_id, market=r.bet_market,
                            side=r.bet_side, home=home, odds=float(r.bet_odds),
                            chance=float(r.bet_chance), filler=r.card == "filler",
                            edge=(abs(r.spread_edge_pts) if r.bet_market == "SPREAD"
                                  else 100 * (r.ml_edge_home if home else r.ml_edge_away)),
                            out="W" if units > 0 else ("P" if units == 0 else "L"), units=units))
    return pd.DataFrame(out)


def card_summary(bets: pd.DataFrame) -> dict:
    """Record, ROI with its standard error, and what the model expected."""
    if bets.empty:
        return dict(n=0)
    dec = bets[bets.out != "P"]
    be = np.mean([(-o / (-o + 100)) if o < 0 else (100 / (o + 100)) for o in dec.odds]) if len(dec) else np.nan
    roi = bets.units.mean()
    se = bets.units.std(ddof=1) / np.sqrt(len(bets)) if len(bets) > 1 else np.nan
    return dict(n=int(len(bets)), won=int((bets.out == "W").sum()), lost=int((bets.out == "L").sum()),
                push=int((bets.out == "P").sum()), win_pct=float((dec.out == "W").mean()),
                break_even=float(be), expected_win_pct=float(bets.chance.mean()),
                roi=float(roi), roi_se=float(se))


# ── this season's published games ───────────────────────────────────────

def archived_factor_inputs(season: int, schedule: pd.DataFrame) -> pd.DataFrame:
    """
    The factor inputs behind this season's published picks, one row per game:
    each archived factor_* point value divided by the weight it was written
    with (weekNN_meta.json "factor_weights"; ARCHIVED_WEIGHTS before that was
    recorded). Weeks published without factors are left out.
    """
    from .archive import week_dir
    d = week_dir(season)
    played = schedule[(schedule.season == season) & schedule.result.notna()]
    rows = []
    for f in sorted(d.glob("week*_picks.csv")):
        wk = int(f.stem[4:6])
        pk = pd.read_csv(f)
        if "factor_adj" not in pk.columns:
            continue
        meta = d / f"week{wk:02d}_meta.json"
        used = ARCHIVED_WEIGHTS
        if meta.exists():
            used = json.loads(meta.read_text()).get("factor_weights", ARCHIVED_WEIGHTS)
        for _, r in pk.iterrows():
            away, home = [x.strip() for x in str(r.matchup).split("@")]
            g = played[(played.week == wk) & (played.home_team == home) & (played.away_team == away)]
            if g.empty:
                continue
            row = dict(game_id=g.game_id.iloc[0])
            for feat, col in ARCHIVE_COLS.items():
                w = float(used.get(feat, 0.0) or 0.0)
                v = r.get(col)
                row[feat] = float(v) / w if w and pd.notna(v) else 0.0
            rows.append(row)
    cols = ["game_id", *FACTOR_TERMS]
    return pd.DataFrame(rows, columns=cols).drop_duplicates("game_id", keep="last")


def history_factor_points(h: pd.DataFrame, season: int | None = None,
                          schedule: pd.DataFrame | None = None,
                          weights: dict | None = None) -> np.ndarray:
    """
    Points the live game factors add to the home side for every game in a
    trend-check history (trends.build_history): the 2013-2025 factor cache for
    backtest games, the archive for this season's published ones.
    """
    weights = FACTORS if weights is None else weights
    fac = pd.read_parquet(CACHE_DIR / "factors_2013_2025.parquet")[["game_id", *FACTOR_TERMS]]
    if season is not None and schedule is not None:
        cur = archived_factor_inputs(season, schedule)
        fac = pd.concat([fac[~fac.game_id.isin(cur.game_id)], cur], ignore_index=True)
    x = h[["game_id"]].merge(fac, on="game_id", how="left")
    pts = np.zeros(len(x))
    for feat in FACTOR_TERMS:
        pts += float(weights.get(feat, 0.0) or 0.0) * x[feat].fillna(0.0).to_numpy()
    return pts
