"""
backup_qb_rule.py -- why the model kept betting PHI after Hurts went out, and
whether "no bets on a team starting a backup QB" should be a rule
(2026-11-02, after PHI +3.5, +4.5 and +5.5 all lost by 11+ with Tanner McKee).

    .venv/bin/python -W ignore scripts/backup_qb_rule.py

Part 1, the cause. Team and QB are fit jointly. Hurts has started nearly every
PHI game since 2021, so the fit cannot tell him apart from the team and most
of his value sits in PHI's TEAM rating: the fit credits Hurts himself with
+0.3 to +0.9 pts. McKee has too few starts for a rating and gets the pooled
replacement level (-2.4 to -3.3). So the model priced Hurts -> McKee at 2.6
pts in Week 6 and 4.2 by Week 8; the market moved Week 6 five points (PHI
-1.5 -> +3.5) when Hurts was ruled out. Every McKee week the model was 2.5 to
3 pts higher on PHI than FanDuel, and PHI lost by 11, 17 and 17.

Part 2, the history. The same blind spot over 2013-25 (the replayed card,
closing prices, today's rules):

  bets ON a team whose QB is...       2013-20                2021-25 (hold-out)
  new + under 8 starts (V0)           46 bets, won 43.5%     39 bets, won 41.0%
                                      (model said 60.9%)     (model said 59.1%)
  under 8 career starts (V1)          132, won 51.9% (59.4%) 80, won 50.0% (58.3%)
  stand-in for the regular (V2)       103, won 51.0% (60.0%) 70, won 51.4% (58.8%)

Overconfident by 8 to 18 points of win % in both periods. Cutting the bets
(the card refills with the next best) helps less, because the replacements
are ordinary card bets:

  rule                                2013-20                2021-25
  V0 new + under 8 starts             +16.0 units (t +1.67)  +12.2 units (t +1.37)
  V1 under 8 career starts            +16.8 units (t +1.21)   +1.7 units (t +0.15)
  V2 stand-in for the regular starter +10.3 units (t +0.77)   +2.7 units (t +0.25)

V0 only flags a backup's FIRST start, so it would have stopped Week 6 PHI but
not Weeks 7-8. V1 is the trend checker's own definition (written 2026-09-26,
before any of this), so it was not fit to the PHI losses; it would have
stopped all three. 2026 live bets V1 flags: CHI -3.5 W, TB +3 P, TB +8.5 W,
CHI -120 L, PHI +3.5 L, PHI +4.5 L, PHI +5.5 L (2-4-1, -$10.82 at $5).

Verdict: a real, repeatable overconfidence; the rule is a guardrail that costs
nothing measurable, not a source of profit. Jameson's call (not shipped).
"""
import os
import sys
from collections import Counter

sys.path.insert(0, "src")
sys.path.insert(0, "scripts")

import numpy as np
import pandas as pd

from nflmodel import replay
from nflmodel.data import load_games
from nflmodel.model import NFLModel
from nflmodel.trends import QB_HISTORY_FROM, team_context


def part1(games):
    """PHI's rating pieces as each live week's fit saw them."""
    from run_week import load_fitted
    from nflmodel.config import TRAIN_SEASON_START
    from nflmodel.data import build_dataset
    from nflmodel.ratings import REPLACEMENT_QB, fit_market_ratings
    params, qb_lambda, _ = load_fitted()
    hist = build_dataset(list(range(TRAIN_SEASON_START, 2027)))
    print("PART 1: PHI as each week's fit saw it (points vs an average team)")
    rows = []
    for wk in [3, 6, 7, 8, 9]:
        m = NFLModel(params=params, qb_lambda=qb_lambda).fit(hist, 2026, wk, market_games=games)
        mk, _ = fit_market_ratings(games, 2026, params, asof_week=wk)
        hurts = m.qb_ratings.get("Jalen Hurts", np.nan)
        mckee = m.qb_ratings.get("Tanner McKee", m.qb_ratings.get(REPLACEMENT_QB))
        rows.append(dict(week=wk, PHI_team=m.team_ratings["PHI"], Hurts=hurts, McKee=mckee,
                         swap=hurts - mckee, with_Hurts=m.strength("PHI", "Jalen Hurts"),
                         with_McKee=m.strength("PHI", "Tanner McKee"), market_PHI=mk.get("PHI", np.nan),
                         prior_weight=m.market_prior_weight_used))
    print(pd.DataFrame(rows).round(2).to_string(index=False))
    print("\n  model vs FanDuel in the McKee games (home margin):")
    for w in (6, 7, 8):
        p = pd.read_csv(f"picks/2026/week{w:02d}_leans.csv")
        r = p[(p.home_team == "PHI") | (p.away_team == "PHI")].iloc[0]
        g = games[games.game_id == r.game_id].iloc[0]
        print(f"    Week {w} {r.away_team} @ {r.home_team}: model {r.projected_margin:+.1f}, "
              f"line {r.spread_line:+.1f}, final {g.result:+.0f}; bet {r.bet_side}")
    print()


