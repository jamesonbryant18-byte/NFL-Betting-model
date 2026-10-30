"""Drop-one ablation of the deployed stack on 2021-25 (grader reconstruction)."""
import sys, json
sys.path.insert(0, 'src'); sys.path.insert(0, 'scripts'); sys.path.insert(0, '../work')
import numpy as np, pandas as pd
from nflmodel.trends import margin_model_for_history, win_probs, calibrate
from metrics import *
import adjust_lab as al

d = pd.read_parquet('../work/holdout.parquet')
H = d[d.season.between(2021, 2025)].reset_index(drop=True)
full_wf = pd.read_parquet('../work/wf_full.parquet')
chk = H[['game_id', 'base']].merge(full_wf[['game_id', 'projected_margin']], on='game_id')
print('self-tune mode:', 'live closed loop' if (len(sys.argv)>1 and sys.argv[1]=='live_st') else 'adjust_lab', 'weights:', sys.argv[2] if len(sys.argv)>2 else 'facA'); print('rerun vs cached base: max abs diff', float((chk.base - chk.projected_margin).abs().max()))

mm = margin_model_for_history()
B_DISC = json.load(open('data/trends.json'))['calibration']['disc_fit']['b']
tg = al.team_game_stats(range(2021, 2026))

def selftune(base_series):
    x = H.copy(); x['projected_margin'] = base_series.to_numpy()
    x = x.drop(columns=[c for c in x.columns if c.startswith(('home_off', 'away_off', 'home_ints', 'away_ints', 'home_fl', 'away_fl', 'epa_margin', 'to_margin', 'fl_margin'))])
    x = al.attach(x, tg)
    return al.run(x, 'epa', 1.0, half_life=3.0, clip=14.0, max_adj=0.5)['adj'].to_numpy()

def selftune_live(base_series, fac_series):
    """Closed loop like selftune.live_corrections: learns EPA margin - (shipped minus trend)."""
    from collections import defaultdict
    x = H.copy(); x['projected_margin'] = np.asarray(base_series, float)
    x = x.drop(columns=[c for c in x.columns if c.startswith(('home_off', 'away_off', 'home_ints', 'away_ints', 'home_fl', 'away_fl', 'epa_margin', 'to_margin', 'fl_margin'))])
    x = al.attach(x, tg)
    fac = np.asarray(fac_series, float) * np.ones(len(x))
    decay = 0.5 ** (1 / 3.0)
    adj = np.zeros(len(x))
    for season, sdf in x.groupby('season', sort=True):
        mem = defaultdict(list)
        for wk, wdf in sdf.groupby('week', sort=True):
            def corr(t):
                o = mem.get(t)
                if not o: return 0.0
                w = np.array([decay ** (wk - a) for a, _ in o]); v = np.array([r for _, r in o])
                return float((w * v).sum() / w.sum())
            new = []
            for i, g in wdf.iterrows():
                a = float(np.clip(corr(g.home_team) - corr(g.away_team), -0.5, 0.5))
                adj[i] = a
                r = g.epa_margin - (g.projected_margin + a + fac[i])
                if pd.notna(r):
                    new.append((g.home_team, g.away_team, float(np.clip(r, -14, 14))))
            for h_, a_, r in new:
                mem[h_].append((wk, r)); mem[a_].append((wk, -r))
    return adj

def trend_of(base_series):
    g = base_series - H.spread_line
    return np.where(g.abs() >= 3, -1.5 * np.sign(g), 0.0)

LIVE_ST = len(sys.argv) > 1 and sys.argv[1] == 'live_st'
WSET = sys.argv[2] if len(sys.argv) > 2 else 'facA'
def stack(base=None, st=True, trend=True, inj=True, epa=True, rest=True, recal=True):
    b = H.base if base is None else base
    fsum = (H[f'{WSET}_inj_total'] if inj else 0) + (H[f'{WSET}_eff_epa'] if epa else 0) + (H[f'{WSET}_rt_rest_diff'] if rest else 0)
    if LIVE_ST:
        s = selftune_live(b, fsum) if st else 0.0
    else:
        s = selftune(b) if (st and base is not None) else (H.st.to_numpy() if st else 0.0)
    t = trend_of(b) if trend else 0.0
    f = fsum
    proj = b + s + t + f
    p = win_probs(proj, mm)
    if recal:
        p = calibrate(p, dict(a=0.0, b=B_DISC))
    return np.asarray(proj, float), np.asarray(p, float)

wf = {v: pd.read_parquet(f'../work/wf_{v}.parquet').set_index('game_id').reindex(H.game_id).projected_margin.reset_index(drop=True)
      for v in ('no_prior', 'no_qb')}
no_hfa = H.base - np.where(H.neutral.astype(bool), 0.0, H.hfa_used)

variants = {
    'FULL deployed': stack(),
    '- market prior blend': stack(base=wf['no_prior']),
    '- joint QB fit': stack(base=wf['no_qb']),
    '- home field': stack(base=no_hfa),
    '- injuries factor': stack(inj=False),
    '- EPA/play factor': stack(epa=False),
    '- rest factor': stack(rest=False),
    '- trend pull (3pt/1.5)': stack(trend=False),
    '- EPA self-tune': stack(st=False),
    '- win% recalibration': stack(recal=False),
}
y = (H.result > 0).astype(float).to_numpy(); nt = H.result.to_numpy() != 0
res = H.result.to_numpy(); line = H.spread_line.to_numpy()
fp, fw = variants['FULL deployed']
f_err = np.abs(res - fp); f_br = (fw - y) ** 2
f_su = ((fw >= 0.5) == (res > 0)).astype(float)
rows = []
for k, (pj, pw) in variants.items():
    err = np.abs(res - pj); br = (pw - y) ** 2
    su = ((pw >= 0.5) == (res > 0)).astype(float)
    # component effect = full minus drop-one (negative MAE/Brier effect = component helps)
    dm, sem, tm = paired(f_err, err) if k != 'FULL deployed' else (0, 0, np.nan)
    db, seb, tb = paired(f_br[nt], br[nt]) if k != 'FULL deployed' else (0, 0, np.nan)
    ds, ses, ts = paired(f_su[nt], su[nt]) if k != 'FULL deployed' else (0, 0, np.nan)
    rows.append(dict(variant=k, SU=su[nt].mean(), MAE=err.mean(), Brier=br[nt].mean(),
                     comp_dSU_pts=100 * ds, t_SU=ts, comp_dMAE=dm, t_MAE=tm, comp_dBrier=db, t_Brier=tb))
out = pd.DataFrame(rows)
pd.set_option('display.width', 220)
print(out.round(4).to_string(index=False))
print("\ncomp_d* = metric(full) - metric(without component); MAE/Brier: negative = component helps; SU: positive = helps.")
print("A component HURTS if comp_dMAE t >= +2, comp_dBrier t >= +2, or comp_dSU < -0.5 pts.")
