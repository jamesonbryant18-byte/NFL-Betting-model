import sys
sys.path.insert(0, 'src')
import numpy as np, pandas as pd
from nflmodel import replay
from nflmodel.config import STAKING
from dataclasses import replace
from nflmodel.model import NFLModel

d = replay.deployed(); h = d[d.season.isin(replay.HOLD)]
print('missing spread odds in hold-out:', int(h.home_spread_odds.isna().sum()), int(h.away_spread_odds.isna().sum()))
card = replay.card(h)
allq = replay.card(h, model=NFLModel(staking=replace(STAKING, card_max=99, card_min=0)))  # every qualifying bet, no card cut
def summ(x):
    c = replay.card_summary(x); return f"n {c['n']:4d} won {c['win_pct']:.3f} (BE {c['break_even']:.3f}, model {c['expected_win_pct']:.3f}) ROI {c['roi']:+.3f} (SE {c['roi_se']:.3f})"
for label, bets in (('ALL QUALIFYING', allq), ('CARD (top 7)', card)):
    print('\n' + label, summ(bets))
    sp = bets[bets.market == 'SPREAD']
    for lo, hi in ((1.5, 2.0), (2.0, 2.5), (2.5, 3.0), (3.0, 99)):
        x = sp[(sp.edge >= lo) & (sp.edge < hi)]
        if len(x): print(f'   spread edge {lo}-{hi}: {summ(x)}')
    ml = bets[bets.market == 'MONEYLINE']
    for lo, hi in ((3, 5), (5, 8), (8, 100)):
        x = ml[(ml.edge >= lo) & (ml.edge < hi)]
        if len(x): print(f'   ML edge {lo}-{hi}%: {summ(x)}')
    # chance terciles (the card's ranking)
    q = pd.qcut(bets.chance, 3, labels=['low', 'mid', 'high'])
    for k in ('low', 'mid', 'high'):
        print(f'   chance tercile {k}: {summ(bets[q == k])}')
