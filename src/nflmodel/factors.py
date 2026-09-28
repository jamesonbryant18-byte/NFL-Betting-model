"""
factors.py — candidate game factors beyond team rating, QB and home field.

Built 2026-09-28 at Jameson's request: "look into the core part of the model"
and find what it is missing. Six families, each a set of per-game numbers
known BEFORE kickoff:

  efficiency   offense/defense per play: EPA, success, explosives, points per
               drive, red-zone TDs, pass vs run, sacks and pressure
  matchup      one side's strength against the other's (pass offense vs pass
               defense, pass rush vs protection, run vs run defense)
  weather      wind, cold, rain/snow, and how pass-heavy each team is in it
  rest_travel  rest days, byes, short weeks, time zones, miles, body clock
  injuries     non-QB starters out, by position group
  situation    division, prime time, coaching record/tenure, late-season stakes

Nothing here touches the live model. scripts/factor_lab.py measures each
family on seasons it never saw; only a family that helps there is a candidate
for the core model.

No-leak rule: a team's number for week W uses only its games before W this
season, plus last season shrunk toward league average. Opponent adjustment
uses the opponent's numbers as they stood BEFORE that earlier game.
"""
from __future__ import annotations

import math
import re

import numpy as np
import pandas as pd

from .config import CACHE_DIR
from .data import TEAM_TZ_OFFSET, _normalize_team

WIDE_DIR = CACHE_DIR / "pbp_wide"

# Offensive stats per team-game. The defense's version is the opponent's
# offense in the same game.
STATS = ["epa", "sr", "pass_epa", "rush_epa", "expl", "sack", "press",
         "ppd", "rz_td"]
STYLE = ["pass_rate"]          # not opponent-adjusted: it is a choice, not a skill

PRIOR_GAMES = 6.0              # last season counts as this many games
PRIOR_KEEP = 0.6               # and is regressed 40% to league average


# ---------------------------------------------------------------- efficiency

def _team_games(season: int) -> pd.DataFrame:
    """One row per team per game with that team's OFFENSIVE numbers."""
    p = pd.read_parquet(WIDE_DIR / f"pbp_wide_{season}.parquet")
    for c in ("posteam", "defteam", "home_team", "away_team"):
        p[c] = _normalize_team(p[c])

    plays = p[p.play_type.isin(["pass", "run"]) & p.epa.notna()
              & p.posteam.notna()].copy()
    # Garbage time says little about the next game.
    plays = plays[plays.wp.between(0.05, 0.95)]
    db = plays.qb_dropback == 1
    plays["is_db"] = db.astype(float)
    plays["pass_e"] = np.where(db, plays.epa, np.nan)
    plays["rush_e"] = np.where(~db, plays.epa, np.nan)
    plays["expl"] = ((db & (plays.yards_gained >= 20))
                     | (~db & (plays.yards_gained >= 10))).astype(float)
    plays["sk"] = np.where(db, plays.sack.fillna(0), np.nan)
    plays["pr"] = np.where(db, ((plays.sack.fillna(0) + plays.qb_hit.fillna(0)) > 0)
                           .astype(float), np.nan)
    neutral = plays.down.isin([1, 2]) & plays.wp.between(0.2, 0.8)
    plays["pr_neutral"] = np.where(neutral, plays.is_db, np.nan)

    g = plays.groupby(["game_id", "posteam"]).agg(
        epa=("epa", "mean"), sr=("success", "mean"),
        pass_epa=("pass_e", "mean"), rush_epa=("rush_e", "mean"),
        expl=("expl", "mean"), sack=("sk", "mean"), press=("pr", "mean"),
        pass_rate=("pr_neutral", "mean"), n_plays=("epa", "size"))

    # Drives: points per drive and red-zone touchdown rate.
    d = p[p.fixed_drive.notna() & p.posteam.notna()]
    drv = d.groupby(["game_id", "posteam", "fixed_drive"]).agg(
        res=("fixed_drive_result", "first"), minyl=("yardline_100", "min"))
    drv = drv[drv.res != "End of half"]
    drv["pts"] = drv.res.map({"Touchdown": 7.0, "Field goal": 3.0}).fillna(0.0)
    drv["rz"] = drv.minyl <= 20
    drv["rz_td"] = np.where(drv.rz, (drv.res == "Touchdown").astype(float), np.nan)
    dg = drv.groupby(["game_id", "posteam"]).agg(ppd=("pts", "mean"),
                                                  rz_td=("rz_td", "mean"))
    g = g.join(dg).reset_index().rename(columns={"posteam": "team"})

    meta = (p.groupby("game_id")
              .agg(season=("season", "first"), week=("week", "first"),
                   home_team=("home_team", "first"), away_team=("away_team", "first"))
              .reset_index())
    g = g.merge(meta, on="game_id")
    g["opp"] = np.where(g.team == g.home_team, g.away_team, g.home_team)
    # Defensive numbers = opponent's offense in the same game.
    opp = g[["game_id", "team"] + STATS].rename(
        columns={"team": "opp", **{s: f"d_{s}" for s in STATS}})
    g = g.merge(opp, on=["game_id", "opp"], how="left")
    g = g.rename(columns={s: f"o_{s}" for s in STATS})
    return g[["season", "week", "game_id", "team", "opp"]
             + [f"o_{s}" for s in STATS] + [f"d_{s}" for s in STATS] + STYLE]


