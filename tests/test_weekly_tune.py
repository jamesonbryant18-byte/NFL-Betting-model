"""Single-book pricing, the live self-tune, and the mid-week archive merge."""
import sys
sys.path.insert(0, 'src')

import pandas as pd

from nflmodel import archive, shop
from nflmodel.selftune import live_corrections


def _raw():
    rows = []
    for book, spread, hml, aml in (("fanduel", -3.0, -150, 130),
                                   ("draftkings", -2.5, -140, 120),
                                   ("bet365", -3.5, -160, 140)):
        rows.append(dict(game="AAA@BBB", commence_time=None, book=book,
                         spread=spread, spread_odds=-110, away_spread_odds=-110,
                         home_ml=hml, away_ml=aml, home_team="BBB",
                         away_team="AAA", espn_id=None, source="action"))
    return pd.DataFrame(rows)


def test_single_book_uses_only_that_books_numbers(monkeypatch):
    monkeypatch.setattr(shop.odds, "live_odds", lambda s, w: _raw())
    slate = pd.DataFrame([dict(game_id="g", home_team="BBB", away_team="AAA",
                               spread_line=-1.0, home_moneyline=-110,
                               away_moneyline=-110, home_spread_odds=-110,
                               away_spread_odds=-110)])
    out, rep = shop.attach_live_odds(slate, 2026, 3, book="fanduel", verbose=False)
    r = out.iloc[0]
    assert (r.spread_line, r.home_moneyline, r.away_moneyline) == (-3.0, -150, 130)
    assert r.odds_source == "fanduel" and rep["single_book"] == "fanduel"


def test_single_book_missing_game_keeps_stored_line(monkeypatch):
    monkeypatch.setattr(shop.odds, "live_odds", lambda s, w: _raw())
    slate = pd.DataFrame([dict(game_id="g", home_team="ZZZ", away_team="YYY",
                               spread_line=4.0, home_moneyline=-180,
                               away_moneyline=150)])
    out, rep = shop.attach_live_odds(slate, 2026, 3, book="fanduel", verbose=False)
    assert out.iloc[0].spread_line == 4.0 and rep["missing"] == ["YYY@ZZZ"]


def _games():
    return pd.DataFrame([
        dict(season=2026, week=1, home_team="BBB", away_team="AAA",
             played=True, result=20.0),
        dict(season=2026, week=2, home_team="BBB", away_team="CCC",
             played=True, result=0.0),
    ])


def test_live_corrections_follow_the_miss_and_scale_with_alpha(tmp_path):
    pd.DataFrame([dict(matchup="AAA @ BBB", winner="BBB", proj_margin=3.0)]) \
        .to_csv(tmp_path / "week01_picks.csv", index=False)
    corr, used = live_corrections(_games(), 2026, 3, alpha=0.15,
                                  archive_dir=tmp_path)
    # BBB beat its projection by 17 -> positive for BBB, mirrored for AAA
    assert used.residual.tolist() == [17.0]
    assert corr["BBB"] > 0 and abs(corr["BBB"] + corr["AAA"]) < 1e-9
    assert abs(corr["BBB"] - 0.15 * 7.0) < 1e-9     # 17 is capped at 7
    assert corr["CCC"] == 0.0                        # week 2 not archived
    zero, _ = live_corrections(_games(), 2026, 3, alpha=0.0, archive_dir=tmp_path)
    assert all(v == 0 for v in zero.values())


def test_live_corrections_ignore_the_week_being_predicted(tmp_path):
    pd.DataFrame([dict(matchup="AAA @ BBB", winner="BBB", proj_margin=3.0)]) \
        .to_csv(tmp_path / "week01_picks.csv", index=False)
    _, used = live_corrections(_games(), 2026, 1, alpha=0.15, archive_dir=tmp_path)
    assert used.empty


def test_midweek_rerun_keeps_published_rows_for_played_games(tmp_path, monkeypatch):
    monkeypatch.setattr(archive, "week_dir", lambda s: tmp_path)
    cols = dict(rank=1, loser="x", at_home=True, win_prob=.6, moneyline=-150,
                market_favorite=True, confidence="lean", consistent=True)
    pd.DataFrame([dict(matchup="ATL @ GB", winner="GB", proj_margin=4.0, **cols),
                  dict(matchup="KC @ MIA", winner="KC", proj_margin=8.0, **cols)]) \
        .to_csv(tmp_path / "week03_picks.csv", index=False)
    pd.DataFrame([dict(game_id="2026_03_ATL_GB", recommendation="BET GB -4.5")]) \
        .to_csv(tmp_path / "week03_leans.csv", index=False)
    ranked = pd.DataFrame([dict(matchup="KC @ MIA", winner="KC", proj_margin=7.0, **cols)])
    slate = pd.DataFrame([dict(game_id="2026_03_KC_MIA", home_team="MIA",
                               away_team="KC", recommendation="NO BET")])
    archive.archive_week(ranked, slate, {}, {}, 2026, 3)
    out = pd.read_csv(tmp_path / "week03_picks.csv").set_index("matchup")
    assert out.loc["ATL @ GB", "proj_margin"] == 4.0     # published, untouched
    assert out.loc["KC @ MIA", "proj_margin"] == 7.0     # re-priced
    assert pd.read_csv(tmp_path / "week03_leans.csv").game_id.tolist() == ["2026_03_ATL_GB"]


def test_blowout_is_clipped_before_it_is_learned(tmp_path):
    pd.DataFrame([dict(matchup="AAA @ BBB", winner="BBB", proj_margin=3.0)]) \
        .to_csv(tmp_path / "week01_picks.csv", index=False)
    g = _games()
    g.loc[0, "result"] = -30.0                      # 33-point miss
    corr, _ = live_corrections(g, 2026, 3, alpha=1.0, cap=99.0,
                               resid_clip=7.0, archive_dir=tmp_path)
    assert abs(corr["BBB"] + 7.0) < 1e-9 and abs(corr["AAA"] - 7.0) < 1e-9
