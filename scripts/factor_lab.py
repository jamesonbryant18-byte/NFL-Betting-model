"""
factor_lab.py — does adding a factor to the model make it better?

Jameson, 2026-09-28: the model decides games on home/away, team rating and
QB rating. What is it MISSING? Test efficiency, matchups, weather,
rest/travel, non-QB injuries and coaching/situation as real inputs, and judge
them on BOTH jobs the model does:

  1. pick the winner of every game          (straight-up %, margin error)
  2. find bets where its win % beats the odds (ATS and moneyline vs FanDuel-
     style closing prices, and whether it knows anything the line doesn't)

Method, the same for every family:
  * start from the frozen model's walk-forward projection (each game
    projected from games before it only; cache from build_base_projections)
  * fit a ridge correction  result - projection ~ factors  on 2013-2020,
    penalty picked by leave-one-season-out inside 2013-2020
  * score it on 2021-2025, which the fit never saw

A family is a CANDIDATE only if on 2021-2025 it lowers margin error, does
not lower straight-up %, and helps in at least 3 of the 5 seasons. Being a
candidate does not change the live model; that is Jameson's call.

    .venv/bin/python -W ignore scripts/factor_lab.py            # all families
    .venv/bin/python -W ignore scripts/factor_lab.py --rebuild  # rebuild factors
"""
import argparse
import sys

sys.path.insert(0, "src")
import numpy as np
import pandas as pd
from scipy.stats import norm, t as tdist

from nflmodel.config import CACHE_DIR
from nflmodel.factors import FAMILIES, build_game_factors

TUNE = list(range(2013, 2021))
HOLD = list(range(2021, 2026))
SIGMA = 13.2
ALPHAS = [1, 3, 10, 30, 100, 300, 1000, 3000]

ap = argparse.ArgumentParser()
ap.add_argument("--rebuild", action="store_true")
args = ap.parse_args()

fpath = CACHE_DIR / "factors_2013_2025.parquet"
if args.rebuild or not fpath.exists():
    games = pd.read_parquet(CACHE_DIR / "dataset_2010_2025.parquet")
    build_game_factors(games, range(2013, 2026)).to_parquet(fpath, index=False)

base = pd.read_parquet(CACHE_DIR / "base_projections_2013_2025.parquet")
fac = pd.read_parquet(fpath)
d = base.merge(fac.drop(columns=["season", "week", "home_team", "away_team"]),
               on="game_id", how="inner")
odds = pd.read_parquet(CACHE_DIR / "dataset_2010_2025.parquet")[
    ["game_id", "home_spread_odds", "away_spread_odds"]]
d = d.merge(odds, on="game_id", how="left")
d = d[d.result.notna() & d.spread_line.notna()].reset_index(drop=True)
m = d.projected_margin
home = (~d.neutral.astype(bool)).astype(float)

# Condition flags that apply to BOTH teams can't favor a side on their own.
# They can (a) shrink or stretch the expected margin, or (b) change home field.
EXTRA = {
    "weather": {"wx_wind_x_m": d.wx_wind * m / 10, "wx_precip_x_m": d.wx_precip * m,
                "wx_cold_x_m": d.wx_cold * m, "wx_bad_x_home": d._wx_bad * home},
    "situation": {"sit_div_x_m": d.sit_div * m, "sit_prime_x_m": d.sit_prime * m,
                  "sit_playoff_x_m": d.sit_playoff * m,
                  "sit_div_x_home": d.sit_div * home, "sit_prime_x_home": d.sit_prime * home},
}
for fam, cols in EXTRA.items():
    for k, v in cols.items():
        d[k] = v
FAMS = {f: list(c) + list(EXTRA.get(f, {})) for f, c in FAMILIES.items()}

tune = d.season.isin(TUNE).to_numpy()
hold = d.season.isin(HOLD).to_numpy()


def ridge_fit(X, y, alpha):
    mu, sd = X.mean(0), X.std(0) + 1e-12
    Z = (X - mu) / sd
    b = np.linalg.solve(Z.T @ Z + alpha * np.eye(Z.shape[1]), Z.T @ (y - y.mean()))
    return lambda Xn: ((Xn - mu) / sd) @ b + y.mean(), b / sd