def _pregame_mean(tg: pd.DataFrame, cols: list[str], prior: pd.DataFrame | None,
                  lg: pd.Series) -> pd.DataFrame:
    """Each team's average over games BEFORE this one, with last season as a prior."""
    tg = tg.sort_values(["team", "week"]).copy()
    out = tg[["season", "week", "game_id", "team", "opp"]].copy()
    for c in cols:
        x = tg[c].fillna(lg[c])
        csum = x.groupby(tg.team).cumsum() - x
        n = tg.groupby("team").cumcount()
        if prior is not None and c in prior:
            pr = tg.team.map(prior[c]).fillna(lg[c])
            pr = lg[c] + PRIOR_KEEP * (pr - lg[c])
        else:
            pr = pd.Series(lg[c], index=tg.index)
        out[c] = (PRIOR_GAMES * pr + csum) / (PRIOR_GAMES + n)
    return out


def team_efficiency(seasons) -> pd.DataFrame:
    """
    Pregame opponent-adjusted efficiency for every team-game in `seasons`.

    Returns season, week, game_id, team, opp, and o_*/d_* per STATS plus
    pass_rate. o_* higher = better offense; d_* is what the defense ALLOWS
    (lower = better defense).
    """
    seasons = sorted(seasons)
    first = seasons[0] - 1
    raw = {s: _team_games(s) for s in range(first, seasons[-1] + 1)}
    ocols = [f"o_{s}" for s in STATS]
    dcols = [f"d_{s}" for s in STATS]
    allc = ocols + dcols + STYLE
    frames = []
    prior_adj = None
    for s in range(first, seasons[-1] + 1):
        tg = raw[s]
        lg = (raw[s - 1] if s - 1 in raw else tg)[allc].mean()
        pre = _pregame_mean(tg, allc, prior_adj, lg)
        # Opponent adjustment: what this offense did, relative to what that
        # defense had been allowing BEFORE the game (and vice versa).
        opp_pre = pre.set_index(["game_id", "team"])
        key = pd.MultiIndex.from_arrays([tg.game_id, tg.opp])
        adj = tg.copy()
        for st in STATS:
            opp_d = opp_pre[f"d_{st}"].reindex(key).to_numpy()
            opp_o = opp_pre[f"o_{st}"].reindex(key).to_numpy()
            adj[f"o_{st}"] = tg[f"o_{st}"] - (np.nan_to_num(opp_d, nan=lg[f"d_{st}"]) - lg[f"d_{st}"])
            adj[f"d_{st}"] = tg[f"d_{st}"] - (np.nan_to_num(opp_o, nan=lg[f"o_{st}"]) - lg[f"o_{st}"])
        pre_adj = _pregame_mean(adj, allc, prior_adj, lg)
        if s in seasons:
            frames.append(pre_adj)
        # Full-season adjusted averages become next season's prior.
        prior_adj = adj.groupby("team")[allc].mean()
    return pd.concat(frames, ignore_index=True)


# ------------------------------------------------------------- game factors

