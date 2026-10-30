# Grade Report

Total: 40 / 100 | Confidence: medium | Self-graded: no

Project: NFL Betting Model, 2026 Weeks 1-7, graded 2026-10-28 against Rubric v1 (locked 2026-10-28). Scratch copy: `/private/tmp/claude-501/-Users-jameson/f8af9ddc-e116-402b-81c6-f976dc266c74/scratchpad/grader-r1/NFL-Betting-model` (git status clean after every run). The real project's workbooks were re-hashed at the end and are unchanged (`work/real_output_abs.sha`, all OK).

**How every number below was produced.** Scripts and outputs are in `/private/tmp/claude-501/-Users-jameson/f8af9ddc-e116-402b-81c6-f976dc266c74/scratchpad/grader-r1/work/`. Each was run from the scratch-copy root as `$PY ../work/<script>.py`, with `PY="/Users/jameson/Desktop/NFL-Betting-model/.venv/bin/python -W ignore"`. Repo scripts were run as `$PY scripts/<name>.py`.

**Hold-out and live definitions.**
- Hold-out = 2021-25, 1,424 games (1,420 after 4 ties; 0 pick'em).
- "Deployed reconstruction" (`build_holdout.py`, then `crit12.py`) stacks the following on 2021-25:
  - the frozen walk-forward base (`data/cache/base_projections_2013_2025.parquet`; a from-scratch walk-forward rerun matches it exactly);
  - the EPA self-tune (`adjust_lab.run`, cap 0.5);
  - the live trend pull (−1.5 toward the line when |base − line| ≥ 3);
  - the three live factors, with weights refit on 2013-20 only (ridge α 300: injuries 0.512, EPA/play 1.866, rest 0.044);
  - the win-% recalibration with the 2013-20 `disc_fit` b = 1.535.
- Live = the `picks/2026/` archive, scored against FanDuel closes in `weekNN_closing.csv`.

## Score by criterion

| # | Criterion | Score | Max |
|---|---|---|---|
| **1** | **Straight-up accuracy vs simply taking the favorite** | **3** | **15** |
| 1a | Hold-out SU vs the closing favorite | 1 | 7 |
| 1b | The straight-up pick rule | 0 | 4 |
| 1c | Live SU tracking and explanation | 2 | 4 |
| **2** | **Margin and win-probability accuracy vs the market** | **5** | **12** |
| 2a | Margin error vs the closing line | 3 | 4 |
| 2b | Win probability vs the de-vigged market | 2 | 4 |
| 2c | Calibration | 0 | 4 |
| **3** | **Model design: does every live piece earn its place?** | **2** | **10** |
| 3a | Component ablation on the hold-out | 0 | 5 |
| 3b | Information beyond the line | 2 | 3 |
| 3c | Structural soundness | 0 | 2 |
| **4** | **Validation rigor and leakage** | **4** | **8** |
| 4a | Leak-free hold-out, honest reporting | 2 | 4 |
| 4b | Reproducibility | 2 | 4 |
| **5** | **Live bets: good bets or lucky ones?** | **3** | **12** |
| 5a | Logging completeness | 1 | 3 |
| 5b | Luck vs skill accounting | 1 | 5 |
| 5c | Closing line value | 1 | 4 |
| **6** | **Bet selection logic** | **5** | **12** |
| 6a | Hold-out profitability of the selection rules | 2 | 6 |
| 6b | Bigger edges / edge math | 2 | 4 |
| 6c | His own betting choices | 1 | 2 |
| **7** | **Locked choices work as designed (bug check)** | **3** | **3** |
| **8** | **Input correctness at the time he bets** | **3** | **10** |
| 8a | Quarterback starters | 1 | 5 |
| 8b | Injuries and late news by game day | 1 | 3 |
| 8c | Prices match what he can bet | 1 | 2 |
| **9** | **Process reliability and safeguards** | **4** | **8** |
| 9a | Weekly procedure produces the right files | 2 | 4 |
| 9b | Tests and guards | 2 | 4 |
| **10** | **Workbook correct, carried, usable and honest** | **8** | **10** |
| 10a | Numbers and formulas correct | 4 | 4 |
| 10b | His Bet Tracker carried and charts updated | 3 | 3 |
| 10c | Usable and honest | 1 | 3 |
| | **Total** | **40** | **100** |

---

## 1. Straight-up accuracy vs simply taking the favorite (3 / 15)

### 1a. Hold-out straight-up vs the closing favorite: 1 / 7

**Evidence**
- `$PY ../work/crit12.py` (output in `crit12.out`) runs the deployed reconstruction on 2021-25.
  - The model picked 927 of 1,420 winners (65.28%). The closing favorite picked 944 (66.48%) on the same games.
  - Excluded: 0 pick'em, 4 ties.
  - Paired difference −1.20 pts (SE 0.82, t −1.46).
- By season (model minus favorite): 2021 −1.06, 2022 −3.19, 2023 −0.70, 2024 −1.05, 2025 0.00. The model is behind or level in every season.
- Sensitivity:
  - Weights refit on 2013-20 against the post-trend target: −1.27 pts (t −1.59).
  - Frozen base alone: −2.04 pts (t −2.16).
  - Live weights (fit through 2025, so in-sample and not a result): −0.14 pts.
- The repo has no same-games favorite comparison. `factor_lab.py` and `grade.py` report only raw SU (64.4% on the hold-out).

**What's costing points:** the model is 1.20 pts below the favorite, which falls in the "1.0 to 2.0 below" band. Taking the favorite every game would have picked 17 more winners over five seasons. The comparison also cannot be reproduced from the repo.

**Confidence:** medium-high. This is my reconstruction, but both 2013-20 weight variants land in the same band (−1.20 / −1.27).

### 1b. The straight-up pick rule: 0 / 4

**Evidence**
- Hold-out (`crit12.out`): the model went against the closing favorite in 135 games and won 59 of them (43.7%).
- Alternative rules on the same 1,420 games:

| Rule | SU % |
|---|---|
| Model only (deployed) | 65.28% |
| Favorite only | 66.48% |
| Go against the favorite only when the model's p is beyond 0.58-0.65 | 66.6-66.7% |
| 0.35 model + 0.65 de-vigged market | 67.11% (953/1,420) |

  The blend weight was picked on the hold-out itself, so its 67.11% is optimistic.
- Live (`$PY ../work/live.py`, output in `live_fixed.out`):
  - Against the favorite at publication: 7 picks, 2 won.
  - Against the FanDuel close: 9 picks, 3 won.
- No alternative pick rule is tested anywhere in `scripts/`, `IMPROVEMENT.md` or `README.md`.

**What's costing points:** picks against the favorite win under 45% on the hold-out, and no alternative rule was ever tested.

**Confidence:** high.

### 1c. Live straight-up tracking and explanation: 2 / 4

**Evidence**
- `scripts/review_week.py` (code read only; it locks weeks) prints:
  - SU against an expected-wins 95% band;
  - tier calibration with bands;
  - card leans against a coin-flip band.
- `$PY scripts/grade.py` (output in `grade.out`) prints "straight up 64-43 (59.8%)", average error 9.59 vs close 9.41, and a tier table. It has no favorite baseline.
- `scripts/miss_report.py --no-save` gives a luck-vs-model verdict for misses.
- The favorite baseline shows up only as ad-hoc notes in CLAUDE.md, for example Week 6: "FanDuel's closing favorites went 7-6".
- Grader recomputation (`live.py`): the model went 64 of 106 (60.4%; 1 tie out).
  - The publication favorite also went 67 of 106: −2.8 pts (SE 2.5).
  - The FanDuel closing favorite went 67 of 106: −2.8 pts (SE 2.8).
  - The model expected 67.7 ± 9.5 wins (95%).

**What's costing points:** there is no systematic SU-vs-favorite baseline at publication and at close with an uncertainty band. Misses where the model went against the favorite are not systematically classified as input error, model view or noise.

**Confidence:** high.

## 2. Margin and win-probability accuracy vs the market (5 / 12)

### 2a. Margin error vs the closing line: 3 / 4

**Evidence**
- Hold-out (`crit12.out`): MAE 9.899 vs closing line 9.762, +0.137 (SE 0.053, t +2.57). Frozen base alone: 10.079 (+0.317).
- The model is worse than the line in every season:

| Season | Model MAE | Line MAE |
|---|---|---|
| 2021 | 10.794 | 10.667 |
| 2022 | 8.986 | 8.783 |
| 2023 | 10.114 | 9.984 |
| 2024 | 9.775 | 9.704 |
| 2025 | 9.825 | 9.670 |

- Live (`live.py`): 9.594 vs FanDuel close 9.439, +0.155 (t +0.94, n=107).

**What's costing points:** 0.137 pts worse than the close, which falls in the "within 0.15 worse" band, and worse in all five seasons.

**Confidence:** high.

### 2b. Win probability vs the de-vigged market: 2 / 4

**Evidence**
- Hold-out (`crit12.out`), n=1,420; the market is de-vigged multiplicatively from the matched closing ML pair:
  - Brier: model 0.2162 vs market 0.2115, +0.0047 (t +2.69).
  - Log loss: 0.6216 vs 0.6103.
  - Without the recalibration: +0.0052.
- Live (`live.py`, n=104 games with both FanDuel close prices): Brier 0.2352 vs 0.2343 (+0.0009, t +0.15); log loss 0.6650 vs 0.6649.

**What's costing points:** Brier is 0.0047 worse, which falls in the 0.002-0.005 band.

**Confidence:** high. The result sits close to the 0.005 boundary.

### 2c. Calibration: 0 / 4

**Evidence**
- Hold-out (`crit12.out`):
  - Home-side calibration slope 0.855 (SE 0.067); picked-side slope 0.863 (SE 0.107).
  - Two picked-side buckets with n ≥ 100 are more than 6 pts off:
    - (0.65, 0.70], n=184: said 67.5%, won 58.7% (−8.8 pts).
    - (0.80, 0.85], n=136: said 82.4%, won 72.8% (−9.6 pts).
  - The other buckets are within about 3 pts.
  - The market's slope on the same games is 1.059.
- Cause: the recalibration factor (b = 1.535 hold-out, 1.483 live) was fit on base+trend probabilities, where the slope is 0.956. It is then applied on top of the factors and self-tune, which already widen the margins.
  - Without the recal, the deployed slope is 1.31.
  - With the live b it is 0.885, still with two buckets more than 6 pts off.
- Live: `review_week.py` prints tiers with counts and 95% bands (code read). In `live.py`, all picked-side buckets (n=3-25) fall inside their bands.

**What's costing points:** slope below 0.90 and two large buckets about 9 pts overconfident, which is the zero anchor.

**Confidence:** medium-high.

## 3. Model design: does every live piece earn its place? (2 / 10)

### 3a. Component ablation on the hold-out: 0 / 5

**Evidence**
- `$PY ../work/ablation.py live_st facA` (output in `ablation.out`) removes one component at a time from the deployed reconstruction.
- The market-prior and QB rows come from walk-forward reruns (`wf_ablate.py`). Its full rerun matches the cached base exactly ("max abs diff 0.0").
- Effect = full model minus the model without the component. For MAE and Brier, negative means the component helps; for SU, positive means it helps.

| Live component | Effect on SU (pts) | Effect on MAE (t) | Effect on Brier (t) | Rubric reading |
|---|---|---|---|---|
| Market-prior blend | −0.63 (t −1.19) | −0.062 (−2.49) | −0.0015 (−1.79) | Helps MAE; trips the "SU down > 0.5" test |
| Joint QB fit | +0.07 | −0.033 (−1.11) | −0.0007 (−0.77) | Neutral/helps |
| Home field | −0.35 | −0.021 (−0.54) | +0.0010 (+0.83) | Neutral |
| Injuries factor | −0.35 | −0.069 (−2.49) | −0.0016 (−1.88) | Helps |
| **EPA/play factor** | −0.42 | +0.016 (+1.86) | **+0.0006 (+2.51)** | **Hurts** (Brier) |
| Rest factor | +0.14 | −0.000 | +0.0000 | Does nothing |
| Trend pull | +0.49 | −0.097 (−5.11) | −0.0030 (−5.08) | Helps |
| **EPA self-tune** | **−0.85 (t −2.06)** | −0.001 | 0.0000 | **Hurts** (SU) |
| Win-% recalibration | 0.00 | 0 | −0.0005 (−0.33) | Neutral |

- The EPA/play factor hurts Brier at t 2.1-2.5 in every weight variant, including the in-sample live weights.
- The repo's own `factor_lab.py` (output in `factor_lab.out`) rates efficiency "no help" (SU −0.5, error 0.014 worse) and rest/travel "no help", yet both run live. Only injuries is rated "CANDIDATE".
- The repo's self-tune grid matches my standalone check (−0.015 MAE, SU 0). The repo never tested the self-tune on top of the factors, and never ablated the stack as a whole.

**What's costing points:** two or more live components measurably hurt: the EPA/play factor (Brier t +2.5) and the EPA self-tune (SU −0.85). The market-prior blend also trips the SU test.

**Confidence:** medium-high. These are my reconstructions; the EPA/play result holds across all variants.

### 3b. Information beyond the line: 2 / 3

**Evidence:** `$PY ../work/ols3b.py` (output in `ols3b.out`), OLS on 2021-25 with classical SEs:

| Model | Regression | Model coefficient | Line coefficient |
|---|---|---|---|
| Deployed | result ~ line + model | +0.295 (SE 0.156, t +1.89) | +0.774 (SE 0.158) |
| Deployed | result ~ line + (model − line) | +0.295 (t +1.89) | +1.069 (SE 0.056) |
| Live weights (in-sample, not a result) | result ~ line + model | +0.360 (t +2.43) | — |
| Frozen base | result ~ line + model | −0.005 (t −0.03) | — |

The frozen-base result is consistent with the repo's documented −0.018 (t −0.1).

**What's costing points:** the deployed model's coefficient is positive but t < 2. The deployed stack actually does better than the repo claims: the workbook still says "zero information beyond the line", which is the base-only number.

**Confidence:** high.

### 3c. Structural soundness: 0 / 2

**Evidence**
- (i) QB double counting: identified in the documentation, never measured.
- (ii) Trend cliff at exactly 3 pts: identified (commit 80b5311 "flag the 3-pt trend-fix cliff"), not measured.
- (iii) Replacement-level QBs: kept as a watch item (miss report −1.0 / −0.9), not measured as an effect or corrected.
- (iv) Live/replay mismatch:
  - The `ratings.fit_market_ratings` docstring says that live "is harmless -- only this week's lines exist yet". The replay's `asof_week` guard drops the current week's games once they are played.
  - `$PY ../work/prior_mismatch.py` (output in `prior_mismatch.out`) rebuilds the 2021-25 prior the way live sees it (current week's lines included):
    - Projections move by 0.34 pts on average: 0.81 in weeks 1-2, 0.74 in weeks 3-4.
    - MAE changes from 10.079 to 10.022 (t −3.40).
    - Games where the model is 3+ pts off the line drop from 339 to 253.
  - The 2026 loader already holds lines for week 8 (14 games) and week 9 (15 games). So the live prior also uses future weeks' lines, which contradicts the docstring.

**What's costing points:** (iv) is not identified as a mismatch. It is asserted harmless and is measurably not. As a result, the hold-out numbers describe a model that differs from the one running live.

**Confidence:** medium.

## 4. Validation rigor and leakage (4 / 8)

### 4a. Leak-free hold-out, honest reporting: 2 / 4

**Evidence**
- No data leak found:
  - EPA timing: `$PY ../work/epa_timing.py 2023 10` and `... 2025 3` truncate the season after that week and corrupt the week's own EPA. That week's `o_epa` / `d_epa` features change by at most 5.6e-17.
  - Injury inputs (ad-hoc join to same-week snaps): 1 of 27,791 roster-unavailable rows and 6 of 6,238 Out/Doubtful rows show same-week snaps, which is negligible.
  - The market-prior as-of guard is covered by `test_market_ratings_respect_asof_cutoff` and `test_deployed_model_is_leak_free`.
- The 2021-25 seasons were reused for selection decisions, not only scored:
  - The weekly card rule was chosen on them (config comment: "2021-25 hold-out ... top 7 ... -0.7%").
  - Factor families were selected on them in `factor_lab`.
  - Trend-fix prune/confirm and calibration confirm read "2021+".
  - The live factor weights are fit through 2025.

**What's costing points:** the hold-out has been used to pick rules, so it is not fully clean.

**Confidence:** medium.

### 4b. Reproducibility: 2 / 4

**Evidence**
- `$PY scripts/factor_lab.py` (output in `factor_lab.out`) reproduces the documented numbers:

| Measure | Reproduced | Documented (README / workbook) |
|---|---|---|
| SU | 64.4% | — |
| MAE | 10.079 | 10.08 |
| Closing-line MAE | 9.762 | 9.76 |
| ATS | 50.1% on 762 | 50.1% |
| ML ROI | −7.4% on 702 | — |

- The walk-forward rerun equals the cached base exactly. The rerun without the prior gives MAE 10.154.
- Caches are stale against the live loader: with today's `load_games` the MAE is 10.085 instead of 10.079, and there are 66 QB-name mismatches. CLAUDE.md section 9 acknowledges this.

**What's costing points:** the caches are not consistent with the live data loader.

**Confidence:** high.

## 5. Live bets: good bets or lucky ones? (3 / 12)

### 5a. Logging completeness: 1 / 3

**Evidence**
- `weekNN_leans.csv` has game, market, side, number, price, the moneyline pair, home win % and `odds_source`.
- Missing from the archive:
  - The stake (only in `output/slate_*.csv`).
  - The spread bet's cover probability, and the spread juice needed to de-vig the spread market (slate CSV only).
- First-published numbers exist only for Weeks 5-7; Weeks 1-4 are backfilled from the final card.
- Closes are FanDuel except three:
  - Wk2 JAX @ DEN and Wk4 IND @ WAS: DraftKings.
  - Wk4 ARI @ NYG: nflverse DraftKings. This game is a card bet (NYG +118).
- His tracker: Closing Line, Closing Odds and Model Edge are blank on all 28 rows, so the tracker's CLV cells (E4/G4) are empty.

**What's costing points:** more than two fields are missing or backfilled.

**Confidence:** high.

### 5b. Luck vs skill accounting: 1 / 5

**Evidence**
- What the repo reports:
  - `review_week.py`: the card record, a coin-flip band and season CLV.
  - `grade.py`: "VALUE PICKS 25-19-1 (57%)" with a "low hit rate is their expected shape" caveat.
  - A one-off CLAUDE.md note for the Week 7 card ("expected about 3.3 wins").
  - Not reported anywhere: season-level expected wins under the model's or the market's probabilities, ROI against the break-even of the prices taken, or slices.
- Grader, model card Weeks 1-7 at 1 unit (`$PY ../work/bets_live.py`, output in `bets_live.out`):

| Measure | Value |
|---|---|
| Bets / record | 45 bets, 25-19-1 |
| Profit | +7.20 units, ROI +16.0% (SE 16.9%) |
| Expected wins under the model | 24.3 ± 3.2 (actual 25) |
| Expected wins under the de-vigged market at publication | 20.6 ± 3.2 (n=42; actual 23) |
| Expected wins under the de-vigged market at close | 21.8 ± 3.2 (actual 25) |
| Break-even of prices taken vs actual win rate | 51.1% vs 56.8% |
| By market | Spreads 13-8 (ROI +17.5%); moneylines 12-11 (+14.5%) |
| By side | Favorite side 10-6; underdog side 15-13 |
| Spread edge buckets | 0-2 pts: 3/5; 2-3 pts: 5/11; 3+ pts: 5/6 |
| ML edge buckets | 0-5%: 7/11; 5-8%: 4/10; 8%+: 1/2 |

  The card is about one SD above what the closing market expected (25 vs 21.8 ± 3.2), which is consistent with luck.
- His tracker (`clv_move.py`): 28 bets, 20-8, +$46.13 on $140 (+32.9%). His prices' break-even is 56.3%; he won 71.4%.

**What's costing points:** the repo gives a record and a generic coin-flip band. None of the expected-wins, break-even or slice accounting the rubric asks for exists.

**Confidence:** high.

### 5c. Closing line value: 1 / 4

**Evidence**
- How the repo measures CLV (`closing.card_clv`, `betlog.clv_for_row`, `review_week._grade_bet`):
  - Spreads: (number taken − close) × per-point value from the key-number table. This part is fine.
  - Moneylines: raw implied-probability difference, not de-vigged.
  - His spread CLV is in raw points, so bought alt lines count as CLV (for example CIN +2.5 at −199 reads +5.5; the repo notes this one).
  - The NYG +118 card bet is scored against a DraftKings close.
  - Weeks 1-4 are scored from the final card, not the first-published number.
- Repo numbers (`bets_live.out`, "REPO CLV"):
  - Spreads: +0.326 pts (n=23, t +0.97); in probability +1.48% (t +1.63).
  - Moneylines: +0.07% (n=26, t +0.19).
- Grader, correct method (`$PY ../work/clv_move.py`, output in `clv_move.out`):
  - From the published number, n=49: +0.75% (SD 3.35%, t +1.56).
    - Spreads +1.48% (t +1.63; +0.33 pts).
    - Moneylines, de-vigged: +0.10% (t +0.27).
  - Without the largest news-driven move (CIN +2.5, Wk7, Lamar ruled out, +12.6%): +0.50% (t +1.20).
  - From the final card number, n=45: +0.64% (t +1.74).
- The beat is smaller than the vig. Closing EV at the price taken (de-vigged FanDuel close, key-number aware), from `bets_live.out`:
  - −2.77% per bet (t −3.56).
  - −2.88% (t −3.28) from first-published numbers.
  - Moneylines alone: −3.41% (t −3.92).

**What's costing points:** CLV is measured with method errors: moneylines not de-vigged, one mixed-book close, alt lines counted as CLV. Measured correctly, it would score 3: positive but not significant. Either way the bets do not beat the close by enough to cover the vig.

**Confidence:** medium. The score depends on how strictly "method errors" is read.

## 6. Bet selection logic (5 / 12)

### 6a. Hold-out profitability of the selection rules: 2 / 6

**Evidence**
- `$PY ../work/replay66.py primary` (output in `replay66_primary.out`) replays the deployed rules on 2021-25, picking and settling at nflverse closing lines and real juice. It mirrors `model._recommend` and `model._weekly_card`:
  - Spread edge ≥ 1.5 pts, priced at real juice.
  - Moneyline edge ≥ 3% against the multiplicative de-vig, with −350/+250 caps.
  - Half-Kelly ≥ $5 qualification; spread preferred when both qualify.
  - Top 7 by bet chance, topped up to 4 with positive-EV near misses.
- Results:

| Slice | Bets | Record | Win % vs break-even | ROI (SE) |
|---|---|---|---|---|
| Card, all | 665 | 376-279-10 | 57.4% vs 57.5% | +0.02% (3.40); 95% CI −6.6% to +6.7% |
| Card, spreads | 388 | — | 52.9% vs 52.1% | +1.5% (4.8) |
| Card, moneylines | 277 | — | 63.5% vs 65.0% | −2.1% (4.6) |
| All qualifying, no card cap | 873 | — | — | −1.3% (3.1) |

- By season: 2021 −5.3%, 2022 +0.8%, 2023 +1.9%, 2024 +6.5%, 2025 −4.1%.
- The model said its card bets would win 63.0%; they won 57.4%, about 3 SE overconfident.
- Sensitivity:
  - 2013-20 weights fit on the post-trend target: −0.29%.
  - Base+trend only: −0.35%.
  - Live weights (in-sample, not a result): +3.95%.
  - The repo's own figure (config comment and CLAUDE.md, no script in the repo): −0.7% (SE about 3.5%).

**What's costing points:** ROI is indistinguishable from zero. The clean reconstructions straddle 0 (+0.02, −0.29, −0.35, repo −0.7), so I took the lower band ("between −3% and 0").

**Confidence:** medium.

### 6b. Do bigger edges mean better bets? Is the edge computed correctly? 2 / 4

**Evidence**
- Edge buckets (`replay66_primary.out`, all qualifying bets at the close):

| Market | Edge bucket | Win % (break-even) | ROI |
|---|---|---|---|
| Spread | 1.5-2 pts | 47.1% | −8.8% |
| Spread | 2-2.5 pts | 48.4% | −6.6% |
| Spread | 2.5-3 pts | 58.0% | +11.4% |
| Spread | 3-4 pts | 53.4% | +2.6% |
| Spread | 4+ pts | 53.9% | +3.4% |
| Moneyline | 3-5% | — | +1.5% |
| Moneyline | 5-8% | — | −0.3% |
| Moneyline | 8-12% | 52.4% (66.3%) | −23.0% |

  Spreads are not monotone. Bigger moneyline edges did worse.
- On every game, ATS on the model's side vs |model − line|: correlation with profit 0.024 (n=1,424).
- Edge math (code read):
  - Single-book matched ML pair, multiplicative de-vig: correct (`test_devig_pair_is_never_mixed_across_books`).
  - Pushes: handled (`cover_prob` returns a push probability; Kelly and `bet_chance` renormalize).
  - Key numbers: handled through the empirical margin distribution.
  - Real juice: used, with a −110 fallback.
- Caveats:
  - `shop._attach_single_book` silently fills missing FanDuel spread juice with the stored nflverse (DraftKings) juice while labeling the row "fanduel".
  - Raw model probabilities are compared with the market without any blending, which fits the 5.6-pt overconfidence above.

**What's costing points:** edges behave like noise.

**Confidence:** medium-high.

### 6c. His own betting choices: 1 / 2

**Evidence**
- What the repo does:
  - `review_week.tracker_review` labels each of his bets "same side / OPPOSITE / no model bet", without prices.
  - CLAUDE.md notes his deviations anecdotally: IND −340 left out, NYG +1.5 not logged, TB +3.5 at −148, CIN +2.5 at −199, two sign typos.
- Grader comparison with prices (`$PY ../work/his_vs_model.py`, output in `his_vs_model.out`), using closing EV at the FanDuel fair close:

| His bets | n | Closing EV | Realized |
|---|---|---|---|
| All | 28 | −3.86% per bet (t −6.51) | +9.23 units |
| Same bet as the card | 22 | His number/price −3.46% vs the card's −1.82% | +7.09 vs +7.34 units |
| Off-card | 4 | −6.1% | +2.61 units |
| Card bets he did not log (Wk3-7) | 10 | −2.9% | +1.55 units |

  On the 22 shared bets, his choices cost about 1.6% per bet in expectation.

**What's costing points:** his deviations are only noted anecdotally, not measured with prices.

**Confidence:** high.

## 7. Locked choices work as designed (bug check only): 3 / 3

**Evidence**
- FanDuel only (from Week 3): every bet row in Weeks 3-7 has `odds_source = fanduel` (5/6/7/7/7 rows in `leans.csv`). A FanDuel row needs both FanDuel moneylines (`shop.py`), and a test guards it.
- Spreads and moneylines only: true in all seven weeks.
- $5 flat (from Week 4): every bet is $5.
  - Week 4: 6 × $5 in the slate CSV.
  - Weeks 5-6: 6 × $5 plus the carried Thursday bet.
  - Week 7: 7 × $5 in the slate and on This Week's Bets.
- Card size 4-7 (from Week 5): 7, 7, 7; no filler needed.
- ML caps respected: the shortest favorite is BUF −350 (at the limit) and the longest underdog is MIA +205.

**What's costing points:** nothing; no deviation found. One latent risk: the spread-juice fallback in 6b. The archive does not record the juice source, so I cannot tell whether it ever fired.

**Confidence:** high.

## 8. Input correctness at the time he bets (3 / 10)

### 8a. Quarterback starters: 1 / 5

**Evidence**
- `$PY ../work/qbcheck.py` (output in `qbcheck.out`) compares the assumed starter in `weekNN_meta.json` with the nflverse attempts leader. There are 7 mismatches.
- 4 are in-game injuries to the correct starter: Wk1 SEA Darnold, Wk1 MIN Murray, Wk2 NYG Dart, Wk4 WAS Mariota.
- 3 are wrong pregame starters in final picks:
  - Wk1 ATL: Tagovailoa assumed, Cooper Rush started. The PIT pick was right; no bet.
  - Wk7 TB: Jalon Daniels override, Baker Mayfield started. About a 2.4-pt swing; the CAR pick was unchanged and lost. It was caught only in the scratch Sunday run.
  - Wk7 NYG: Winston assumed, J.J. McCarthy started. About 0.1 pt.
- None of the three changed a pick or a bet.

**What's costing points:** 3 wrong starters in final picks.

**Confidence:** high.

### 8b. Injuries and late news by game day: 1 / 3

**Evidence**
- From archive and git timestamps, a late run reached his files in:
  - Week 3 (Sat 9/26), Week 4 (Sun 10/4), Week 5 (Sun 10/11), Week 6 (Sat 10/17).
- Weeks 1-2: no game-day refresh.
- Week 7: the Sunday roster run happened in a scratch copy only (CLAUDE.md 2026-10-25). His files stayed on Wednesday's card. That card missed Lamar being out and Mayfield playing, and still carried CIN +2.5 and MIA +205, which the Sunday run dropped.
- `OPERATING.md` makes the Sunday roster run the procedure "from 2026 Week 5".

**What's costing points:** 3 of 7 weeks had no refresh reaching his files, and the formal procedure failed once (Week 7).

**Confidence:** medium. It would be 2 if pre-procedure weeks are excused.

### 8c. Prices match what he can bet: 1 / 2

**Evidence**
- Edges are computed on the FanDuel price at build time.
- There is no "still a bet at" number in any sheet of the Week 7 workbook (regex search of every sheet) or in the outputs. The only one is an ad-hoc CLAUDE.md note for the Monday-night game ("stops qualifying at +4").
- In Week 7 two Wednesday bets no longer qualified on Sunday. He bet one of them on an alt line (CIN +2.5 at −199, closing EV −7.4%).

**What's costing points:** there is no guide to whether a moved line still qualifies.

**Confidence:** high.

## 9. Process reliability and safeguards (4 / 8)

### 9a. The weekly procedure produces the right files: 2 / 4

**Evidence:** two procedure failures.
1. The Week 7 Sunday run was scratch-only, so his files kept a wrong TB starter and two bets that no longer qualified.
2. First-published numbers were not kept for Weeks 1-4. The mechanism was added 10/07 (commit b3bc5bb), and those weeks were backfilled from final cards.

Locks were eventually applied to every week. Weeks 6 and 7 were first graded with the lock stubbed and locked on 10/21 and 10/27. The Week 7 workbook matches the archive (see 10a).

**What's costing points:** the two failures above.

**Confidence:** high.

### 9b. Tests and guards: 2 / 4

**Evidence**
- `pytest tests/ -q` in the copy (`grader-r1/pytest_out.txt`): 226 passed, 2 failed.
  - Failing: `tests/test_history.py::test_build_history_grades_and_joins` and `::test_summarize_history_numbers` (avg_clv_pts 0.75 vs 1.0).
  - Both have been known since 10/8 per CLAUDE.md and are still unfixed.
- Every named past bug has a guard:

| Past bug | Regression test(s) |
|---|---|
| Sign convention | `test_ticket_sign_matches_the_real_bet`, `test_clv_signs_from_the_bettors_side` |
| Mixed-book de-vig | `test_devig_pair_is_never_mixed_across_books` |
| Market-prior leak | `test_market_ratings_respect_asof_cutoff`, `test_deployed_model_is_leak_free` |
| QB override | `test_qb_override_actually_reaches_the_projection` |
| Tracker carry | `test_tracker_is_carried_cell_for_cell`, `test_a_tracker_rebuilt_from_scratch_keeps_his_converter` |

**What's costing points:** 2 failing tests.

**Confidence:** high.

## 10. Workbook correct, carried, usable and honest (8 / 10)

### 10a. Numbers and formulas correct: 4 / 4

**Evidence:** `$PY ../work/wb_check.py` (output in `wb_check.out`) checked 363 cells in a copy of `output/NFL_Model_2026_Week07.xlsx`, using cached values. All of them match.

| Sheet | Cells | Checked against |
|---|---|---|
| Picks | 84 | Pick, win %, margin, ML and tier vs `week07_picks.csv` |
| Weekly Slate | 119 | MLs, spread, edge recomputed as margin − line, home win %, recommendation, odds and $5 stake vs the slate CSV and `leans.csv` |
| Bet Tracker | 64 | Each row's W/L vs nflverse scores, P&L formula values, B5-B10, M5, K6, running bankroll |
| Chart Data | 96 | Cumulative profit (final 46.13), running win %, per-bet break-even, profit by week, profit by bet type |

The one cell my script flagged was my own expected format. R2 reads "BANKROLL $146.13 (+$46.13 since the start)", which is correct.

**What's costing points:** nothing.

**Confidence:** high.

### 10b. His Bet Tracker carried and charts updated: 3 / 3

**Evidence:** from `wb_check.out`, comparing every formula and value in Bet Tracker rows 1-32 between Week 6 and Week 7:
- One cell differs: J6, 0.537 → 0.52. J6 is the input to his own Kalshi converter. `output/.tracker_state.json` shows the Week 7 tracker as written had the same fingerprint as his Week 6 save, so the change is his own later edit.
- K6 `=IF(J6>=0.5, -ROUND(J6/(1-J6)*100,0), ROUND((1-J6)/J6*100,0))` and M5 `=SUM(H12:H300)` are identical.
- All 21 earlier rows are identical.
- The 3 kept charts sit at identical anchors. Their series point at formula ranges on Chart Data that now cover all 28 rows.
- The chart he deleted (profit by bet type) is not restored.

**What's costing points:** nothing.

**Confidence:** high.

### 10c. Usable and honest: 1 / 3

**Evidence**
- What works:
  - Picks ranks every game by win %, with a "vs Market" column.
  - This Week's Bets lists each bet with its price and $5 stake.
  - Banners say the hold-out shows no edge against closing lines.
- What's missing:
  - A straight-up favorite baseline. Bet Log shows only "Model's pick won the game 55 of 92".
  - A CLV view. Bet Log has no close or CLV columns, and the tracker's CLV cells are blank because closes are never typed. The terminal review prints CLV, but the workbook does not.
- Stale or misleading items:
  - Reference & Glossary B4 says the model "ships in ADVISORY MODE ... stakes $0", while every sheet shows live $5 bets.
  - The "Win Chance" column on This Week's Bets shows the pick's straight-up win %. DEN −4.5 shows 76%; its cover chance is 54.5% on the Weekly Slate.

**What's costing points:** both the favorite baseline and the CLV view are missing, plus a stale claim.

**Confidence:** medium-high.

---

## Biggest point losses
1. **1a, −6 pts.** On the 2021-25 hold-out the deployed model picks fewer winners than the closing favorite: 65.28% vs 66.48%, −1.20 pts (t −1.46). It is behind or level in every season. Always taking the favorite would have picked 17 more winners.
2. **3a, −5 pts.** Live components that measurably hurt the hold-out are still on:
   - EPA/play factor: Brier worse at t +2.5. The repo's own factor lab rated it "no help".
   - EPA self-tune: SU −0.85 pts.
   - Market-prior blend: SU −0.63 pts.

   The stack was never ablated as a whole.
3. **1b, −4 pts.** Picks against the favorite won 43.7% (59/135) on the hold-out and 2 of 7 live. Simpler rules pick more winners: favorite-only 66.48%, or a 0.35 model / 0.65 market blend 67.11% (in-sample). The repo never tested any of them.
4. **2c, −4 pts.** Probabilities are overconfident: slope 0.855, and the 65-70% and 80-85% buckets are about 9 pts too high. The recalibration was fit on a different stack (base+trend) than the one it is applied to.
5. **6a, 5b, 8a, −4 pts each (tie).**
   - 6a: the card's hold-out ROI at closing prices is +0.02% ± 3.4%.
   - 5b: there is no luck-vs-skill accounting; the 25-19-1 card is consistent with luck (closing EV −2.8% per bet).
   - 8a: three wrong pregame QB starters.

## What's genuinely strong
- **Clean data pipeline.** I found no leak in the market prior, EPA features or injury inputs. A from-scratch walk-forward rerun reproduces the cached hold-out projections exactly.
- **Honest documentation.** The workbook and README lead with hold-out "no edge" numbers. IMPROVEMENT.md records rejected ideas, and the docs warn never to quote tuning-season numbers.
- **Close to the market on margins.** The deployed stack's margin error is within 0.14 pts of the close. It also carries some information beyond the line (t 1.89), which is better than the repo itself claims.
- **Workbook correct.** All 363 spot-checked cells match. His tracker carried cell for cell (K6, M5, all rows), and the charts he kept update while the one he deleted stays gone.
- **Locked rules and test coverage.** The locked rules run exactly as specified, and every named past bug has a regression test (228 tests).
- **Sound pricing code.** It uses a single-book de-vig, key-number-aware cover probabilities from the empirical margin distribution, push-aware Kelly qualification and real juice.

## Rubric gaps
1. **5c:** the rubric defines CLV as line movement but does not say whether "significantly negative" also applies to value net of the vig. Here they conflict: movement CLV is +0.75% (t +1.56), while closing EV at the price taken is −2.8% (t −3.56).
2. **3a:** the SU-only trigger (down more than 0.5 pt) can flag a component that significantly helps MAE. The market prior is down 0.63 pts on SU (t −1.19) while improving MAE by 0.062 (t −2.49). The rubric does not say how to weigh conflicting metrics. Here it did not change the score, since two other components clearly hurt.
3. **6a:** the level boundary sits at ROI = 0, and the result is knife-edge. The rubric does not name a canonical reconstruction: which target to refit the 2013-20 factor weights on, and which recalibration fit to use. Those choices move ROI between −0.35% and +0.02%.
4. **8b:** the evidence window is Weeks 1-7, but the game-day procedure only began in Week 5. It is unclear whether pre-procedure weeks count as skips.
5. **1a:** the rubric does not say what target the 2013-20 factor refit should use. The two candidates give 0.512/1.866/0.044 vs 0.351/0.491/0.015 weights, though the band is the same here.
6. **10c:** it is unclear whether CLV and expected-wins shown only in the terminal review, and not in the workbook, count.
7. **His data-entry errors** (two sign typos, alt lines logged without the original number) distort his CLV and chart categories. No criterion covers them.

## Couldn't verify
- **`review_week.py` output.** It was not run because it locks weeks; I read it from the code and CLAUDE.md notes.
- **The Week 7 run's terminal output.** It was not saved, and `run_week.py` is off-limits.
- **The spread-juice fallback.** I could not tell whether it ever fired on a published bet, because the archive does not record the juice source.
- **The repo's card-replay figures** (55.4% / −0.7%). No script in the repo produces them; my reconstructions give +0.02% / −0.29% / −0.35%.
- **What he saw in Weeks 1-2.** The archive was committed on 9/25, after publication, so I could not confirm it matches what he was shown.
- **Whether he bet NYG +1.5** (Week 6). It is not in his tracker.
- **Game-day prices for the card's bets.** Only his own bets' game-day prices are recorded.
