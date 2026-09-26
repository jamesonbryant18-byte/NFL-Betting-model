"""The miss-trend checker: statistics, pre-game context, and live application."""
import sys
sys.path.insert(0, 'src')

import numpy as np
import pandas as pd

from nflmodel import trends


def test_bh_controls_false_discoveries():
    assert trends.benjamini_hochberg([0.001, 0.5, 0.9], q=0.1) == [True, False, False]
    assert trends.benjamini_hochberg([0.04] + [0.9] * 19, q=0.1) == [False] * 20
    assert trends.benjamini_hochberg([float('nan'), 0.0001], q=0.1) == [False, True]


def test_logistic_recovers_known_calibration():
    rng = np.random.default_rng(0)
    x = rng.normal(0, 1, 20000)
    y = (rng.random(20000) < 1 / (1 + np.exp(-(0.2 + 1.5 * x)))).astype(float)
    a, b = trends.fit_logistic(x, y)
    assert abs(a - 0.2) < 0.06 and abs(b - 1.5) < 0.08


def test_calibration_stretch_lowers_longshot_probability():
    cal = {"a": 0.0, "b": 1.5}
    assert trends.calibrate(0.25, cal) < 0.25          # dog: less likely
    assert trends.calibrate(0.75, cal) > 0.75          # favorite: more likely
    assert abs(trends.calibrate(0.5, cal) - 0.5) < 1e-9
    assert trends.calibrate(0.3, None) == 0.3


def _frame(**kw):
    base = dict(game_id=["g"], season=[2024], week=[5], gameday=["2024-10-06"],
                weekday=["Sunday"], gametime=["13:00"], home_team=["BUF"], away_team=["MIA"],
                spread_line=[7.5], total_line=[45.0], div_game=[0], neutral=[False],
                home_rest=[7], away_rest=[7], windy=[False], precip=[False], cold=[False],
                home_qb_new=[False], away_qb_new=[False], home_qb_starts=[50],
                away_qb_starts=[50], home_prev_margin=[3.0], away_prev_margin=[3.0],
                home_prev_to=[0.0], away_prev_to=[0.0], home_prev_luck=[0.0],
                away_prev_luck=[0.0], home_pass_rel=[0.1], away_pass_rel=[0.1],
                home_tz=[0.0], away_tz=[0.0], kick_hour=[13.0], projected_margin=[6.0])
    base.update({k: [v] for k, v in kw.items()})
    return pd.DataFrame(base)


def test_subject_signs_follow_the_spread_convention():
    # spread_line > 0 means the HOME team is favored
    s = trends.subjects(_frame(spread_line=7.5))
    assert s["big_favorite"][0] == 1
    s = trends.subjects(_frame(spread_line=-8.0))
    assert s["big_favorite"][0] == -1 and s["home_underdog"][0] == 1
    s = trends.subjects(_frame(spread_line=3.0))
    assert s["big_favorite"][0] == 0 and s["small_favorite"][0] == 1


def test_new_qb_only_flags_the_team_that_changed():
    s = trends.subjects(_frame(away_qb_new=True))
    assert s["new_qb"][0] == -1
    s = trends.subjects(_frame(home_qb_new=True, away_qb_new=True))
    assert s["new_qb"][0] == 0


def test_team_context_uses_only_earlier_games():
    sched = pd.DataFrame([
        dict(game_id="a", season=2025, week=1, gameday="2025-09-07", home_team="BUF",
             away_team="MIA", result=28.0, home_qb_name="Josh Allen", away_qb_name="Tua"),
        dict(game_id="b", season=2025, week=2, gameday="2025-09-14", home_team="BUF",
             away_team="NYJ", result=-3.0, home_qb_name="Mitch Trubisky", away_qb_name="Geno"),
        dict(game_id="c", season=2025, week=3, gameday="2025-09-21", home_team="MIA",
             away_team="BUF", result=None, home_qb_name=None, away_qb_name=None),
    ])
    ctx = trends.team_context(sched, pd.DataFrame(), starters={"BUF": "Josh Allen"}) \
        .set_index(["game_id", "team"])
    assert np.isnan(ctx.loc[("a", "BUF"), "prev_margin"])          # nothing before week 1
    assert ctx.loc[("b", "BUF"), "prev_margin"] == 28.0              # week 1, not week 2
    assert bool(ctx.loc[("b", "BUF"), "qb_new"]) is True             # Allen -> Trubisky
    assert ctx.loc[("c", "BUF"), "prev_margin"] == -3.0              # BUF lost by 3 in week 2
    assert bool(ctx.loc[("c", "BUF"), "qb_new"]) is False            # Allen back: started 2 games ago
    assert ctx.loc[("c", "BUF"), "qb_starts"] == 1                   # Allen: one prior start
    assert ctx.loc[("c", "MIA"), "prev_margin"] == -28.0