def _haversine_mi(a, b) -> float:
    (la1, lo1), (la2, lo2) = a, b
    p1, p2 = math.radians(la1), math.radians(la2)
    dl, dp = math.radians(lo2 - lo1), p2 - p1
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def _home_stadium(games: pd.DataFrame) -> dict:
    """Each team's most-used non-neutral stadium id."""
    g = games[~games.neutral.fillna(False).astype(bool)]
    return g.groupby("home_team").stadium_id.agg(lambda s: s.mode().iat[0]).to_dict()


def build_game_factors(games: pd.DataFrame, seasons) -> pd.DataFrame:
    """
    One row per game with every candidate factor, home-minus-away where it
    makes sense. `games` is data/cache/dataset_2010_2025.parquet (it carries
    gametime, rest, coaches, roof, temp, wind).
    """
    from .weather import STADIUMS, DOMES, RETRACTABLE, OPEN_AIR

    seasons = sorted(seasons)
    g = games[games.season.isin(seasons)].copy()
    out = g[["game_id", "season", "week", "home_team", "away_team"]].copy()

    # ---- efficiency + matchup
    eff = team_efficiency(seasons).set_index(["game_id", "team"])
    h = eff.reindex(pd.MultiIndex.from_arrays([g.game_id, g.home_team]))
    a = eff.reindex(pd.MultiIndex.from_arrays([g.game_id, g.away_team]))
    h.index = a.index = g.index
    for st in STATS:
        # net = own offense minus what own defense allows; sign flips for
        # "bad" stats (sacks/pressure taken on offense).
        sign = -1.0 if st in ("sack", "press") else 1.0
        out[f"eff_{st}"] = sign * ((h[f"o_{st}"] - h[f"d_{st}"])
                                   - (a[f"o_{st}"] - a[f"d_{st}"]))
    lgm = eff.mean(numeric_only=True)
    c = lambda frame, col: frame[col] - lgm[col]
    # Matchups: products of centered strengths. Home pass offense x away pass
    # defense (allowed; higher = worse defense), minus the reverse.
    out["mu_pass"] = c(h, "o_pass_epa") * c(a, "d_pass_epa") - c(a, "o_pass_epa") * c(h, "d_pass_epa")
    out["mu_rush"] = c(h, "o_rush_epa") * c(a, "d_rush_epa") - c(a, "o_rush_epa") * c(h, "d_rush_epa")
    # Pass rush vs protection: away pressure allowed x home pressure generated.
    # d_press = pressure the defense ALLOWS the opponent's QB to face, i.e.
    # pressure generated. o_press = pressure the offense gives up.
    out["mu_rush_vs_pro"] = (c(a, "o_press") * c(h, "d_press")
                             - c(h, "o_press") * c(a, "d_press"))
    out["mu_expl"] = c(h, "o_expl") * c(a, "d_expl") - c(a, "o_expl") * c(h, "d_expl")
    # Style clash: pass-heavy offense into a defense that stops the pass best.
    out["mu_style"] = (c(h, "pass_rate") * -c(a, "d_pass_epa")
                       - c(a, "pass_rate") * -c(h, "d_pass_epa"))
    out["_h_pass_rate"] = h["pass_rate"]
    out["_a_pass_rate"] = a["pass_rate"]

    # ---- weather
    sid = g.stadium_id.fillna("")
    roof = g.roof.fillna("")
    indoors = (sid.isin(DOMES) | sid.isin(RETRACTABLE)
               | roof.isin(["dome", "closed"])) & ~sid.isin(OPEN_AIR)
    from .weather import gamebook
    gb = g[["game_id"]].merge(gamebook(range(2016, max(seasons) + 1)), on="game_id", how="left")
    gb.index = g.index
    wind = g.wind.fillna(gb.gb_wind).where(~indoors, 0).fillna(0.0)
    temp = g.temp.fillna(gb.gb_temp).where(~indoors, 70).fillna(65.0)
    precip = gb.precip.fillna(False).astype(bool)
    precip = pd.Series(precip, index=g.index) & ~indoors
    out["wx_wind"] = wind
    out["wx_wind15"] = (wind >= 15).astype(float)
    out["wx_cold"] = (temp < 32).astype(float)
    out["wx_precip"] = precip.astype(float)
    # Does bad weather hurt the more pass-heavy team? (home minus away pass rate)
    pr_diff = (h["pass_rate"] - a["pass_rate"]).fillna(0)
    out["wx_wind_x_pass"] = wind * pr_diff
    out["wx_precip_x_pass"] = out.wx_precip * pr_diff
    home_std = _home_stadium(games)
    away_home_dome = g.away_team.map(home_std).isin(DOMES | RETRACTABLE)
    out["wx_dome_team_cold"] = ((temp < 40) & ~indoors & away_home_dome).astype(float)
    out["_wx_bad"] = ((wind >= 15) | precip | (temp < 32)).astype(float)

    # ---- rest & travel
    out["rt_rest_diff"] = (g.home_rest - g.away_rest).clip(-7, 7).fillna(0)
    out["rt_home_bye"] = (g.home_rest >= 12).astype(float)
    out["rt_away_bye"] = (g.away_rest >= 12).astype(float)
    out["rt_away_short"] = (g.away_rest <= 5).astype(float)
    out["rt_home_short"] = (g.home_rest <= 5).astype(float)
    tz_h = g.home_team.map(TEAM_TZ_OFFSET).fillna(0)
    tz_a = g.away_team.map(TEAM_TZ_OFFSET).fillna(0)
    out["rt_tz"] = (tz_a - tz_h).abs().where(~g.neutral.astype(bool), 0)
    loc = g.stadium_id.map(STADIUMS)
    a_loc = g.away_team.map(home_std).map(STADIUMS)
    h_loc = g.home_team.map(home_std).map(STADIUMS)
    miles_a = [(_haversine_mi(x, y) if isinstance(x, tuple) and isinstance(y, tuple) else 0.0)
               for x, y in zip(a_loc, loc)]
    miles_h = [(_haversine_mi(x, y) if isinstance(x, tuple) and isinstance(y, tuple) else 0.0)
               for x, y in zip(h_loc, loc)]
    out["rt_miles"] = (np.array(miles_a) - np.array(miles_h)) / 1000.0
    hour = pd.to_numeric(g.gametime.fillna("13:00").str.slice(0, 2), errors="coerce").fillna(13)
    # West-coast team at a 1 pm ET kickoff (10 am body clock), and the reverse:
    # east team in a late night game.
    out["rt_west_early"] = ((tz_a <= -2) & (hour < 14)).astype(float) \
        - ((tz_h <= -2) & (hour < 14) & g.neutral.astype(bool)).astype(float)
    out["rt_east_late"] = ((tz_a == 0) & (hour >= 20) & (tz_h <= -2)).astype(float)

    # ---- situation & coaching
    out["sit_div"] = g.div_game.fillna(0).astype(float)
    out["sit_prime"] = ((hour >= 19) | ~g.weekday.isin(["Sunday"])).astype(float)
    out["sit_playoff"] = (g.game_type != "REG").astype(float)
    out = out.join(_coach_features(games, g))
    out = out.join(_stakes_features(games, g))

    # ---- injuries (non-QB)
    out = out.join(_injury_features(g, seasons))

    return out.reset_index(drop=True)


