"""10a/10b: spot-check the Week 7 workbook copy against the archive and recomputation; diff the Bet Tracker vs Week 6."""
import sys, zipfile, re
sys.path.insert(0, 'src'); sys.path.insert(0, '../work')
import numpy as np, pandas as pd, openpyxl
from nflmodel.data import load_games

WB7, WB6 = '../wb/wk07.xlsx', '../wb/wk06.xlsx'
f7 = openpyxl.load_workbook(WB7); v7 = openpyxl.load_workbook(WB7, data_only=True)
f6 = openpyxl.load_workbook(WB6); v6 = openpyxl.load_workbook(WB6, data_only=True)
g = load_games(); g = g[g.season == 2026]
checks = []


def chk(sheet, cell, shown, expect, tol=1e-6, note=''):
    if isinstance(expect, (float, int, np.floating)) and not isinstance(expect, bool):
        ok = shown is not None and abs(float(shown) - float(expect)) <= tol
    else:
        ok = str(shown).strip() == str(expect).strip()
    checks.append(dict(sheet=sheet, cell=cell, shown=shown, expected=expect, ok=ok, note=note))


# --- Picks vs picks/2026/week07_picks.csv
P = pd.read_csv('picks/2026/week07_picks.csv')
ws = v7['Picks']
for r in range(4, 18):
    mt = ws.cell(r, 4).value
    p = P[P.matchup.str.replace(' ', '') == mt.replace(' ', '')]
    if p.empty:
        checks.append(dict(sheet='Picks', cell=f'D{r}', shown=mt, expected='(not in archive)', ok=False)); continue
    p = p.iloc[0]
    chk('Picks', f'B{r}', ws.cell(r, 2).value, p.winner)
    chk('Picks', f'E{r}', ws.cell(r, 5).value, float(p.win_prob), 1e-9)
    chk('Picks', f'F{r}', ws.cell(r, 6).value, float(p.proj_margin), 1e-9)
    chk('Picks', f'G{r}', ws.cell(r, 7).value, float(p.moneyline), 0.5)
    chk('Picks', f'H{r}', ws.cell(r, 8).value, p.confidence)
    # SU pick consistent with the win prob it prints
    chk('Picks', f'E{r}>=0.5', ws.cell(r, 5).value >= 0.5, True, note='printed pick has win% >= 50')
    # actual outcome (for the record)

# --- Weekly Slate vs output/slate_2026_wk07.csv and leans archive
S = pd.read_csv('output/slate_2026_wk07.csv')
L = pd.read_csv('picks/2026/week07_leans.csv')
ws = v7['Weekly Slate']
for r in range(4, 18):
    away, home = ws.cell(r, 5).value, ws.cell(r, 6).value
    s = S[(S.home_team == home) & (S.away_team == away)].iloc[0]
    chk('Weekly Slate', f'G{r}', ws.cell(r, 7).value, float(s.away_ml), 0.5)
    chk('Weekly Slate', f'H{r}', ws.cell(r, 8).value, float(s.home_ml), 0.5)
    line = float(s.spread_line)
    shown_spread = f"{home} {-line:+.1f}"
    chk('Weekly Slate', f'I{r}', ws.cell(r, 9).value, shown_spread, note='home ticket number')
    chk('Weekly Slate', f'M{r}', ws.cell(r, 13).value, float(s.spread_edge_pts), 1e-9)
    chk('Weekly Slate', f'Q{r}', ws.cell(r, 17).value, float(s.home_win_prob), 1e-9)
    chk('Weekly Slate', f'S{r}', ws.cell(r, 19).value, s.recommendation)
    l = L[(L.home_team == home) & (L.away_team == away)]
    if len(l):
        l = l.iloc[0]
        chk('Weekly Slate', f'S{r} vs leans', ws.cell(r, 19).value, f'BET {l.bet_side}', note='archive bet_side')
        chk('Weekly Slate', f'T{r} vs leans', ws.cell(r, 20).value, float(l.bet_odds), 0.5)
        chk('Weekly Slate', f'U{r}', ws.cell(r, 21).value, 5.0, 1e-9, note='flat $5')
    # recompute edge from the printed model margin and line
    chk('Weekly Slate', f'M{r} recompute', ws.cell(r, 13).value, float(s.projected_margin) - line, 1e-9, note='edge = model margin - line')

# --- Bet Tracker: result and P&L per row vs actual games
alias = {'JAC': 'JAX', 'NY': 'NYG', 'LAR': 'LA', 'WSH': 'WAS'}
ws = v7['Bet Tracker']; wf = f7['Bet Tracker']
pnl_rows = []
for r in range(12, 40):
    wk, mt, mkt, side, line, odds, stake, res, pnl = [ws.cell(r, c).value for c in (2, 3, 4, 5, 6, 7, 8, 9, 10)]
    a, h = [alias.get(t.strip(), t.strip()) for t in mt.split('@')]
    gg = g[(g.week == wk) & (g.home_team == h) & (g.away_team == a)].iloc[0]
    tm = gg.result if side.strip().upper() == 'HOME' else -gg.result
    if mkt == 'SPREAD':
        c = tm + float(line)
    else:
        c = tm
    actual = 'W' if c > 0 else ('P' if c == 0 else 'L')
    chk('Bet Tracker', f'I{r}', res, actual, note=f'{mt} {mkt} {side} {line} -> his result vs nflverse score')
    exp_pnl = stake * (100 / abs(odds) if odds < 0 else odds / 100) if res == 'W' else (-stake if res == 'L' else 0.0)
    chk('Bet Tracker', f'J{r}', pnl, exp_pnl, 1e-6, note='P&L formula cached value')
    pnl_rows.append(dict(week=wk, mkt=mkt, odds=odds, line=line, res=res, pnl=exp_pnl, stake=stake))