def test_game_shifts_apply_sign_and_cap():
    active = {"margin": [
        {"key": "big_favorite", "text": "Big favorites", "live_shift": 1.5},
        {"key": "model_far_from_market", "text": "Far from line", "live_shift": -1.5},
    ]}
    # home favored by 7.5, model says 3.0: big favorite (+1.5 home) and the
    # model is 4.5 below the line, leaning AWAY (-1 subject * -1.5 = +1.5 home)
    f = _frame(spread_line=7.5, projected_margin=3.0)
    shift, notes = trends.game_shifts(f, active)
    assert shift[0] == trends.MAX_TOTAL_SHIFT                       # 3.0 capped to 2.0
    assert "Big favorites" in notes[0]
    shift, _ = trends.game_shifts(_frame(spread_line=-7.5, projected_margin=-7.0), active)
    assert shift[0] == -1.5                                          # away big favorite only


def test_game_shifts_do_nothing_without_confirmed_trends():
    shift, notes = trends.game_shifts(_frame(), {})
    assert shift[0] == 0 and notes == [""]


def test_longshot_cap_only_from_the_long_end():
    rows = lambda st: [{"group": f"moneyline underdog: {b}", "status": s}
                       for b, s in zip(["+151 to +250", "+251 to +400", "+401 and up"], st)]
    assert trends.ml_underdog_cap(rows(["confirmed", "no pattern", "no pattern"])) is None
    assert trends.ml_underdog_cap(rows(["no pattern", "no pattern", "confirmed"])) == 400
    assert trends.ml_underdog_cap(rows(["no pattern", "confirmed", "confirmed"])) == 250