def _coach_features(all_games: pd.DataFrame, g: pd.DataFrame) -> pd.DataFrame:
    """Coach experience and track record, from games BEFORE this one."""
    ag = all_games[all_games.played].sort_values(["season", "week"])
    rows = []
    for side in ("home", "away"):
        other = "away" if side == "home" else "home"
        rows.append(pd.DataFrame({
            "game_id": ag.game_id, "season": ag.season, "week": ag.week,
            "coach": ag[f"{side}_coach"], "team": ag[f"{side}_team"],
            "margin": ag.result * (1 if side == "home" else -1),
            "ats": (ag.result - ag.spread_line) * (1 if side == "home" else -1),
            "off_bye": (ag[f"{side}_rest"] >= 12)}))
    cg = pd.concat(rows).sort_values(["season", "week"])
    cg["n"] = cg.groupby("coach").cumcount()
    cg["ats_c"] = cg.groupby("coach").ats.cumsum() - cg.ats.fillna(0)
    cg["seasons_team"] = cg.groupby(["coach", "team"]).season.transform(lambda s: s - s.min())
    bye = cg[cg.off_bye].copy()
    bye["nb"] = bye.groupby("coach").cumcount()
    bye["bye_ats_c"] = bye.groupby("coach").ats.cumsum() - bye.ats.fillna(0)
    cg = cg.merge(bye[["game_id", "coach", "nb", "bye_ats_c"]], on=["game_id", "coach"], how="left")
    key = cg.set_index(["game_id", "coach"])

    def get(side, col):
        return key[col].reindex(pd.MultiIndex.from_arrays([g.game_id, g[f"{side}_coach"]])).to_numpy()

    f = pd.DataFrame(index=g.index)
    # Shrunk career ATS margin: does this coach beat expectations over time?
    f["sit_coach_ats"] = (np.nan_to_num(get("home", "ats_c")) / (np.nan_to_num(get("home", "n")) + 50)
                          - np.nan_to_num(get("away", "ats_c")) / (np.nan_to_num(get("away", "n")) + 50))
    f["sit_first_year"] = ((np.nan_to_num(get("away", "seasons_team"), nan=0) == 0).astype(float)
                           - (np.nan_to_num(get("home", "seasons_team"), nan=0) == 0).astype(float))
    hb = np.nan_to_num(get("home", "bye_ats_c")) / (np.nan_to_num(get("home", "nb")) + 10)
    ab = np.nan_to_num(get("away", "bye_ats_c")) / (np.nan_to_num(get("away", "nb")) + 10)
    f["sit_coach_bye"] = hb * (g.home_rest >= 12) - ab * (g.away_rest >= 12)
    return f


