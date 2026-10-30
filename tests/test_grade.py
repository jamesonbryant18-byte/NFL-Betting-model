"""grade.py's season scorecard (fixed 2026-10-29): rematches and ties."""
import sys
sys.path.insert(0, "src")
sys.path.insert(0, "scripts")

import pandas as pd


def test_rematch_is_graded_in_its_own_week_and_a_tie_is_not_a_loss(tmp_path, monkeypatch):
    import grade
    games = pd.DataFrame([
        dict(game_id="2026_01_DEN_KC", season=2026, week=1, home_team="KC",
             away_team="DEN", result=7.0, spread_line=3.0),
        dict(game_id="2026_02_NYG_WAS", season=2026, week=2, home_team="WAS",
             away_team="NYG", result=0.0, spread_line=1.0),
        # the week-9 rematch is unplayed: it must not borrow week 1's result
        dict(game_id="2026_09_KC_DEN", season=2026, week=9, home_team="DEN",
             away_team="KC", result=None, spread_line=-1.5),
    ])
    monkeypatch.setattr(grade, "load_games", lambda: games)
    d = tmp_path / "2026"
    d.mkdir()
    head = "winner,loser,at_home,win_prob,proj_margin,market_favorite,confidence\n"
    (d / "week01_picks.csv").write_text(head + "KC,DEN,True,0.6,3.0,True,lean\n")
    (d / "week02_picks.csv").write_text(head + "NYG,WAS,False,0.52,0.5,False,coin flip\n")
    (d / "week09_picks.csv").write_text(head + "DEN,KC,True,0.55,1.0,False,slight\n")
    monkeypatch.setattr(grade, "PICKS_DIR", tmp_path)

    sc = grade.season_scorecard(2026)
    assert sc["weeks"] == [1, 2]
    assert (sc["su_w"], sc["su_l"], sc["ties"]) == (1, 0, 1)
    assert (sc["fav_w"], sc["fav_l"]) == (1, 0)
