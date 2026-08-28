"""
backtest.py — walk-forward validation.

The discipline that makes this meaningful: to predict week W of season S, the
model may only see games that finished strictly before week W of season S. It
is refit from scratch at every step. No parameter, rating, or residual is ever
informed by a game the model is being scored on.

That is the difference between a backtest and a story. It is also why the
numbers this produces will look much less impressive than the ones you see
advertised -- those are almost always fit and scored on the same data.

The benchmark that matters is not "did we win more than half our bets", it is
"did our projected margin predict the result better than the closing line
did". The closing line is the single hardest number in sports to beat. If we
do not beat it, we have no edge, and the honest move is to say so.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import RATINGS, RatingsParams, HFA_BASE
from .data import TEAMS
from .market import MarginModel, american_to_prob, devig
from .ratings import fit_ratings, build_target, _time_index


def walk_forward(
    df: pd.DataFrame,
    test_seasons: list[int],
    params: RatingsParams = RATINGS,
    adjust_fn=None,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Refit and predict week by week. Returns one row per game with the model's
    out-of-sample projection alongside the market's number.
    """
    rows = []
    df = df.sort_values(["season", "week"]).reset_index(drop=True)

    for season in test_seasons:
        weeks = sorted(df.loc[df["season"] == season, "week"].unique())

        for week in weeks:
            slate = df[
                (df["season"] == season)
                & (df["week"] == week)
                & df["played"]
                & df["spread_line"].notna()
            ]
            if slate.empty:
                continue

            # Strictly-prior fit. This is the leak-free boundary.
            ratings, hfa = fit_ratings(df, season, week, params)

            for _, g in slate.iterrows():
                home_r = ratings.get(g["home_team"], 0.0)
                away_r = ratings.get(g["away_team"], 0.0)
                hfa_applied = 0.0 if g["neutral"] else hfa

                projected = home_r - away_r + hfa_applied

                adj = 0.0
                if adjust_fn is not None:
                    adj = adjust_fn(g, ratings)
                    projected += adj

                rows.append({
                    "game_id": g["game_id"],
                    "season": season,
                    "week": week,
                    "home_team": g["home_team"],
                    "away_team": g["away_team"],
                    "projected_margin": projected,
                    "adjustment": adj,
                    "spread_line": g["spread_line"],
                    "result": g["result"],
                    "home_moneyline": g["home_moneyline"],
                    "away_moneyline": g["away_moneyline"],
                    "neutral": g["neutral"],
                    "hfa_used": hfa_applied,
                })

        if verbose:
            print(f"  {season} done", flush=True)

    return pd.DataFrame(rows)


def evaluate(bt: pd.DataFrame, edge_thresholds=(0.0, 1.0, 1.5, 2.0, 3.0, 4.0)) -> dict:
    """
    Score a walk-forward run.

    'edge' is how many points the model disagrees with the line by. Positive
    means the model likes the home side.
    """
    bt = bt.copy()
    bt["edge"] = bt["projected_margin"] - bt["spread_line"]
    bt["model_err"] = bt["result"] - bt["projected_margin"]
    bt["market_err"] = bt["result"] - bt["spread_line"]

    # Which side does the model want, and did it cover?
    bt["bet_home"] = bt["edge"] > 0
    bt["push"] = bt["result"] == bt["spread_line"]
    bt["home_covered"] = bt["result"] > bt["spread_line"]
    bt["bet_won"] = np.where(bt["bet_home"], bt["home_covered"], ~bt["home_covered"])
    bt.loc[bt["push"], "bet_won"] = np.nan

    out = {
        "n_games": len(bt),
        "model_mae": float(bt["model_err"].abs().mean()),
        "market_mae": float(bt["market_err"].abs().mean()),
        "model_rmse": float(np.sqrt((bt["model_err"] ** 2).mean())),
        "market_rmse": float(np.sqrt((bt["market_err"] ** 2).mean())),
        "residual_sd": float(bt["model_err"].std()),
        "corr_with_market": float(bt["projected_margin"].corr(bt["spread_line"])),
        "mean_abs_edge": float(bt["edge"].abs().mean()),
        "by_threshold": [],
    }

    for t in edge_thresholds:
        sel = bt[(bt["edge"].abs() >= t) & bt["bet_won"].notna()]
        if len(sel) == 0:
            continue
        wins = int(sel["bet_won"].sum())
        n = len(sel)
        wr = wins / n
        # -110 flat betting: win 0.909 units, lose 1.
        roi = (wins * (100 / 110) - (n - wins)) / n
        # Standard error on the win rate, for judging whether wr is real.
        se = np.sqrt(0.25 / n)
        out["by_threshold"].append({
            "min_edge_pts": t,
            "n_bets": n,
            "wins": wins,
            "win_rate": wr,
            "roi_at_110": roi,
            "z_vs_breakeven": (wr - 0.5238) / se,
        })

    return out


def print_report(res: dict, label: str = "") -> None:
    print()
    print("=" * 72)
    print(f"  WALK-FORWARD BACKTEST{('  —  ' + label) if label else ''}")
    print("=" * 72)
    print(f"  Games scored:            {res['n_games']:,}")
    print()
    print("  PREDICTIVE ACCURACY  (lower is better)")
    print(f"    Model  MAE / RMSE:     {res['model_mae']:.3f}  /  {res['model_rmse']:.3f}")
    print(f"    Market MAE / RMSE:     {res['market_mae']:.3f}  /  {res['market_rmse']:.3f}")
    delta = res["market_mae"] - res["model_mae"]
    verdict = "MODEL BEATS MARKET" if delta > 0 else "market beats model"
    print(f"    Difference:            {delta:+.3f} pts  <-- {verdict}")
    print()
    print(f"    Model residual SD:     {res['residual_sd']:.2f}")
    print(f"    Corr(model, line):     {res['corr_with_market']:.3f}")
    print(f"    Mean |disagreement|:   {res['mean_abs_edge']:.2f} pts")
    print()
    print("  AGAINST THE SPREAD  (break-even at -110 is 52.38%)")
    print(f"    {'min edge':>9} {'bets':>7} {'wins':>7} {'win%':>8} {'ROI':>8} {'z':>7}")
    for r in res["by_threshold"]:
        flag = "  *" if r["z_vs_breakeven"] > 1.65 else ""
        print(f"    {r['min_edge_pts']:>7.1f}p {r['n_bets']:>7,} {r['wins']:>7,} "
              f"{r['win_rate']*100:>7.2f}% {r['roi_at_110']*100:>7.2f}% "
              f"{r['z_vs_breakeven']:>7.2f}{flag}")
    print("=" * 72)