def _stakes_features(all_games: pd.DataFrame, g: pd.DataFrame) -> pd.DataFrame:
    """Late-season stakes: out of it, or locked in, by record before the game."""
    reg = all_games[(all_games.game_type == "REG") & all_games.played]
    rows = []
    for side in ("home", "away"):
        rows.append(pd.DataFrame({"season": reg.season, "week": reg.week,
                                  "team": reg[f"{side}_team"],
                                  "win": (reg.result * (1 if side == "home" else -1) > 0).astype(float)
                                  + 0.5 * (reg.result == 0)}))
    r = pd.concat(rows).sort_values(["season", "team", "week"])
    r["w"] = r.groupby(["season", "team"]).win.cumsum() - r.win
    r["n"] = r.groupby(["season", "team"]).cumcount()
    key = r.set_index(["season", "week", "team"])

    def rec(side):
        idx = pd.MultiIndex.from_arrays([g.season, g.week, g[f"{side}_team"]])
        return key.w.reindex(idx).to_numpy(), key.n.reindex(idx).to_numpy()

    f = pd.DataFrame(index=g.index)
    late = (g.week >= 14) & (g.game_type == "REG")
    for side, sgn in (("home", 1), ("away", -1)):
        w, n = rec(side)
        losses = n - w
        out_of_it = late & (losses >= 9)
        locked = late & (g.week >= 17) & (w >= 12)
        f[f"_{side}_out"] = out_of_it.astype(float)
        f[f"_{side}_locked"] = locked.astype(float)
    f["sit_out_of_it"] = f._home_out - f._away_out
    f["sit_locked"] = f._home_locked - f._away_locked
    return f.drop(columns=["_home_out", "_away_out", "_home_locked", "_away_locked"])


POS_GROUP = {
    "T": "ol", "G": "ol", "C": "ol", "OL": "ol", "OT": "ol", "OG": "ol",
    "WR": "wr", "TE": "wr", "RB": "rb", "FB": "rb",
    "DE": "dl", "DT": "dl", "NT": "dl", "DL": "dl", "EDGE": "dl", "OLB": "lb",
    "LB": "lb", "ILB": "lb", "MLB": "lb",
    "CB": "db", "S": "db", "FS": "db", "SS": "db", "DB": "db",
}
INJ_GROUPS = ["ol", "wr", "rb", "dl", "lb", "db"]


