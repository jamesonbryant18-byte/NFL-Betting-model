"""The canonical replay's win-% side is walk-forward (expert review round 2, 2026-10-29)."""
import sys
sys.path.insert(0, "src")

import numpy as np


def test_holdout_season_never_sees_its_own_results():
    from nflmodel import replay
    d = replay.load()
    d = d[d.season.between(2013, 2023)].copy()
    d["proj"] = d.base
    plan = replay.win_plan(d)
    # tuning seasons share the 2013-2020 fit; each later season uses earlier seasons only
    assert {plan[s][1] for s in range(2013, 2021)} == {2020}
    assert plan[2021][1] == 2020 and plan[2022][1] == 2021 and plan[2023][1] == 2022
    assert plan[2022][0] == replay.fit_win_slope(d, "proj", range(2013, 2022))
    # a table cut at 2020 is built from fewer games than the full one
    assert not np.allclose(replay.margin_model(2020)._p0, replay.margin_model()._p0)


def test_apply_win_pct_uses_each_seasons_own_plan():
    from nflmodel import replay
    d = replay.load()
    d = d[d.season.isin([2021, 2022])].copy()
    plan = {2021: (1.3, 2020), 2022: (None, 2021)}
    wp = replay.apply_win_pct(d, d.base, plan)
    m21 = (d.season == 2021).to_numpy()
    assert np.allclose(wp[m21], replay.win_pct(d.base[m21], 1.3, replay.margin_model(2020)))
    assert np.allclose(wp[~m21], replay.win_pct(d.base[~m21], None, replay.margin_model(2021)))
