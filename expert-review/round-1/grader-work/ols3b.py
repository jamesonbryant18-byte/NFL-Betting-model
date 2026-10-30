"""3b: OLS of result on (closing line, model) and on (line, model - line), 2021-25 hold-out, classical SEs."""
import numpy as np, pandas as pd
d = pd.read_parquet('../work/holdout.parquet'); H = d[d.season.between(2021, 2025)]
def ols(y, X, names):
    X = np.column_stack([np.ones(len(y))] + X); b = np.linalg.lstsq(X, y, rcond=None)[0]
    r = y - X @ b; s2 = r @ r / (len(y) - X.shape[1]); se = np.sqrt(np.diag(s2 * np.linalg.inv(X.T @ X)))
    return ', '.join(f'{n} {bi:+.3f} (se {si:.3f}, t {bi/si:+.2f})' for n, bi, si in zip(['const'] + names, b, se))
for nm, m in (('deployed (facA)', H.projA), ('deployed LIVE weights (in-sample)', H.base + H.st + H.trend + H.fac_live),
              ('frozen base', H.base), ('base+trend', H.base + H.trend)):
    print(nm); y = H.result.to_numpy(float); L = H.spread_line.to_numpy(float); M = m.to_numpy(float)
    print('   result ~ line + model:      ', ols(y, [L, M], ['line', 'model']))
    print('   result ~ line + (model-line):', ols(y, [L, M - L], ['line', 'model-line']))
