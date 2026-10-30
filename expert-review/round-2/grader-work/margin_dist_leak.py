import sys
sys.path.insert(0, 'src')
import numpy as np, pandas as pd
from nflmodel import replay, trends
from nflmodel.config import CACHE_DIR, MARKET
from nflmodel.market import MarginModel
ds = pd.read_parquet(CACHE_DIR / 'dataset_2010_2025.parquet')
mm_old = MarginModel(residuals=np.load(CACHE_DIR / 'residuals.npy'), sigma=MARKET.margin_sigma,
                     margins=ds.loc[ds.result.notna() & (ds.season <= 2020), 'result'].to_numpy())
base = replay.deployed()
# patch the margin model used by replay/win_probs
orig = trends.margin_model_for_history
trends.margin_model_for_history = lambda: mm_old
replay.margin_model_for_history = lambda: mm_old
alt = replay.deployed()
for name, d in (('margins 2010-2025 (repo)', base), ('margins 2010-2020 only', alt)):
    h = d[d.season.isin(replay.HOLD)]
    s = replay.scorecard(h)
    t = replay.calibration_table(h, bins=[0.5,.55,.6,.65,.7,.75,.8,.85,.9,.95,1.01])
    t['gap'] = (100*(t.won - t.said)).round(2)
    c = replay.card_summary(replay.card(h))
    print(name, 'slope b', round(d.attrs['win_slope'], 3), 'SU', round(s['su_model'], 4), 'Brier', round(s['brier_model'], 5),
          'cal slope', round(s['calibration_slope'], 3), 'card ROI', round(c['roi'], 4), 'n', c['n'])
    print('   gaps by 5-pt bucket:', list(zip(t.n, t.gap)))