def _injury_features(g: pd.DataFrame, seasons) -> pd.DataFrame:
    """Starter-equivalents out by position group (QB excluded), home minus away."""
    from .roster import (player_importance, load_injuries, OUT_DESIGNATIONS,
                         UNAVAILABLE_STATUS)
    from .depth import load_weekly_rosters

    frames = []
    for s in seasons:
        imp = player_importance(s)
        parts = []
        inj = load_injuries(s)
        if not inj.empty:
            i = inj[inj.report_status.isin(OUT_DESIGNATIONS)].dropna(subset=["gsis_id"])
            parts.append(i[["week", "team", "gsis_id", "position"]])
        try:
            ro = load_weekly_rosters(s)
            ro = ro[ro.status.isin(UNAVAILABLE_STATUS)].dropna(subset=["gsis_id"])
            parts.append(ro[["week", "team", "gsis_id", "position"]])
        except Exception:
            pass
        if not parts:
            continue
        a = pd.concat(parts).drop_duplicates(["week", "team", "gsis_id"])
        a["team"] = _normalize_team(a.team)
        a["grp"] = a.position.map(POS_GROUP)
        a = a[a.grp.notna()]
        a["imp"] = a.gsis_id.map(imp).fillna(0.0)
        t = a.pivot_table(index=["week", "team"], columns="grp", values="imp",
                          aggfunc="sum", fill_value=0.0).reset_index()
        t.insert(0, "season", s)
        frames.append(t)
    inj = pd.concat(frames, ignore_index=True)
    for grp in INJ_GROUPS:
        if grp not in inj:
            inj[grp] = 0.0
    key = inj.set_index(["season", "week", "team"])[INJ_GROUPS]
    hi = key.reindex(pd.MultiIndex.from_arrays([g.season, g.week, g.home_team])).fillna(0.0)
    ai = key.reindex(pd.MultiIndex.from_arrays([g.season, g.week, g.away_team])).fillna(0.0)
    f = pd.DataFrame(index=g.index)
    for grp in INJ_GROUPS:
        # Positive = HOME is the healthier side.
        f[f"inj_{grp}"] = ai[grp].to_numpy() - hi[grp].to_numpy()
    f["inj_total"] = f[[f"inj_{x}" for x in INJ_GROUPS]].sum(axis=1)
    return f


FAMILIES = {
    "efficiency": ["eff_epa", "eff_sr", "eff_pass_epa", "eff_rush_epa", "eff_expl",
                   "eff_sack", "eff_press", "eff_ppd", "eff_rz_td"],
    "matchup": ["mu_pass", "mu_rush", "mu_rush_vs_pro", "mu_expl", "mu_style"],
    "weather": ["wx_wind_x_pass", "wx_precip_x_pass", "wx_dome_team_cold"],
    "rest_travel": ["rt_rest_diff", "rt_home_bye", "rt_away_bye", "rt_away_short",
                    "rt_home_short", "rt_tz", "rt_miles", "rt_west_early", "rt_east_late"],
    "injuries": ["inj_ol", "inj_wr", "inj_rb", "inj_dl", "inj_lb", "inj_db"],
    "situation": ["sit_div", "sit_coach_ats", "sit_first_year", "sit_coach_bye",
                  "sit_out_of_it", "sit_locked"],
}
# Weather also changes how far apart the teams play, not just who is favored:
# a margin-shrink term (wind/precip/cold x projected margin) is built in the lab
# because it needs the projection.


# ================================================================ batch 2
# 2026-09-28, second pass: things score-based ratings CANNOT already know,
# because they change between one game and the next.

INTL = ("LON", "MEX", "GER", "MUN", "FRA", "SAO", "RIO", "MAD", "PAR", "MEL", "DUB", "BER")


def _team_rows(all_games: pd.DataFrame) -> pd.DataFrame:
    """One row per team per game, in schedule order, from that team's side."""
    ag = all_games.copy()
    rows = []
    for side, sgn in (("home", 1), ("away", -1)):
        o = "away" if side == "home" else "home"
        rows.append(pd.DataFrame({
            "game_id": ag.game_id, "season": ag.season, "week": ag.week,
            "team": ag[f"{side}_team"], "opp": ag[f"{o}_team"],
            "is_home": (side == "home") & ~ag.neutral.fillna(False).astype(bool),
            "margin": ag.result * sgn, "line": ag.spread_line * sgn,
            "ot": ag.overtime.fillna(0), "coach": ag[f"{side}_coach"],
            "div": ag.div_game.fillna(0), "weekday": ag.weekday,
            "intl": ag.stadium_id.fillna("").str.startswith(INTL),
            "surface": ag.surface.fillna("").str.strip().str.lower(),
            "played": ag.result.notna()}))
    return pd.concat(rows).sort_values(["team", "season", "week"]).reset_index(drop=True)


