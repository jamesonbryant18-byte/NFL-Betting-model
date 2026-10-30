import sys
sys.path.insert(0, 'src')
import numpy as np, pandas as pd
from nflmodel.trends import margin_model_for_history
from nflmodel.scorecard import value_at_price
from nflmodel.closing import model_card, load_closing, close_for, ticket
mm = margin_model_for_history()
rows = []
for wk in range(1, 8):
    card = model_card(2026, wk); C = load_closing(2026, wk)
    for _, l in card.iterrows():
        side = l.bet_side; bh = side.split()[0] == l.home_team
        cr = close_for(C, l.home_team, l.away_team)
        ev, p = value_at_price(mm, l.bet_market, bh, ticket(side) if l.bet_market == 'SPREAD' else None, float(l.bet_odds), cr)
        rows.append(dict(week=wk, bet=side, market=l.bet_market, odds=l.bet_odds, ev=ev, src=l.card_source))
d = pd.DataFrame(rows)
x = d.ev.astype(float)
print(f'first-published card: n {len(x)} value {x.mean():+.4f} SD {x.std(ddof=1):.4f} t {x.mean()/(x.std(ddof=1)/np.sqrt(len(x))):+.2f}')
i = x.idxmax(); y = x.drop(i)
print(f'  without largest ({d.bet[i]} wk{d.week[i]} {x[i]:+.3f}): {y.mean():+.4f} t {y.mean()/(y.std(ddof=1)/np.sqrt(len(y))):+.2f}')
print(d[d.week >= 5].round(3).to_string())
