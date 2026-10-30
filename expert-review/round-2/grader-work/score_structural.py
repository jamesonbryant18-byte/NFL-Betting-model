import sys
sys.path.insert(0, 'src')
import numpy as np, pandas as pd
from nflmodel import replay

v = pd.read_parquet(sys.argv[1])
d0 = replay.load()
x = d0[['game_id']].merge(v, on='game_id', how='left')
print('full variant vs cache max |diff|:', float(np.nanmax(np.abs(x.full.to_numpy() - d0.base.to_numpy()))), 'missing', int(x.full.isna().sum()))

full = replay.deployed()
b_full = full.attrs['win_slope']
H = full.season.isin(replay.HOLD).to_numpy()
res = full.result.to_numpy(float)[H]
dec = res != 0
y = (res > 0).astype(float)
mkt = replay.market_wp(full[H])
okb = dec & ~np.isnan(mkt)

def metrics(dd, fixed_b=None):
    h = dd[H]
    wp = h.wp.to_numpy(float) if fixed_b is None else replay.win_pct(h.proj, fixed_b)
    su = ((wp >= 0.5) == (res > 0)).astype(float)
    err = np.abs(res - h.proj.to_numpy(float))
    br = (wp - y) ** 2
    card = replay.card_summary(replay.card(h.assign(wp=wp)))
    return su, err, br, card, wp

fsu, ferr, fbr, fcard, fwp = metrics(full)
rows = [dict(variant='FULL', SU=100*fsu[dec].mean(), MAE=ferr.mean(), Brier=fbr[okb].mean(), ROI=100*fcard['roi'], n_bets=fcard['n'],
             slope=b_full, w=str({k: round(v_, 3) for k, v_ in full.attrs['factor_weights'].items()}))]
variants = {
    'no market prior': x.noprior.to_numpy(),
    'no joint QB fit (team-only)': x.noqb.to_numpy(),
    'no home field': (x.full - x.hfa_full).to_numpy(),
}
for name, base in variants.items():
    dd = d0.copy(); dd['base'] = base
    dv = replay.deployed(d=dd)
    for label, fb in ((name + ' [refit slope]', None), (name + ' [slope held]', b_full)):
        su, err, br, card, wp = metrics(dv, fb)
        dsu, sesu, _ = replay._paired(fsu[dec], su[dec])
        dm, sem, _ = replay._paired(ferr, err)
        db, seb, _ = replay._paired(fbr[okb], br[okb])
        rows.append(dict(variant=label, SU=100*su[dec].mean(), MAE=err.mean(), Brier=br[okb].mean(), ROI=100*card['roi'], n_bets=card['n'],
                         slope=dv.attrs['win_slope'] if fb is None else fb,
                         w=str({k: round(v_, 3) for k, v_ in dv.attrs['factor_weights'].items()}),
                         piece_dSU=100*dsu, piece_tSU=dsu/sesu, piece_dMAE=dm, piece_tMAE=dm/sem, piece_dBrier=db, piece_tBrier=db/seb))
pd.set_option('display.width', 250)
print(pd.DataFrame(rows).round(4).to_string(index=False))
print('piece_* = full minus variant (what the piece itself does): SU + helps; MAE/Brier - helps')
