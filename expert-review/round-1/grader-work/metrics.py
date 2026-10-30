"""Shared metric helpers for the grader's hold-out analysis."""
import numpy as np, pandas as pd


def imp(ml):
    ml = np.asarray(ml, dtype=float)
    return np.where(ml < 0, -ml / (-ml + 100), 100 / (ml + 100))


def devig_home(hml, aml):
    ph, pa = imp(hml), imp(aml)
    return ph / (ph + pa)


def payout(ml):
    ml = np.asarray(ml, dtype=float)
    return np.where(ml < 0, 100 / -ml, ml / 100)


def logit(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def fit_logistic(x, y, iters=100):
    a, b = 0.0, 1.0
    for _ in range(iters):
        z = np.clip(a + b * x, -30, 30)
        p = 1 / (1 + np.exp(-z)); w = p * (1 - p)
        g = np.array([(y - p).sum(), ((y - p) * x).sum()])
        h = np.array([[w.sum(), (w * x).sum()], [(w * x).sum(), (w * x * x).sum()]])
        step = np.linalg.solve(h + 1e-12 * np.eye(2), g)
        a, b = a + step[0], b + step[1]
        if np.abs(step).max() < 1e-10:
            break
    z = np.clip(a + b * x, -30, 30); p = 1 / (1 + np.exp(-z)); w = p * (1 - p)
    h = np.array([[w.sum(), (w * x).sum()], [(w * x).sum(), (w * x * x).sum()]])
    se = np.sqrt(np.diag(np.linalg.inv(h)))
    return a, b, se


def paired(a, b):
    """mean(a-b), se, t"""
    d = np.asarray(a, float) - np.asarray(b, float)
    se = d.std(ddof=1) / np.sqrt(len(d))
    return d.mean(), se, d.mean() / se if se > 0 else np.nan


def su_vs_fav(home_wp, line, result):
    """Same-games SU: excludes pick'em lines and ties. Returns dict."""
    home_wp, line, result = map(lambda x: np.asarray(x, float), (home_wp, line, result))
    ok = (line != 0) & (result != 0)
    pick_home = home_wp >= 0.5
    fav_home = line > 0
    home_won = result > 0
    mc = (pick_home == home_won)[ok].astype(float)
    fc = (fav_home == home_won)[ok].astype(float)
    dis = (pick_home != fav_home)[ok]
    diff, se, t = paired(mc, fc)
    return dict(n=int(ok.sum()), n_excl_pk=int((line == 0).sum()), n_excl_tie=int((result == 0).sum()),
                model=mc.mean(), fav=fc.mean(), diff=diff, se=se, t=t,
                n_dis=int(dis.sum()), dis_hit=mc[dis].mean() if dis.any() else np.nan,
                wins_model=int(mc.sum()), wins_fav=int(fc.sum()))