B = pd.DataFrame(pnl_rows)
chk('Bet Tracker', 'B5', ws['B5'].value, len(B))
chk('Bet Tracker', 'B6', ws['B6'].value, f"{(B.res=='W').sum()}-{(B.res=='L').sum()}-{(B.res=='P').sum()}")
chk('Bet Tracker', 'B8', ws['B8'].value, B.pnl.sum(), 1e-6)
chk('Bet Tracker', 'B9', ws['B9'].value, B.pnl.sum() / B.stake.sum(), 1e-9)
chk('Bet Tracker', 'B10', ws['B10'].value, 100 + B.pnl.sum(), 1e-6)
chk('Bet Tracker', 'M5', ws['M5'].value, B.stake.sum(), 1e-9, note='his SUM(H12:H300)')
j6 = ws['J6'].value
chk('Bet Tracker', 'K6', ws['K6'].value, -round(j6 / (1 - j6) * 100) if j6 >= 0.5 else round((1 - j6) / j6 * 100), 0.5, note='his converter')
chk('Bet Tracker', 'K39', ws['K39'].value, 100 + B.pnl.sum(), 1e-6, note='running bankroll')

# --- Chart Data vs recomputation
cd = v7['Chart Data']
cum = B.pnl.cumsum().to_numpy()
for i in range(len(B)):
    chk('Chart Data', f'B{i+3}', cd.cell(i + 3, 2).value, cum[i], 1e-6, note='cumulative profit')
    dec = B.iloc[:i + 1]; dec = dec[dec.res != 'P']
    chk('Chart Data', f'C{i+3}', cd.cell(i + 3, 3).value, (dec.res == 'W').mean(), 1e-9, note='running win %')
    o = B.odds.iloc[i]
    chk('Chart Data', f'D{i+3}', cd.cell(i + 3, 4).value, (-o / (-o + 100)) if o < 0 else 100 / (o + 100), 1e-9, note='break-even of the price')
for wk in range(1, 8):
    chk('Chart Data', f'I{wk+1}', cd.cell(wk + 1, 9).value, B[B.week == wk].pnl.sum(), 1e-6, note=f'profit week {wk}')
types = {'Moneyline underdogs': (B.mkt == 'MONEYLINE') & (B.odds > 0), 'Moneyline favorites': (B.mkt == 'MONEYLINE') & (B.odds < 0),
         'Spread underdogs': (B.mkt == 'SPREAD') & (B.line.astype(float) > 0), 'Spread favorites': (B.mkt == 'SPREAD') & (B.line.astype(float) < 0)}
for r in range(2, 6):
    lab = cd.cell(r, 13).value
    chk('Chart Data', f'N{r}', cd.cell(r, 14).value, B[types[lab]].pnl.sum(), 1e-6, note=lab + ' (by typed line sign)')
chk('Chart Data', 'R2', cd['R2'].value, f"BANKROLL ${100 + B.pnl.sum():,.2f}".replace('.00', ''), note='chart title (format may differ)')

C = pd.DataFrame(checks)
pd.set_option('display.width', 250); pd.set_option('display.max_colwidth', 70)
print(f'cells checked: {len(C)}; mismatches: {int((~C.ok).sum())}')
print(C[~C.ok].to_string(index=False))
print(C.groupby('sheet').ok.agg(['size', 'sum']).to_string())

# --- 10b: Bet Tracker Week 6 vs Week 7 (rows 1-32, every cell, formulas and values)
w6, w7 = f6['Bet Tracker'], f7['Bet Tracker']
diffs = []
for r in range(1, 33):
    for c in range(1, 30):
        a, b = w6.cell(r, c).value, w7.cell(r, c).value
        if a != b:
            diffs.append((w6.cell(r, c).coordinate, a, b))
print('\nBet Tracker rows 1-32, Week 6 vs Week 7, cells that differ (formula text / typed values):', len(diffs))
for d in diffs[:30]:
    print('  ', d)
for nm, (f_, v_) in (('wk06', (f6, v6)), ('wk07', (f7, v7))):
    ws_ = f_['Bet Tracker']
    print(nm, 'charts on Bet Tracker:', [(ch.anchor._from.row, ch.anchor._from.col, (ch.title.tx.rich.p[0].r[0].t if ch.title and ch.title.tx and ch.title.tx.rich else None) if hasattr(ch, 'title') else None) for ch in ws_._charts])
for nm, path in (('wk06', WB6), ('wk07', WB7)):
    z = zipfile.ZipFile(path)
    refs = sorted(set(sum([re.findall(r'<c:f>([^<]+)</c:f>', z.read(n).decode('utf8', 'ignore')) for n in z.namelist() if n.startswith('xl/charts/chart')], [])))
    print(nm, 'chart series refs:', refs)