def flags(games):
    """(game_id, team) sets for the three backup-QB definitions."""
    ctx = team_context(games[games.season.between(QB_HISTORY_FROM, 2026)], pd.DataFrame())
    v2 = pd.Series(False, index=ctx.index)
    for _, g in ctx.groupby("team", sort=False):          # each team's rows are in date order
        prev = []
        for i, q, s in zip(g.index, g.qb, g.qb_starts):
            top = Counter(x for x in prev[-8:] if x).most_common(1)
            v2[i] = bool(q) and s < 8 and q != (top[0][0] if top else None)
            if q:
                prev.append(q)
    under8 = ctx.qb_starts < 8
    defs = {"V0 new + under 8 starts": ctx.qb_new.fillna(False).astype(bool) & under8,
            "V1 under 8 career starts": under8,
            "V2 stand-in for the regular starter": v2}
    return {k: set(zip(ctx.game_id[m], ctx.team[m])) for k, m in defs.items()}, ctx


def rule_model(d, flagset):
    """The live rules, but no bet and no filler on the flagged side."""
    key = {(h, a, round(float(p), 6)): {t for t in (h, a) if (gid, t) in flagset}
           for gid, h, a, p in zip(d.game_id, d.home_team, d.away_team, d.proj)}

    class Rule(NFLModel):
        def _recommend(self, projected, line, *a, **k):
            rec = super()._recommend(projected, line, *a, **k)
            home, away = k.get("home", a[9] if len(a) > 9 else None), k.get("away", a[10] if len(a) > 10 else None)
            if rec["bet_side"] and rec["bet_side"].split()[0] in key.get((home, away, round(float(projected), 6)), ()):
                return {**rec, "recommendation": "NO BET", "bet_market": "", "bet_side": "",
                        "bet_odds": 0.0, "stake": 0.0}
            return rec

        def _near_miss(self, r, spread_odds):
            best = super()._near_miss(r, spread_odds)
            bad = key.get((r["home_team"], r["away_team"], round(float(r["projected_margin"]), 6)), ())
            return None if best and best["team"] in bad else best
    return Rule()


def show(label, x):
    c = replay.card_summary(x)
    if not c.get("n"):
        print(f"    {label:<40} none")
        return
    print(f"    {label:<40} {c['n']:>4} bets  {c['won']}-{c['lost']}-{c['push']}  won {c['win_pct']:.1%} "
          f"(model said {c['expected_win_pct']:.1%})  ROI {c['roi']:+.2%} (SE {c['roi_se']:.2%})")


def vs(x, base):
    b = base.groupby(["season", "week"]).units.sum()
    diff = x.groupby(["season", "week"]).units.sum().reindex(b.index, fill_value=0) - b
    return diff.sum(), diff.std(ddof=1) * len(diff) ** 0.5


def part2(games):
    fs, ctx = flags(games)
    d = replay.deployed()
    print("PART 2: the replayed card, closing prices, today's rules")
    for label, yrs in [("2013-20 (fit period)", replay.TUNE), ("2021-25 (hold-out)", replay.HOLD)]:
        sub = d[d.season.isin(yrs)]
        sub.attrs = d.attrs
        now = replay.card(sub)
        print(label)
        show("today's rules", now)
        for name, f in fs.items():
            on = now[[(g, s.split()[0]) in f for g, s in zip(now.game_id, now.side)]]
            show(f"  bets ON a team, {name}", on)
            u, se = vs(replay.card(sub, model=rule_model(d, f)), now)
            print(f"      rule on: {u:+.1f} units vs today's rules (t {u / se:+.2f})")
        print()

    led = pd.read_csv("data/model_bet_ledger_2026.csv")
    g26 = games[games.season == 2026]
    gid = {(int(w), f"{a} @ {h}"): i for w, a, h, i in zip(g26.week, g26.away_team, g26.home_team, g26.game_id)}
    led["game_id"] = [gid.get((int(w), g)) for w, g in zip(led.week, led.game)]
    led["team"] = led.bet.str.split().str[0]
    c = ctx.set_index(["game_id", "team"])
    led["qb"] = [c.qb.get((i, t)) for i, t in zip(led.game_id, led.team)]
    led["starts"] = [c.qb_starts.get((i, t)) for i, t in zip(led.game_id, led.team)]
    for name, f in fs.items():
        led[name.split()[0]] = [(i, t) in f for i, t in zip(led.game_id, led.team)]
    hit = led[led.V0 | led.V1 | led.V2]
    print("2026 live card bets ON a flagged team (ledger; Week 8 is graded on Wednesday):")
    print(hit[["week", "game", "bet", "qb", "starts", "V0", "V1", "V2", "out", "pnl_at_5"]].to_string(index=False))


if __name__ == "__main__":
    games = load_games()
    part1(games)
    part2(games)