def test_joint_fit_absorbs_a_duplicate_reason():
    rng = np.random.default_rng(1)
    n = 4000
    line = rng.choice([-10.0, -4.0, 3.0, 8.0], n)
    h = pd.concat([_frame()] * n, ignore_index=True)
    h["spread_line"] = line
    h["season"] = np.where(np.arange(n) < n // 2, 2013 + np.arange(n) % 8, 2023)
    h["projected_margin"] = line * 0.8
    # truth: big favorites beat the model by 3 points; nothing else matters
    big = np.where(np.abs(line) >= 7, np.sign(line), 0)
    h["result"] = h.projected_margin + 3.0 * big + rng.normal(0, 3, n)
    rows = trends.test_margin_trends(h)
    joint = trends.fit_joint(h, rows)
    assert joint["keys"][0] == "big_favorite"           # the real cause goes in first
    assert "small_favorite" not in joint["keys"]
    assert joint["status"] == "confirmed"
    assert joint["conf_mae_after"] < joint["conf_mae_before"]


def test_joint_fit_drops_a_reason_that_hurts_2021_on():
    rng = np.random.default_rng(2)
    n = 6000
    line = rng.choice([-10.0, -4.0, 3.0, 8.0], n)
    h = pd.concat([_frame()] * n, ignore_index=True)
    h["spread_line"] = line
    disc = np.arange(n) < n // 2
    h["season"] = np.where(disc, 2013 + np.arange(n) % 8, 2021 + np.arange(n) % 5)
    h["projected_margin"] = line * 0.8
    big = np.where(np.abs(line) >= 7, np.sign(line), 0)
    mid = np.where(np.abs(line) == 4, np.sign(line), 0)
    # mid favorites beat the model in 2013-2020 only; big favorites always
    effect = 3.0 * big + np.where(disc, 2.0, -2.0) * mid
    h["result"] = h.projected_margin + effect + rng.normal(0, 3, n)
    rows = [dict(key=k, status="candidate", effect_disc=1.0) for k in ("big_favorite", "mid_favorite")]
    joint = trends.fit_joint(h, rows)
    assert joint["keys"] == ["big_favorite"] and joint["pruned"] == ["mid_favorite"]


def test_capped_ridge_refits_the_others_around_the_cap():
    rng = np.random.default_rng(3)
    X = np.column_stack([rng.choice([0, 1], 5000), rng.choice([0, 1], 5000)]).astype(float)
    r = 4.0 * X[:, 0] + 1.0 * X[:, 1] + rng.normal(0, 1, 5000)
    b = trends._ridge_capped(X, r, lam=1.0, cap=1.5)
    assert b[0] == 1.5 and abs(b[1] - 1.0) > 0.3     # the other absorbs what the cap removed
    b2 = trends._ridge_capped(X, r, lam=1.0, cap=10.0)
    assert abs(b2[0] - 4.0) < 0.1


def test_symmetric_calibration_keeps_the_pick_with_the_margin():
    cal = {"a": 0.0, "b": 1.35}
    assert abs(trends.calibrate(0.5, cal) - 0.5) < 1e-12
    b = trends.fit_logistic_slope(np.array([-2.0, -1, 1, 2] * 500),
                                  np.array([0, 0, 1, 1] * 500, dtype=float))
    assert b > 1


def test_new_qb_ignores_a_starter_returning_from_one_missed_game():
    rows = []
    qbs = ["Kyler Murray", "Kyler Murray", "Carson Wentz", "Kyler Murray"]
    for i, q in enumerate(qbs, start=1):
        rows.append(dict(game_id=f"g{i}", season=2026, week=i,
                         gameday=str(pd.Timestamp("2026-09-06") + pd.Timedelta(days=7 * i))[:10],
                         home_team="MIN", away_team="TB", result=3.0 if i < 4 else None,
                         home_qb_name=q if i < 4 else None, away_qb_name="Baker"))
    ctx = trends.team_context(pd.DataFrame(rows), pd.DataFrame(),
                              starters={"MIN": "Kyler Murray"}).set_index(["game_id", "team"])
    assert bool(ctx.loc[("g3", "MIN"), "qb_new"]) is True       # Wentz: new
    assert bool(ctx.loc[("g4", "MIN"), "qb_new"]) is False      # Murray back: not new


def test_published_history_uses_the_pre_fix_margin(tmp_path, monkeypatch):
    from nflmodel import archive
    monkeypatch.setattr(archive, "week_dir", lambda s: tmp_path)
    pd.DataFrame([dict(matchup="KC @ MIA", winner="KC", loser="MIA", proj_margin=10.4,
                       raw_margin=-8.4)]).to_csv(tmp_path / "week03_picks.csv", index=False)
    sched = pd.DataFrame([dict(game_id="2026_03_KC_MIA", season=2026, week=3,
                               home_team="MIA", away_team="KC", result=-14.0)])
    pub = trends.published_projections(2026, sched)
    assert pub.projected_margin.iloc[0] == -8.4 and pub.published_winner.iloc[0] == "KC"



def test_qb_starts_count_across_seasons():
    # A veteran's starts from earlier seasons must count (2026 Week 3 bug:
    # live counts started in 2025 and veterans read as inexperienced).
    rows = [dict(game_id=f"s{y}", season=y, week=1, gameday=f"{y}-09-10", home_team="WAS",
                 away_team="DAL", result=3.0, home_qb_name="Marcus Mariota", away_qb_name="Dak")
            for y in range(2015, 2025)]
    rows.append(dict(game_id="now", season=2026, week=3, gameday="2026-09-27", home_team="WAS",
                     away_team="SEA", result=None, home_qb_name=None, away_qb_name=None))
    ctx = trends.team_context(pd.DataFrame(rows), pd.DataFrame(),
                              starters={"WAS": "Marcus Mariota"}).set_index(["game_id", "team"])
    assert ctx.loc[("now", "WAS"), "qb_starts"] == 10


def test_qb_starts_count_other_teams_in_date_order():
    # Keenum's starts for LA must count when he starts for CHI, even though
    # CHI sorts before LA alphabetically.
    rows = [dict(game_id=f"la{i}", season=2017, week=i, gameday=f"2017-10-{10+i:02d}",
                 home_team="LA", away_team="SF", result=7.0, home_qb_name="Case Keenum",
                 away_qb_name="X") for i in range(1, 10)]
    rows.append(dict(game_id="chi", season=2026, week=3, gameday="2026-09-28", home_team="CHI",
                     away_team="PHI", result=None, home_qb_name=None, away_qb_name=None))
    ctx = trends.team_context(pd.DataFrame(rows), pd.DataFrame(),
                              starters={"CHI": "Case Keenum"}).set_index(["game_id", "team"])
    assert ctx.loc[("chi", "CHI"), "qb_starts"] == 9
    assert ctx.loc[("la1", "LA"), "qb_starts"] == 0
