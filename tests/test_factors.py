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
