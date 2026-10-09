"""Game factors (factors.py, config.FACTORS) — added 2026-09-28."""
import sys
sys.path.insert(0, "src")

import numpy as np
import pandas as pd


def _model():
    from nflmodel.model import NFLModel
    m = NFLModel()
    m.team_ratings = {"TB": 3.0, "CLE": -2.0}
    m.hfa = 1.5
    return m


GAME = dict(game_id="g1", week=4, home_team="TB", away_team="CLE", spread_line=4.5,
            home_moneyline=-200, away_moneyline=170, home_qb_name=None, away_qb_name=None)


def test_factor_adjust_reaches_the_projection():
    """A factor that never reaches the margin is a claimed fix that isn't (CLAUDE.md 3.3)."""
    m = _model()
    before = m.project(dict(GAME)).projected_margin
    m.factor_adjust = {"g1": -2.0}
    p = m.project(dict(GAME))
    assert abs(p.projected_margin - (before - 2.0)) < 1e-9
    assert p.factor_adj == -2.0
    assert m.project(dict(GAME, game_id="other")).projected_margin == before


def test_config_weights_are_the_measured_ones():
    from nflmodel.config import FACTORS
    assert set(FACTORS) == {"inj_total", "eff_epa", "rt_rest_diff"}
    assert all(v > 0 for v in FACTORS.values())       # healthier/better/rested side gains


def test_archive_raw_margin_excludes_factors(tmp_path, monkeypatch):
    """The trend checker learns from the frozen model; factors must be taken back out."""
    from nflmodel import archive
    monkeypatch.setattr(archive, "ARCHIVE_DIR", tmp_path)
    slate = pd.DataFrame([dict(game_id="g1", home_team="TB", away_team="CLE",
                               projected_margin=5.0, trend_adj=0.5, selftune_adj=0.25,
                               factor_adj=1.0, factor_inj=0.7, factor_epa=0.2,
                               factor_rest=0.1, factor_notes="injuries +0.7 TB",
                               spread_line=4.5, recommendation="NO BET")])
    ranked = pd.DataFrame([dict(rank=1, winner="TB", loser="CLE", matchup="CLE @ TB",
                                at_home=True, win_prob=0.6, proj_margin=5.0)])
    archive.archive_week(ranked, slate, {}, {}, 2026, 4, force=True)
    out = pd.read_csv(tmp_path / "2026" / "week04_picks.csv")
    assert abs(out.raw_margin.iat[0] - 3.25) < 1e-9
    assert out.factor_inj.iat[0] == 0.7


def test_live_injury_week_carries_latest_roster_status(monkeypatch):
    """Upcoming week has no roster rows yet: last known IR status must count."""
    from nflmodel import factors, roster, depth
    monkeypatch.setattr(roster, "player_importance", lambda s: {"p1": 1.0, "p2": 0.5})
    monkeypatch.setattr(roster, "load_injuries", lambda s: pd.DataFrame(
        columns=["week", "team", "gsis_id", "position", "report_status"]))
    monkeypatch.setattr(depth, "load_weekly_rosters", lambda s: pd.DataFrame([
        dict(week=3, team="TB", gsis_id="p1", position="T", status="RES"),
        dict(week=2, team="CLE", gsis_id="p2", position="CB", status="RES"),
        dict(week=3, team="CLE", gsis_id="p2", position="CB", status="ACT")]))  # came back
    g = pd.DataFrame([dict(season=2026, week=4, home_team="TB", away_team="CLE")])
    f = factors._injury_features(g, [2026], live_week=4)
    assert f.inj_ol.iat[0] == -1.0      # home TB missing a full-time tackle
    assert f.inj_db.iat[0] == 0.0       # CLE's corner is back: not counted
    assert f.inj_total.iat[0] == -1.0


def test_live_factors_carry_each_side(monkeypatch):
    """Game Detail shows both teams: per-side points must net to the game factor."""
    from nflmodel import factors
    monkeypatch.setattr(factors, "_injury_features", lambda g, s, live_week=None, per_side=False:
                        pd.DataFrame(dict(inj_total=[-2.0], home_out=[3.0], away_out=[1.0])))
    eff = pd.DataFrame(dict(o_epa=[0.10, -0.02], d_epa=[0.0, 0.03]), index=["TB", "CLE"])
    monkeypatch.setattr(factors, "team_efficiency_current", lambda s: eff)
    g = pd.DataFrame([dict(game_id="g1", home_team="TB", away_team="CLE",
                           home_rest=14.0, away_rest=4.0)])        # 10-day gap, capped at 7
    w = dict(inj_total=0.7, eff_epa=1.2, rt_rest_diff=0.1)
    r = factors.live_factor_shifts(g, 2026, 5, w).iloc[0]
    assert (r.home_inj_out, r.away_inj_out) == (3.0, 1.0)
    assert abs(r.factor_inj_home - r.factor_inj_away - r.factor_inj) < 1e-9
    assert abs(r.factor_epa_home - 1.2 * 0.10) < 1e-9 and abs(r.factor_epa_away + 1.2 * 0.05) < 1e-9
    assert abs(r.factor_epa_home - r.factor_epa_away - r.factor_epa) < 1e-9
    assert (r.home_rest, r.away_rest) == (14.0, 4.0)
    assert abs(r.factor_rest - 0.7) < 1e-9                         # the cap still applies


def test_side_shares_net_to_the_term():
    from nflmodel.excel import _side_shares
    assert _side_shares(-1.4, -2.1, -0.7) == (-2.1, -0.7)          # exact: own numbers
    h, a = _side_shares(0.5, 0.9, -0.3)                            # self-tune capped at 0.5
    assert abs(h - a - 0.5) < 1e-9 and h > 0 > a
    assert _side_shares(-1.5) == (0.0, 1.5)                        # game-level: to the side it favors
    assert _side_shares(0.0) == (0.0, 0.0)
    assert _side_shares(None) == (None, None)


def test_game_detail_fills_both_sides():
    """Every margin term has a home AND away number, and the totals net to the margin."""
    from nflmodel.excel import _model_rows
    slate = pd.DataFrame([dict(
        game_id="g1", home_team="TEN", away_team="HOU", spread_line=-7.5,
        projected_margin=-4.0189, home_team_rating=-4.9136, away_team_rating=1.4749,
        home_qb_adj=-1.2610, away_qb_adj=0.1297, hfa_used=1.5917, situational_adj=0.0,
        selftune_adj=0.5, home_tune=0.9, away_tune=0.1, trend_adj=0.0,
        factor_inj=1.9837, factor_inj_home=-0.4218, factor_inj_away=-2.4055,
        factor_epa=-0.3151, factor_epa_home=-0.0596, factor_epa_away=0.2555,
        factor_rest=0.0, factor_rest_home=0.0, factor_rest_away=0.0,
        home_inj_out=0.6, away_inj_out=3.42, home_net_epa=-0.05, away_net_epa=0.2145,
        home_rest=7.0, away_rest=7.0)])
    row = _model_rows(slate)[0]
    terms = ["hfa", "sit", "tune", "trend", "inj", "epa", "rest"]
    for t in terms:
        assert row[f"{t}_home"] is not None and row[f"{t}_away"] is not None, t
    home = (row["home_team_rating"] + row["home_qb_adj"]
            + sum(row[f"{t}_home"] for t in terms))
    away = (row["away_team_rating"] + row["away_qb_adj"]
            + sum(row[f"{t}_away"] for t in terms))
    assert abs(home - away - row["projected_margin"]) < 1e-3
    assert row["hfa_away"] == 0.0 and row["away_inj_out"] == 3.42