def fit_family(cols, target):
    """Ridge on 2013-20, penalty by leave-one-season-out; returns hold-out adj."""
    X = d[cols].fillna(0.0).to_numpy()
    y = target.to_numpy()
    best, best_a = np.inf, None
    for a in ALPHAS:
        err = 0.0
        for s in TUNE:
            tr = tune & (d.season != s).to_numpy()
            te = (d.season == s).to_numpy()
            f, _ = ridge_fit(X[tr], y[tr], a)
            err += np.abs(y[te] - f(X[te])).sum()
        if err < best:
            best, best_a = err, a
    f, coef = ridge_fit(X[tune], y[tune], best_a)
    # Intercept is dropped: home field is already in the projection, and a
    # tuning-era intercept would just be 2013-20's average miss.
    adj = f(X) - y[tune].mean()
    return adj, best_a, dict(zip(cols, coef))


def devig(h_ml, a_ml):
    def imp(x):
        return np.where(x < 0, -x / (-x + 100), 100 / (x + 100))
    ph, pa = imp(h_ml), imp(a_ml)
    return ph / (ph + pa)


def payout(ml):
    return np.where(ml < 0, 100 / -ml, ml / 100)


def score(proj, mask):
    x = d[mask]
    p = proj[mask]
    res = x.result.to_numpy()
    nz = res != 0
    out = {}
    out["mae"] = np.abs(res - p).mean()
    out["su"] = (np.sign(p[nz]) == np.sign(res[nz])).mean()
    ph = np.clip(norm.cdf(p / SIGMA), 1e-4, 1 - 1e-4)
    win = (res > 0).astype(float)
    out["logloss"] = -np.mean(np.where(nz, win * np.log(ph) + (1 - win) * np.log(1 - ph), 0))
    # ATS at the live 1.5-pt threshold, real juice where present.
    line = x.spread_line.to_numpy()
    edge = p - line
    bet = np.abs(edge) >= 1.5
    home_side = edge > 0
    cover = np.where(home_side, res > line, res < line)
    push = res == line
    juice = np.where(home_side, x.get("home_spread_odds", pd.Series(-110, index=x.index)).fillna(-110),
                     x.get("away_spread_odds", pd.Series(-110, index=x.index)).fillna(-110))
    g = bet & ~push
    out["ats_n"] = int(g.sum())
    out["ats"] = cover[g].mean() if g.any() else np.nan
    out["ats_roi"] = (np.where(cover[g], payout(juice[g]), -1.0)).mean() if g.any() else np.nan
    # Moneyline at the live 3% edge vs de-vigged price, +250 dog cap.
    hm, am = x.home_moneyline.to_numpy(), x.away_moneyline.to_numpy()
    ok = ~np.isnan(hm) & ~np.isnan(am)
    fair = devig(hm, am)
    eh, ea = ph - fair, (1 - ph) - (1 - fair)
    take_h = ok & (eh >= 0.03) & (hm <= 250)
    take_a = ok & (ea >= 0.03) & (am <= 250) & ~take_h
    pnl = np.concatenate([np.where(res[take_h] > 0, payout(hm[take_h]), np.where(res[take_h] == 0, 0, -1.0)),
                          np.where(res[take_a] < 0, payout(am[take_a]), np.where(res[take_a] == 0, 0, -1.0))])
    out["ml_n"] = len(pnl)
    out["ml_roi"] = pnl.mean() if len(pnl) else np.nan
    return out


def per_season_gain(proj0, proj1):
    wins, rows = 0, []
    for s in HOLD:
        k = (d.season == s).to_numpy()
        e0 = np.abs(d.result[k] - proj0[k]).mean()
        e1 = np.abs(d.result[k] - proj1[k]).mean()
        rows.append(e0 - e1)
        wins += e1 < e0
    return wins, rows