def build_extra_factors(all_games: pd.DataFrame, seasons) -> pd.DataFrame:
    """
    Batch-2 factors, one row per game (game_id). `all_games` should be the
    full schedule from 1999 (data/cache/games.parquet) so track records exist.
    """
    seasons = sorted(seasons)
    ag = all_games[all_games.game_type.notna()].copy()
    ag["neutral"] = ag.location.eq("Neutral") if "location" in ag else False
    tr = _team_rows(ag)
    grp = tr.groupby(["team", "season"])

    # ---- schedule spots (previous / next game for this team, same season)
    prev = lambda c: grp[c].shift(1)
    tr["prev_upset_win"] = ((prev("margin") > 0) & (prev("line") <= -3)).astype(float)
    tr["prev_blowout_loss"] = (prev("margin") <= -21).astype(float)
    tr["prev_blowout_win"] = (prev("margin") >= 21).astype(float)
    tr["prev_ot"] = (prev("ot") > 0).astype(float)
    tr["prev_intl"] = prev("intl").fillna(False).astype(float)
    tr["prev_mon_road"] = ((prev("weekday") == "Monday") & ~prev("is_home").fillna(True).astype(bool)).astype(float)
    tr["lookahead"] = ((grp["div"].shift(-1) == 1) & (tr["div"] == 0)).astype(float)
    # consecutive road games ending with this one
    road = (~tr.is_home).astype(int)
    streak = road.groupby([tr.team, tr.season, (road == 0).cumsum()]).cumsum()
    tr["road3"] = (streak >= 3).astype(float)

    # ---- mid-season coaching change (interim head coach)
    first_coach = grp["coach"].transform("first")
    tr["interim"] = (tr.coach != first_coach).astype(float)
    tr["interim_first3"] = (tr.interim.astype(bool)
                            & (tr.groupby(["team", "season", "coach"]).cumcount() < 3)).astype(float)

    # ---- form: last 3 games' margin vs the line (hot/cold beyond the rating)
    beat = tr.margin - tr.line
    tr["form3"] = beat.groupby([tr.team, tr.season]).transform(
        lambda s: s.shift(1).rolling(3, min_periods=2).mean()).fillna(0.0)

    # ---- team-specific home field from PRIOR seasons (home minus road margin)
    hf = tr[tr.played].groupby(["team", "season"]).apply(
        lambda x: pd.Series({"h": x.margin[x.is_home].sum(), "nh": x.is_home.sum(),
                             "r": x.margin[~x.is_home].sum(), "nr": (~x.is_home).sum()}))
    hf = hf.reset_index().sort_values(["team", "season"])
    for c in ("h", "nh", "r", "nr"):     # last 5 seasons before this one
        hf[c + "5"] = hf.groupby("team")[c].transform(lambda s: s.shift(1).rolling(5, min_periods=1).sum())
    split = (hf.h5 / hf.nh5 - hf.r5 / hf.nr5) / 2
    lg = split.groupby(hf.season).transform("mean")
    n = hf.nh5 + hf.nr5
    hf["team_hfa"] = ((split - lg) * n / (n + 80)).fillna(0.0)
    hfa = hf.set_index(["team", "season"]).team_hfa

    # ---- surface: visitor whose home field is the other surface type
    turf = lambda s: s.str.contains("turf|astro|matrix|a_turf")
    home_surf = tr[tr.is_home].groupby(["team", "season"]).surface.agg(
        lambda s: s.mode().iat[0] if len(s.mode()) else "")

    # ---- referee: crew's home margin in prior seasons, shrunk
    rg = ag[ag.result.notna() & ag.referee.notna()].copy()
    rs = rg.groupby(["referee", "season"]).agg(s=("result", "sum"), n=("result", "size")).reset_index()
    rs = rs.sort_values(["referee", "season"])
    rs["s_prev"] = rs.groupby("referee").s.transform(lambda x: x.shift(1).cumsum())
    rs["n_prev"] = rs.groupby("referee").n.transform(lambda x: x.shift(1).cumsum())
    lg_home = rg.groupby("season").result.mean()
    rs["ref_home"] = ((rs.s_prev / rs.n_prev - rs.season.map(lg_home.shift(1)))
                      * rs.n_prev / (rs.n_prev + 150)).fillna(0.0)
    ref = rs.set_index(["referee", "season"]).ref_home

    # ---- assemble per game
    g = ag[ag.season.isin(seasons)].copy()
    t = tr.set_index(["game_id", "team"])
    H = t.reindex(pd.MultiIndex.from_arrays([g.game_id, g.home_team]))
    A = t.reindex(pd.MultiIndex.from_arrays([g.game_id, g.away_team]))
    H.index = A.index = g.index
    out = g[["game_id"]].copy()
    for c in ("prev_upset_win", "prev_blowout_loss", "prev_blowout_win", "prev_ot",
              "prev_intl", "prev_mon_road", "lookahead", "road3", "interim",
              "interim_first3", "form3"):
        out[f"sp_{c}"] = H[c].to_numpy() - A[c].to_numpy()
    home = (~g.neutral.astype(bool)).astype(float)
    out["loc_team_hfa"] = pd.MultiIndex.from_arrays([g.home_team, g.season]).map(hfa).fillna(0.0).to_numpy() * home
    out["loc_altitude"] = (g.home_team.eq("DEN") & home.astype(bool)).astype(float)
    gs = turf(g.surface.fillna("").str.strip().str.lower())
    a_surf = pd.MultiIndex.from_arrays([g.away_team, g.season - 1]).map(home_surf)
    a_turf = turf(pd.Series(a_surf, index=g.index).fillna("").astype(str))
    out["loc_surface_away"] = (gs != a_turf).astype(float) * home
    out["ref_home"] = pd.MultiIndex.from_arrays([g.referee.fillna(""), g.season]).map(ref).fillna(0.0).to_numpy() * home
    out["total_line"] = g.total_line
    return out.reset_index(drop=True)


