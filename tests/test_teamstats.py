"""
teamstats invariants. Run: .venv/bin/python -W ignore -m pytest tests/test_teamstats.py -q

No network. ESPN and nflverse are monkeypatched to small frames, because the
point of these tests is the MERGE and SIGN logic, not whether a feed is up.
The ATS test is the one that matters: spread_line is points the HOME team is
favored by, and this repo has shipped that inverted once already.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

import numpy as np
import pandas as pd
import pytest

from nflmodel import teamstats as T
from nflmodel import espn, roster
from nflmodel.data import TEAMS


# ── position groups ───────────────────────────────────────────────

@pytest.mark.parametrize("pos,group", [
    ("QB", "QB"),
    ("RB", "RB"), ("FB", "RB"), ("HB", "RB"),
    ("WR", "WR"), ("TE", "TE"),
    ("OT", "OL"), ("T", "OL"), ("G", "OL"), ("OG", "OL"), ("C", "OL"),
    ("OL", "OL"), ("LT", "OL"), ("RT", "OL"), ("LG", "OL"), ("RG", "OL"),
    ("DE", "DL"), ("DT", "DL"), ("NT", "DL"), ("DL", "DL"), ("EDGE", "DL"),
    ("LB", "LB"), ("ILB", "LB"), ("OLB", "LB"), ("MLB", "LB"),
    ("CB", "DB"), ("S", "DB"), ("SS", "DB"), ("FS", "DB"), ("DB", "DB"), ("SAF", "DB"),
    ("K", "ST"), ("PK", "ST"), ("P", "ST"), ("LS", "ST"), ("KR", "ST"), ("PR", "ST"),
    ("XX", "OTHER"), (None, "OTHER"), (float("nan"), "OTHER"), ("", "OTHER"),
    ("qb", "QB"), (" wr ", "WR"),
])
def test_position_group(pos, group):
    assert T.position_group(pos) == group


def test_position_groups_constant():
    assert T.POSITION_GROUPS == ["QB", "RB", "WR", "TE", "OL", "DL", "LB", "DB", "ST"]


# ── name normalisation ────────────────────────────────────────────

def test_normalize_name_drops_suffix_and_punctuation():
    assert T.normalize_name("Michael Penix Jr.") == T.normalize_name("Michael Penix")
    assert T.normalize_name("Gardner Minshew II") == "gardner minshew"
    assert T.normalize_name("Ja'Marr Chase") == "jamarr chase"
    assert T.normalize_name("Amon-Ra St. Brown") == "amon ra st brown"
    assert T.normalize_name("  Odell   Beckham   Jr ") == "odell beckham"
    assert T.normalize_name("Robert Griffin III") == "robert griffin"
    assert T.normalize_name(None) == ""
    assert T.normalize_name(float("nan")) == ""


def test_normalize_name_keeps_single_token_that_looks_like_suffix():
    # A lone 'V' is a name, not a suffix -- never strip to nothing.
    assert T.normalize_name("V") == "v"


# ── records ───────────────────────────────────────────────────────

def _games():
    """
    Four scheduled games, three played. Sign convention throughout:
    result = home - away; spread_line = points the HOME team is favored by.
    """
    return pd.DataFrame([
        # week 1: KC (home) beats DEN 27-20, favored by 7 -> home does NOT cover
        dict(game_id="g1", season=2026, week=1, gameday="2026-09-13",
             home_team="KC", away_team="DEN", home_score=27, away_score=20,
             result=7 - 0 + 0, spread_line=7.5),
        # week 1: LA (home) loses to SF 17-24, LA is a 3-pt dog (line -3):
        # result -7 < -3 -> home does not cover, SF covers
        dict(game_id="g2", season=2026, week=1, gameday="2026-09-13",
             home_team="LA", away_team="SF", home_score=17, away_score=24,
             result=-7, spread_line=-3.0),
        # week 2: DEN (home) beats LA 24-21, favored by 3 -> push
        dict(game_id="g3", season=2026, week=2, gameday="2026-09-20",
             home_team="DEN", away_team="LA", home_score=24, away_score=21,
             result=3, spread_line=3.0),
        # week 3: unplayed -- must be ignored even when asking for week 4
        dict(game_id="g4", season=2026, week=3, gameday="2026-09-27",
             home_team="KC", away_team="LA", home_score=np.nan, away_score=np.nan,
             result=np.nan, spread_line=2.5),
        # a different season, must be ignored
        dict(game_id="g0", season=2025, week=1, gameday="2025-09-07",
             home_team="KC", away_team="LA", home_score=10, away_score=40,
             result=-30, spread_line=0.0),
    ])


def test_team_records_shape_and_week_cutoff():
    rec = T.team_records(_games(), 2026, 1).set_index("team")
    assert len(rec) == 32 and list(rec.index) == TEAMS
    assert (rec["games_played"] == 0).all()
    assert (rec["record"] == "0-0").all()
    assert (rec["last_result"] == "").all()


def test_team_records_wins_losses_pd():
    rec = T.team_records(_games(), 2026, 4).set_index("team")
    kc, la, den, sf = rec.loc["KC"], rec.loc["LA"], rec.loc["DEN"], rec.loc["SF"]

    # the unplayed week-3 game and the 2025 game count for nobody
    assert kc["games_played"] == 1 and la["games_played"] == 2

    assert kc["record"] == "1-0" and kc["pf"] == 27 and kc["pa"] == 20 and kc["pd"] == 7
    assert la["record"] == "0-2" and la["pf"] == 38 and la["pa"] == 48 and la["pd"] == -10
    assert den["record"] == "1-1" and den["pd"] == (20 + 24) - (27 + 21)
    assert sf["record"] == "1-0" and sf["home_record"] == "0-0" and sf["away_record"] == "1-0"
    assert la["home_record"] == "0-1" and la["away_record"] == "0-1"

    assert kc["last_result"] == "W 27-20 vs DEN"
    assert la["last_result"] == "L 21-24 @ DEN"
    assert den["last_result"] == "W 24-21 vs LA"
    assert sf["last_result"] == "W 24-17 @ LA"


def test_team_records_ats_home_favored_sign_convention():
    rec = T.team_records(_games(), 2026, 4).set_index("team")
    # g1: KC favored by 7.5 at home, won by 7 -> KC ATS loss, DEN ATS win
    assert rec.loc["KC", "ats_record"] == "0-1-0"
    # g2: LA a 3-pt home dog, lost by 7 -> LA ATS loss, SF ATS win
    # g3: DEN favored by 3 at home, won by 3 -> push for both
    assert rec.loc["LA", "ats_record"] == "0-1-1"
    assert rec.loc["DEN", "ats_record"] == "1-0-1"
    assert rec.loc["SF", "ats_record"] == "1-0-0"
    assert rec.loc["SF", "ats_wins"] == 1 and rec.loc["LA", "ats_pushes"] == 1


def test_team_records_ties_format():
    g = _games().iloc[:1].copy()
    g["home_score"] = 20; g["away_score"] = 20; g["result"] = 0
    rec = T.team_records(g, 2026, 2).set_index("team")
    assert rec.loc["KC", "record"] == "0-0-1"
    assert rec.loc["DEN", "last_result"] == "T 20-20 @ KC"


def test_team_records_no_line_is_not_an_ats_result():
    g = _games().iloc[:1].copy()
    g["spread_line"] = np.nan
    rec = T.team_records(g, 2026, 2).set_index("team")
    assert rec.loc["KC", "record"] == "1-0"
    assert rec.loc["KC", "ats_record"] == "0-0-0"


# ── roster status derivation ──────────────────────────────────────

def test_espn_roster_status_is_derived_behind_placeholders():
    """ESPN says 'Day-To-Day' for every IR-group player and 'News' for a
    just-suspended active one; the roster table must say what a filter needs."""
    raw = pd.DataFrame([
        dict(group="injuredReserveOrOut", status="Day-To-Day", injury_status="Injured Reserve"),
        dict(group="injuredReserveOrOut", status="Day-To-Day", injury_status="Out"),
        dict(group="injuredReserveOrOut", status="Day-To-Day", injury_status=None),
        dict(group="defense", status="News", injury_status="Suspension"),
        dict(group="offense", status="News", injury_status="Out"),
        dict(group="offense", status="News", injury_status=None),
        dict(group="practiceSquad", status="Practice Squad", injury_status=None),
        dict(group="suspended", status="Active", injury_status=None),
        dict(group="offense", status="Active", injury_status="Questionable"),
        dict(group="offense", status="Day-To-Day", injury_status="Questionable"),
    ])
    for c in espn.ROSTER_COLUMNS:
        if c not in raw.columns:
            raw[c] = None
    raw["team"] = "KC"; raw["player"] = [f"P{i}" for i in range(len(raw))]; raw["position"] = "WR"
    got = T._espn_roster_rows(raw)["status"].tolist()
    assert got == ["Injured Reserve", "Out", "Injured Reserve", "Suspended", "Out",
                   "Active", "Practice Squad", "Suspended", "Active", "Day-To-Day"]
    assert list(T._espn_roster_rows(raw).columns) == T.ROSTER_TABLE_COLUMNS


def test_roster_tag_uses_status_first():
    assert T._roster_tag("Active", None) == ""
    assert T._roster_tag("Active", "Suspension") == ""      # ESPN says Active: believe it
    assert T._roster_tag("Day-To-Day", "Questionable") == ""
    assert T._roster_tag("Day-To-Day", "Injured Reserve") == "IR"
    assert T._roster_tag("News", "Out") == "OUT"
    assert T._roster_tag("Reserve/IR", None) == "IR"
    assert T._roster_tag("Practice Squad", None) == "PS"
    assert T._roster_tag("Suspended", None) == "SUSP"
    assert T._roster_tag("Exempt", None) == "EXE"


# ── injury merge ──────────────────────────────────────────────────

def _espn_injuries():
    cols = espn.INJURY_COLUMNS
    rows = [
        # Mahomes: older Questionable, newer Out -> the Out must win
        dict(team="KC", player="Patrick Mahomes", position="QB", status="Questionable",
             injury="Ankle", return_date=None, updated="2026-09-03T15:00Z",
             short_comment="limited Wednesday"),
        dict(team="KC", player="Patrick Mahomes", position="QB", status="Out",
             injury="Ankle - High", return_date="2026-09-20", updated="2026-09-05T15:00Z",
             short_comment="ruled out Friday"),
        # Kelce: 'Active' is return news, not an injury -> dropped entirely
        dict(team="KC", player="Travis Kelce", position="TE", status="Active",
             injury="Knee", return_date=None, updated="2026-09-06T15:00Z",
             short_comment="back at practice"),
        # Penix: ESPN spells with the suffix, nflverse without -> one row
        dict(team="ATL", player="Michael Penix Jr.", position="QB", status="Questionable",
             injury="Shoulder", return_date=None, updated="2026-09-04T15:00Z",
             short_comment="listed questionable"),
        # ESPN-only player on a team nflverse has nothing for
        dict(team="LA", player="Puka Nacua", position="WR", status="Injured Reserve",
             injury="Knee - ACL", return_date="2026-11-01", updated="2026-09-01T15:00Z",
             short_comment="placed on IR"),
    ]
    df = pd.DataFrame(rows)
    for c in cols:
        if c not in df.columns:
            df[c] = None
    return df[cols]


def _nflverse_injuries():
    return pd.DataFrame([
        # matches Mahomes (ESPN Out beats nflverse Questionable)
        dict(season=2026, week=1, team="KC", gsis_id="00-0033873", full_name="Patrick Mahomes",
             position="QB", report_status="Questionable",
             practice_status="Limited Participation in Practice",
             practice_primary_injury="Ankle", report_primary_injury="Ankle"),
        # matches Penix without the suffix
        dict(season=2026, week=1, team="ATL", gsis_id="00-0039123", full_name="Michael Penix",
             position="QB", report_status="Questionable",
             practice_status="Full Participation in Practice",
             practice_primary_injury="Shoulder", report_primary_injury="Shoulder"),
        # nflverse-only, report status present, ESPN silent
        dict(season=2026, week=1, team="KC", gsis_id="00-0030506", full_name="Travis Kelce",
             position="TE", report_status="Out",
             practice_status="Did Not Participate In Practice",
             practice_primary_injury="Knee", report_primary_injury="Knee"),
        # practice-only: no report status -> derived 'Practice: DNP'
        dict(season=2026, week=1, team="LA", gsis_id="00-0031388", full_name="Aaron Donald",
             position="DE", report_status=None,
             practice_status="Did Not Participate In Practice",
             practice_primary_injury="Not injury related - resting player",
             report_primary_injury=None),
        # wrong week: must be ignored
        dict(season=2026, week=2, team="LA", gsis_id="00-0099999", full_name="Some Guy",
             position="CB", report_status="Out",
             practice_status="Did Not Participate In Practice",
             practice_primary_injury="Toe", report_primary_injury="Toe"),
        # right week but no designation of any kind: not on the report
        dict(season=2026, week=1, team="LA", gsis_id="00-0088888", full_name="Healthy Player",
             position="CB", report_status=None, practice_status=None,
             practice_primary_injury=None, report_primary_injury=None),
    ])


@pytest.fixture
def patched_feeds(monkeypatch):
    monkeypatch.setattr(espn, "fetch_injuries", lambda refresh=False: _espn_injuries())
    monkeypatch.setattr(roster, "load_injuries", lambda season, refresh=False: _nflverse_injuries())

    def _no_disk(*a, **k):
        raise AssertionError("injury_table must not touch disk or network here")
    monkeypatch.setattr(roster, "_load_cached", _no_disk)


def test_injury_table_merge(patched_feeds):
    df = T.injury_table(2026, 1)
    assert list(df.columns) == T.INJURY_TABLE_COLUMNS
    df = df.set_index(["team", "player"])

    # dedupe keeps the LATEST ESPN entry, and ESPN status beats nflverse
    m = df.loc[("KC", "Patrick Mahomes")]
    assert m["status"] == "Out"
    assert m["injury"] == "Ankle - High"
    assert m["expected_return"] == "2026-09-20"
    assert m["comment"] == "ruled out Friday"
    assert m["practice_status"] == "Limited"
    assert m["source"] == "espn+nflverse"
    assert m["updated"] == "2026-09-05T15:00Z"

    # 'Active' ESPN entry dropped; Kelce survives only via nflverse
    k = df.loc[("KC", "Travis Kelce")]
    assert k["status"] == "Out" and k["source"] == "nflverse"
    assert k["injury"] == "Knee" and k["comment"] == "" and k["expected_return"] == ""

    # suffix-insensitive join: one Penix row, not two
    penix = df.loc["ATL"]
    assert len(penix) == 1
    p = penix.iloc[0]
    assert p["source"] == "espn+nflverse" and p["practice_status"] == "Full"

    # ESPN-only row kept
    n = df.loc[("LA", "Puka Nacua")]
    assert n["status"] == "Injured Reserve" and n["source"] == "espn"

    # practice-only row gets the derived status and the practice injury text
    d = df.loc[("LA", "Aaron Donald")]
    assert d["status"] == "Practice: DNP"
    assert d["injury"] == "Not injury related - resting player"
    assert d["source"] == "nflverse"

    # wrong week and undesignated players are not on the report
    assert ("LA", "Some Guy") not in df.index
    assert ("LA", "Healthy Player") not in df.index
    assert len(df) == 5


def test_injury_table_sorted_by_team_then_severity(patched_feeds):
    df = T.injury_table(2026, 1)
    assert list(df["team"]) == sorted(df["team"])
    la = df[df["team"] == "LA"]["status"].tolist()
    assert la == ["Injured Reserve", "Practice: DNP"]
    kc = df[df["team"] == "KC"]["status"].tolist()
    assert kc == ["Out", "Out"]


def test_injury_table_survives_both_feeds_empty(monkeypatch):
    monkeypatch.setattr(espn, "fetch_injuries",
                        lambda refresh=False: pd.DataFrame(columns=espn.INJURY_COLUMNS))
    monkeypatch.setattr(roster, "load_injuries",
                        lambda season, refresh=False: pd.DataFrame(
                            columns=["season", "week", "team", "gsis_id", "full_name",
                                     "position", "report_status"]))
    df = T.injury_table(2026, 1)
    assert df.empty and list(df.columns) == T.INJURY_TABLE_COLUMNS


# ── summary ───────────────────────────────────────────────────────

def test_team_summary_32_rows_with_empty_inputs():
    empty_roster = pd.DataFrame(columns=T.ROSTER_TABLE_COLUMNS)
    empty_inj = pd.DataFrame(columns=T.INJURY_TABLE_COLUMNS)
    s = T.team_summary(_games(), 2026, 1, roster=empty_roster, injuries=empty_inj)
    assert len(s) == 32 and sorted(s["team"]) == sorted(TEAMS)
    for g in T.POSITION_GROUPS:
        assert g in s.columns and (s[g] == "").all()
    assert (s["roster_size"] == 0).all() and (s["n_injured"] == 0).all()
    assert (s["injured_list"] == "").all()
    assert s["rating"].isna().all() and s["rank"].isna().all()
    assert list(s["team"]) == TEAMS          # no ratings -> sorted by team


def test_team_summary_none_inputs_and_ratings_order():
    ratings = pd.DataFrame({"team": TEAMS, "rating": np.linspace(5, -5, 32)})
    ratings["rank"] = ratings["rating"].rank(ascending=False).astype(int)
    ratings = ratings.sample(frac=1, random_state=1)        # shuffle
    s = T.team_summary(_games(), 2026, 4, ratings=ratings,
                       starters={"KC": "Patrick Mahomes"}, qb_source={"KC": "depth chart"})
    assert len(s) == 32
    assert list(s["rank"]) == list(range(1, 33))
    kc = s[s["team"] == "KC"].iloc[0]
    assert kc["starting_qb"] == "Patrick Mahomes" and kc["qb_source"] == "depth chart"
    assert kc["record"] == "1-0" and kc["last_result"] == "W 27-20 vs DEN"


def test_team_summary_position_groups_and_injured_list():
    ros = pd.DataFrame([
        dict(team="KC", player="Patrick Mahomes", position="QB", pos_group="QB", jersey="15",
             age=30, years_exp=9, status="Active", injury_status=None, source="espn"),
        dict(team="KC", player="Gardner Minshew", position="QB", pos_group="QB", jersey="5",
             age=30, years_exp=7, status="Practice Squad", injury_status=None, source="espn"),
        dict(team="KC", player="Chris Oladokun", position="QB", pos_group="QB", jersey="7",
             age=28, years_exp=3, status="Day-To-Day", injury_status="Injured Reserve",
             source="espn"),
        dict(team="KC", player="Travis Kelce", position="TE", pos_group="TE", jersey="87",
             age=36, years_exp=13, status="Active", injury_status="Questionable", source="espn"),
    ])
    inj = pd.DataFrame([
        dict(team="KC", player="Travis Kelce", position="TE", status="Questionable",
             injury="Knee", practice_status="Limited", expected_return="",
             updated="", comment="", source="espn+nflverse"),
        dict(team="KC", player="Chris Oladokun", position="QB", status="Injured Reserve",
             injury="Foot", practice_status="", expected_return="2026-11-08",
             updated="", comment="", source="espn"),
    ])
    s = T.team_summary(_games(), 2026, 1, roster=ros, injuries=inj).set_index("team")
    kc = s.loc["KC"]
    assert kc["QB"] == "Patrick Mahomes, Gardner Minshew (PS), Chris Oladokun (IR)"
    assert kc["TE"] == "Travis Kelce"
    assert kc["roster_size"] == 2                 # Active only
    assert kc["n_injured"] == 2 and kc["n_out"] == 1
    assert kc["injured_list"] == ("Travis Kelce (TE) - Knee - Questionable; "
                                  "Chris Oladokun (QB) - Foot - Injured Reserve - ret 11/8")
    assert s.loc["LA", "QB"] == "" and s.loc["LA", "n_injured"] == 0


def test_injured_list_caps_at_twelve():
    inj = pd.DataFrame([
        dict(team="KC", player=f"Player {i:02d}", position="WR", status="Out", injury="Knee",
             practice_status="", expected_return="", updated="", comment="", source="espn")
        for i in range(15)
    ])
    s = T.team_summary(_games(), 2026, 1, injuries=inj).set_index("team")
    text = s.loc["KC", "injured_list"]
    assert text.count(";") == 12 and text.endswith("+3 more")
    assert s.loc["KC", "n_injured"] == 15 and s.loc["KC", "n_out"] == 15


# ── bundle never raises ───────────────────────────────────────────

def test_bundle_degrades_when_everything_is_down(monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("feed down")
    monkeypatch.setattr(T, "roster_table", boom)
    monkeypatch.setattr(T, "injury_table", boom)
    out = T.team_stats_bundle(_games(), 2026, 1)
    assert out["sources"] == {"roster": "none", "injuries": "none"}
    assert len(out["summary"]) == 32 and len(out["records"]) == 32
    assert out["roster"].empty and out["injuries"].empty
    assert "WARNING" in capsys.readouterr().out
