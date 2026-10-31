"""
build_structural_bases.py — the frozen walk-forward projection with one
structural piece changed, for the ablation (expert review round 2, fixes 7
and 8a). Adapted from the round-2 grader's ablate_structural.py.

Per graded game 2013-2025, each week fit on earlier games only, exactly as
build_base_projections.py does:

  full       the deployed base (checked against the cache: must match)
  noprior    no market prior blend
  noqb       team-only ratings (no joint QB fit), same market prior blend
  hfa        the home field the deployed base used (base - hfa = no home field)
  qbprior    the market prior backed out of lines with each game's QB values
             (the model's own, fit through that week) taken out first: the
             prior is backed out of spreads with no QB term, so it already
             holds each team's usual QB, and the model adds the QB on top
             (flagged 2026-10-14)

    .venv/bin/python -W ignore scripts/build_structural_bases.py   # ~5 min

Writes data/cache/structural_bases_2013_2025.parquet; scripts/ablation.py
reads it.
"""
import json
import sys
import time

sys.path.insert(0, "src")
from dataclasses import replace

import numpy as np
import pandas as pd

from nflmodel.config import CACHE_DIR, RATINGS
from nflmodel.ratings import (blend_with_prior, fit_market_ratings, fit_ratings,
                              fit_ratings_qb, qb_value)

OUT = CACHE_DIR / "structural_bases_2013_2025.parquet"

df = pd.read_parquet(CACHE_DIR / "dataset_2010_2025.parquet") \
       .sort_values(["season", "week"]).reset_index(drop=True)
best = json.loads((CACHE_DIR / "tuning_results.json").read_text())[0]
params = replace(RATINGS, **{k: v for k, v in best.items() if k in RATINGS.__dataclass_fields__})
qbl = best["qb_lambda"]


def blend(team, hfa, market, market_hfa, gp):
    """NFLModel.fit's market prior blend."""
    if not any(abs(v) > 1e-9 for v in market.values()):
        return team, hfa
    w = params.prior_decay_games / (params.prior_decay_games + max(gp, 0.0)) \
        * params.market_prior_weight
    return blend_with_prior(team, market, gp, params), (1 - w) * hfa + w * market_hfa


rows = []
t0 = time.time()
for season in range(2013, 2026):
    for week in sorted(df.loc[df.season == season, "week"].unique()):
        slate = df[(df.season == season) & (df.week == week) & df.played & df.spread_line.notna()]
        if slate.empty:
            continue
        team, qbs, hfa = fit_ratings_qb(df, season, week, params, qb_lambda=qbl)
        gp = len(df[(df.season == season) & (df.week < week) & df.played]) / 16.0
        mk, mhfa = fit_market_ratings(df, season, params, asof_week=week)
        team_f, hfa_f = blend(team, hfa, mk, mhfa, gp)

        tonly, hfa_t = fit_ratings(df, season, week, params)
        tonly, hfa_t = blend(tonly, hfa_t, mk, mhfa, gp)

        lines = df[df.season == season].copy()
        lines["spread_line"] = lines.spread_line - np.array(
            [qb_value(qbs, h) - qb_value(qbs, a)
             for h, a in zip(lines.home_qb_name, lines.away_qb_name)])
        mk_q, mhfa_q = fit_market_ratings(lines, season, params, asof_week=week)
        team_q, hfa_q = blend(team, hfa, mk_q, mhfa_q, gp)

        for _, g in slate.iterrows():
            home = 0.0 if bool(g.neutral) else 1.0
            qh, qa = qb_value(qbs, g.home_qb_name), qb_value(qbs, g.away_qb_name)
            rows.append(dict(
                game_id=g.game_id,
                full=team_f.get(g.home_team, 0) + qh - team_f.get(g.away_team, 0) - qa + home * hfa_f,
                noprior=team.get(g.home_team, 0) + qh - team.get(g.away_team, 0) - qa + home * hfa,
                noqb=tonly.get(g.home_team, 0) - tonly.get(g.away_team, 0) + home * hfa_t,
                hfa=home * hfa_f,
                qbprior=team_q.get(g.home_team, 0) + qh - team_q.get(g.away_team, 0) - qa
                + home * hfa_q))
    print(season, f"{time.time() - t0:.0f}s", flush=True)

out = pd.DataFrame(rows)
cache = pd.read_parquet(CACHE_DIR / "base_projections_2013_2025.parquet")[["game_id", "projected_margin"]]
x = cache.merge(out, on="game_id")
gap = float(np.abs(x.full - x.projected_margin).max())
print(f"full vs the deployed cache: max |diff| {gap:.2e} on {len(x)} games")
assert gap < 1e-6, "the rebuild does not reproduce the deployed base"
out.to_parquet(OUT, index=False)
print("saved", OUT)