def paired_t(proj0, proj1, mask):
    diff = (np.abs(d.result - proj0) - np.abs(d.result - proj1))[mask]
    return diff.mean() / (diff.std(ddof=1) / np.sqrt(len(diff)))


def beats_line(cols):
    """Pure betting test: can the factors predict where the LINE is wrong?"""
    adj, a, _ = fit_family(cols, d.result - d.spread_line)
    x = d[hold]
    miss = (x.result - x.spread_line).to_numpy()
    pred = adj[hold]
    r = np.corrcoef(pred, miss)[0, 1]
    tstat = r * np.sqrt((len(miss) - 2) / (1 - r * r))
    blended = np.abs(miss - pred).mean() - np.abs(miss).mean()   # <0 = line+factors beats line
    return r, tstat, blended, a


p0 = m.to_numpy()
B = {"tune": score(p0, tune), "hold": score(p0, hold)}
line_mae = np.abs(d.result - d.spread_line)[hold].mean()
print("=" * 96)
print(f"  FACTOR LAB — fit on {TUNE[0]}-{TUNE[-1]} ({tune.sum()} games), "
      f"scored on {HOLD[0]}-{HOLD[-1]} ({hold.sum()} games, never seen)")
print("=" * 96)
print(f"  current model on 2021-25: straight-up {B['hold']['su']:.1%}, margin error "
      f"{B['hold']['mae']:.3f} pts (closing line {line_mae:.3f}), ATS {B['hold']['ats']:.1%} "
      f"on {B['hold']['ats_n']}, ML ROI {B['hold']['ml_roi']:+.1%} on {B['hold']['ml_n']}")
print()
hdr = (f"  {'family':<12}{'SU%':>7}{'Δ SU':>7}{'error':>8}{'Δ err':>8}{'t':>6}{'yrs':>5}"
       f"{'ATS%':>7}{'ATS ROI':>8}{'ML ROI':>8}{' | vs LINE r':>12}{'t':>6}  verdict")
print(hdr)
print("  " + "-" * (len(hdr) - 2))

results = {}
for fam, cols in list(FAMS.items()) + [("ALL", [c for cs in FAMS.values() for c in cs])]:
    adj, alpha, coef = fit_family(cols, d.result - m)
    p1 = p0 + adj
    H = score(p1, hold)
    wins, gains = per_season_gain(p0, p1)
    t = paired_t(p0, p1, hold)
    r, tl, blend, _ = beats_line(cols)
    dsu = H["su"] - B["hold"]["su"]
    derr = B["hold"]["mae"] - H["mae"]        # positive = better
    cand = derr > 0 and dsu >= 0 and wins >= 3
    verdict = "CANDIDATE" if cand else ("no help" if derr <= 0 else "mixed")
    results[fam] = dict(adj=adj, coef=coef, alpha=alpha, H=H, wins=wins, gains=gains,
                        t=t, r=r, tl=tl, cand=cand)
    print(f"  {fam:<12}{H['su']:>7.1%}{dsu*100:>+6.1f}{H['mae']:>8.3f}{derr:>+8.3f}{t:>6.1f}"
          f"{wins:>3}/5{H['ats']:>7.1%}{H['ats_roi']:>+8.1%}{H['ml_roi']:>+8.1%}"
          f"{r:>+12.3f}{tl:>6.1f}  {verdict}")

print()
print("  Δ SU / Δ err: change vs the current model on 2021-25 (Δ err > 0 = smaller misses).")
print("  t: paired t on per-game error. yrs: hold-out seasons improved.")
print("  vs LINE: factors fit to predict where the closing line missed; r and t on 2021-25.")
print("  |t| < 2 on that column means the line already prices it.")
print()
for fam, R in results.items():
    if fam == "ALL":
        continue
    top = sorted(R["coef"].items(), key=lambda kv: -abs(kv[1]))[:4]
    print(f"  {fam:<12} penalty {R['alpha']:<5} per-season gain "
          + " ".join(f"{g:+.3f}" for g in R["gains"])
          + "   top: " + ", ".join(f"{k} {v:+.2f}" for k, v in top))