def unit_clusters(seasons) -> pd.DataFrame:
    """Several starters out at ONE unit (2+ OL, 2+ DBs): non-linear injury hits."""
    from .roster import player_importance, load_injuries, OUT_DESIGNATIONS, UNAVAILABLE_STATUS
    from .depth import load_weekly_rosters
    frames = []
    for s in seasons:
        imp = player_importance(s)
        parts = []
        inj = load_injuries(s)
        if not inj.empty:
            parts.append(inj[inj.report_status.isin(OUT_DESIGNATIONS)].dropna(subset=["gsis_id"])
                         [["week", "team", "gsis_id", "position"]])
        try:
            ro = load_weekly_rosters(s)
            parts.append(ro[ro.status.isin(UNAVAILABLE_STATUS)].dropna(subset=["gsis_id"])
                         [["week", "team", "gsis_id", "position"]])
        except Exception:
            pass
        a = pd.concat(parts).drop_duplicates(["week", "team", "gsis_id"])
        a["team"] = _normalize_team(a.team)
        a["grp"] = a.position.map(POS_GROUP)
        a = a[a.gsis_id.map(imp).fillna(0) >= 0.5]          # real starters only
        c = a.groupby(["week", "team", "grp"]).size().unstack(fill_value=0).reset_index()
        c.insert(0, "season", s)
        frames.append(c)
    return pd.concat(frames, ignore_index=True).fillna(0)


FAMILIES2 = {
    "schedule_spots": ["sp_prev_upset_win", "sp_prev_blowout_loss", "sp_prev_blowout_win",
                       "sp_prev_ot", "sp_prev_intl", "sp_prev_mon_road", "sp_lookahead", "sp_road3"],
    "coach_change": ["sp_interim", "sp_interim_first3"],
    "recent_form": ["sp_form3"],
    "venue": ["loc_team_hfa", "loc_altitude", "loc_surface_away"],
    "referee": ["ref_home"],
    "unit_clusters": ["uc_ol2", "uc_db2", "uc_wr2", "uc_dl2"],
}
