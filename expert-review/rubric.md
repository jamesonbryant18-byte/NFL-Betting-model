# Rubric v2: NFL Betting Model (2026 season, Weeks 1-7 graded)
v1 locked 2026-10-28; v2 locked 2026-10-29 (approved by Jameson, his answers C and D to round 1) | Scale: 100 | Owner's goal, in his words: "I want the model to be right" (straight-up winners) and "I want the edge picks to be great and not lucky."

**Locked parts (checked for bugs only, never graded for design, never suggested as fixes):**
FanDuel as the only book; spreads + moneylines only; $5 flat stake; 4-7 bets per week.

**Weighting follows the owner's order:** model picks (45) > bets (27) > weekly inputs (18) > Excel workbook (10).

**Changes from v1 (v1 and v2 scores are not strictly comparable; v1 is kept at `round-1/rubric-v1.md`):**
1. The model is graded on its own bets (the archive `picks/2026/` and the workbook's Bet Log), not on his Bet Tracker. His own picks and prices are his choices. 6c ("his own betting choices", 2 pts) is removed and its 2 points move to 5c. 5a and 5b take their evidence from the model's card.
2. 5c (now 6 pts) also scores **value at the price taken**: each model bet's expected return if the same book's de-vigged closing price is the truth (key-number aware for spreads). Small differences (inside one standard error, or within about 1% a bet) count as about zero, not as a loss.
3. One canonical replay of the deployed model: `scripts/replay_deployed.py` (on `src/nflmodel/replay.py`; everything fit on 2013-2020 only) is the evidence for 1a, 2a-2c, 3b and 6a-6b, and `scripts/ablation.py` for 3a. The grader checks that the replay matches the live code path (`scripts/run_week.py`, `model.py`); a mismatch is scored under 3c(iv) and 4a, and the grader then measures with a faithful replay of their own.
4. Workbook evidence (10a-10c) is the most recent weekly workbook and the one before it, whichever weeks those are when the round runs.

**Ground rules for every criterion**
- "Hold-out" = 2021-2025, seasons no fitted value was tuned on. Numbers from 2013-2020 (or from fits that saw 2021-25) are not results.
- "Live" = 2026 Weeks 1-7 as archived in `picks/2026/` (what was actually published), never a rebuild.
- "The favorite" = the betting favorite on the same game. "At publication" uses the line archived with the pick; "closing" uses `picks/2026/weekNN_closing.csv` (live) or nflverse `spread_line` (history). Pick'em games and ties are excluded consistently and the count reported.
- Small samples: 2026 has ~106 games and ~49 bets. Anchors reward measuring uncertainty honestly; a lucky record earns nothing by itself.

## Summary
| # | Criterion | Points |
|---|-----------|--------|
| | **A. Model picks** | **45** |
| 1 | Straight-up accuracy vs simply taking the favorite | 15 |
| 2 | Margin and win-probability accuracy vs the market | 12 |
| 3 | Model design: does every live piece earn its place? | 10 |
| 4 | Validation rigor and leakage | 8 |
| | **B. Bets** | **27** |
| 5 | Live bets: good bets or lucky ones? | 14 |
| 6 | Bet selection logic | 10 |
| 7 | Locked choices work as designed (bug check only) | 3 |
| | **C. Weekly inputs and process** | **18** |
| 8 | Input correctness at the time he bets | 10 |
| 9 | Process reliability and safeguards | 8 |
| | **D. Excel workbook** | **10** |
| 10 | Workbook correct, carried, usable and honest | 10 |
| | **Total** | **100** |

---

## 1. Straight-up accuracy vs simply taking the favorite (15 pts)
Why it matters: this is the owner's main goal. A raw SU% moves with how many upsets a season has; the fair test is the same games picked by "always take the favorite".

### 1a. Hold-out straight-up vs the closing favorite (7 pts)
- Full (7): The model as deployed (every live component) replayed walk-forward on 2021-25 picks winners at a rate at or above the closing favorite on the same games, and the comparison is reproducible from the repo.
- Partial (5): 0 to 0.5 pts below the favorite. (3): 0.5 to 1.0 below. (1): 1.0 to 2.0 below.
- Zero (0): more than 2.0 pts below, or no same-games comparison can be produced.
- Evidence required: the canonical replay (`scripts/replay_deployed.py`; change 3 above), checked for faithfulness to the live path. Report model SU%, closing-favorite SU%, games compared, per-season split, and the SE of the paired difference.

### 1b. The straight-up pick rule (4 pts)
- Full (4): When the model picks against the favorite, those picks win at least 50% on the hold-out (n reported), OR the repo has tested alternative pick rules on the hold-out (model only / favorite only / disagree only above a threshold / blended model+market probability) and uses the best one.
- Partial (2): Disagreement picks win 45-50% on the hold-out and no alternative rule was tested.
- Zero (0): Disagreement picks win under 45% on the hold-out, or the question was never measured.
- Evidence required: on the hold-out projections from 1a, count games where the model's SU pick differs from the closing favorite, the model's hit rate in them, and the SU% each alternative rule would have produced. Repeat on 2026 live (favorite at publication and at close).

### 1c. Live straight-up tracking and explanation (4 pts)
- Full (4): The project reports 2026 SU against the favorite baseline on the same games (at publication and at close) with an uncertainty band, and every miss where the model went against the favorite is explained (input error vs model view vs noise).
- Partial (2): SU reported with an expected-wins band, but no favorite baseline or no explanation of disagreement misses.
- Zero (0): Raw SU% only.
- Evidence required: read `scripts/review_week.py` and `scripts/grade.py` output (run them in the scratch copy; `grade.py` without `--save`); recompute the 2026 favorite baseline from `picks/2026/` and results.

## 2. Margin and win-probability accuracy vs the market (12 pts)
Why it matters: the closing line is the sharpest public forecast. A model that is less accurate than the line on the same games will pick fewer winners than the favorite and cannot find real edges.

### 2a. Margin error vs the closing line (4 pts)
- Full (4): Hold-out mean absolute error of the deployed model at or below the closing line's on the same games.
- Partial (3): within 0.15 pts worse. (2): 0.15-0.30 worse. (1): 0.30-0.50 worse.
- Zero (0): more than 0.50 worse, or not measured.
- Evidence required: compute MAE(model) and MAE(closing spread) on the 1a hold-out games; also on 2026 live from the archive. Report both, plus the paired t.

### 2b. Win probability vs the de-vigged market (4 pts)
- Full (4): Hold-out Brier score (and log loss) of the model's home win probability at or below the de-vigged closing moneyline's on the same games.
- Partial (3): Brier within 0.002 worse. (2): 0.002-0.005 worse. (1): 0.005-0.010 worse.
- Zero (0): more than 0.010 worse, or never compared with the market.
- Evidence required: de-vig closing moneylines (multiplicative, matched pair) for every hold-out game with both prices; compute Brier and log loss for model and market on identical games; repeat for 2026 live.

### 2c. Calibration (4 pts)
- Full (4): On the hold-out, calibration slope (logistic regression of outcome on logit p) between 0.90 and 1.10 and every probability bucket with n >= 100 within 3 pts of its actual rate; live tiers reported with counts and bands.
- Partial (2): slope 0.80-0.90 or 1.10-1.20, or one bucket off by 3-6 pts.
- Zero (0): slope outside 0.80-1.20, any bucket off by more than 6 pts, or no reliability check.
- Evidence required: reliability table (5-pt buckets from 50%) and calibration slope on the hold-out picked-side probability; same table for 2026 with counts.

## 3. Model design: does every live piece earn its place? (10 pts)
Why it matters: "do more of what works, fix what doesn't" needs each piece measured on its own.

### 3a. Component ablation on the hold-out (5 pts)
- Full (5): A reproducible ablation of the deployed stack on 2021-25: market-prior blend, joint QB fit, home field, each game factor (injuries, EPA/play, rest), the "far from the line" trend pull, the EPA self-tune, and the win-% recalibration. Each one's marginal effect on SU%, MAE and Brier is reported, and no live component makes the hold-out measurably worse (paired t <= -2 on MAE or Brier, or SU down more than 0.5 pt).
- Partial (3): Components were tested one at a time when added, but never together as the deployed stack; or one live component measurably hurts (2).
- Zero (0): No component-level evidence, or two or more live components hurt.
- Evidence required: run `scripts/ablation.py` (and check it against the live path); cite `scripts/factor_lab.py`, `scripts/refit_factors.py`, `scripts/adjust_lab.py`, `scripts/miss_report.py --no-save`, `IMPROVEMENT.md`; check that the documented numbers reproduce. The market-prior blend, joint QB fit and home field need a full walk-forward re-run each; the grader may run or reconstruct those.

### 3b. Information beyond the line (3 pts)
- Full (3): Regressing the actual margin on the closing line and the model's projection (hold-out), the model's incremental coefficient is positive with t >= 2.
- Partial (2): positive with 1 <= t < 2. (1): positive with t < 1.
- Zero (0): zero or negative, or never measured.
- Evidence required: OLS of result on (closing spread, model projection) for 2021-25; report coefficient, SE, t; repeat with the projection minus the line as the second regressor.

### 3c. Structural soundness (2 pts)
- Full (2): None of these is present, or each was measured and shown harmless: (i) double counting (the market prior backed out of spreads already contains each team's QB; the QB value is added on top); (ii) discontinuities (the trend pull switches on at exactly 3 pts off the line); (iii) unrated or inexperienced QBs set to replacement level; (iv) live/replay mismatch (does the live market prior use the current week's lines while the replay does not?).
- Partial (1): Each is identified and documented but not measured.
- Zero (0): Any is unidentified.
- Evidence required: read `ratings.py` (`fit_market_ratings`, `blend_with_prior`, `fit_ratings_qb`), `model.py`, `trends.py`; test (iv) by comparing which lines the prior uses live vs in replay.

## 4. Validation rigor and leakage (8 pts)
Why it matters: leaks make backtests look like edges. This project has already had one (the market-prior as-of bug).

### 4a. Leak-free hold-out, honest reporting (4 pts)
- Full (4): No leak found: as-of guards on the market prior, every factor (injuries, EPA, rest) computed from pregame information only, trend and calibration fits that did not use the seasons they are scored on, and headline numbers are hold-out numbers.
- Partial (2): A minor leak (under 0.05 pt MAE effect) or a headline number from an in-sample fit.
- Zero (0): A material leak, or in-sample numbers presented as results.
- Evidence required: inspect `fit_market_ratings(asof_week=)`, `factors.py` pregame construction, `trends.py` fit windows; spot-check 5 hold-out games by hand for feature timing.

### 4b. Reproducibility (4 pts)
- Full (4): The grader reproduces at least three documented headline hold-out numbers (e.g. MAE, SU%, ATS%) within 0.02 pts / 0.3 pct from repo scripts, and caches are consistent with the live data loader.
- Partial (2): Reproduces with known-stale caches or small unexplained discrepancies.
- Zero (0): Cannot reproduce.
- Evidence required: run the scripts in a scratch copy; note `CLAUDE.md` section 9 on stale caches.

## 5. Live bets: good bets or lucky ones? (14 pts)
Why it matters: the owner wants bets that win because they are good, not because of a hot week.

### 5a. Logging completeness (3 pts)
- Full (3): For every model bet, Weeks 1-7: game, market, side, number and price taken, the model's probability for that bet, the de-vigged market probability, the closing number and price (same book), result, stake, P&L, and the first-published vs final number.
- Partial (1-2): One or two fields missing or backfilled (e.g. cover probability not archived; early weeks' CLV scored from the final card).
- Zero (0): No closing lines or no model probabilities.
- Evidence required: inspect `picks/2026/*.csv` and the workbook's Bet Log (read-only copy). His Bet Tracker is context, not evidence for this criterion.

### 5b. Luck vs skill accounting (5 pts)
- Full (5): Actual wins vs expected wins under BOTH the model's and the market's de-vigged probabilities, with SD; ROI vs the break-even of the prices taken; slices by market, favorite/underdog, odds bucket and edge bucket; conclusions that follow from the numbers.
- Partial (3): Expected wins and topline only. (1): Record and ROI with a generic "small sample" caveat.
- Zero (0): Record/ROI only.
- Evidence required: compute these for the model's card (Weeks 1-7, from the archive); compare with what `review_week.py`/`grade.py`/the workbook report.

### 5c. Closing line value and value at the price taken (6 pts)
- Full (6): Both measured correctly (same-book close; de-vigged for moneylines; key-number-aware for spreads; from the number first published and from the one on the final card) and reported every week, and the model's average value at the price taken is positive with t >= 2 over 40+ bets.
- Partial (5): Measured correctly; positive but not significant. (4): Measured correctly; about zero (inside one SE, or within about 1% a bet: a small difference is neglected). (2): Measured correctly; negative, 1 <= |t| < 2. (1): Measured with method errors.
- Zero (0): Not measured, or significantly negative (t <= -2).
- Evidence required: recompute for every card bet from `weekNN_first_leans.csv`/`weekNN_leans.csv` vs `weekNN_closing.csv`: CLV (spread points converted with the repo's key-number table; moneylines de-vigged) and value at the price taken (expected return per $1 at the de-vigged same-book close). Report mean, SD, t, and with the largest news-driven move removed.

## 6. Bet selection logic (10 pts)
Why it matters: the selection rules decide which games he bets.

### 6a. Hold-out profitability of the selection rules (6 pts)
- Full (6): The deployed rules (1.5-pt spread edge, 3% moneyline edge, -350/+250 caps, recalibrated probabilities, top-7-by-chance card) replayed on 2021-25 at closing prices show ROI > 0 with a 95% interval excluding break-even.
- Partial (4): ROI >= 0 but not significant. (2): ROI between -3% and 0. (1): -3% to -6%.
- Zero (0): Worse than -6%, or never replayed.
- Evidence required: the canonical replay's card (`scripts/replay_deployed.py`, live rules via `NFLModel._recommend`/`_weekly_card`) with real closing prices and juice; report n, win%, ROI, SE, by market and season. Closing prices are the right test here because the owner bets on game day, close to the close.

### 6b. Do bigger edges mean better bets? Is the edge computed correctly? (4 pts)
- Full (4): On the hold-out, outcomes improve with the size of the model-vs-market edge (monotone across at least three edge buckets), AND the edge math is right (single-book de-vig, pushes handled, key numbers, real juice).
- Partial (2): Edge math correct but outcomes do not improve with edge size (edges behave like noise); or the reverse.
- Zero (0): Edge math wrong (raw implied probabilities, mixed-book de-vig) and no monotone relationship.
- Evidence required: hold-out ATS and moneyline results by edge bucket; read `model._recommend`, `market.devig`, `shop`.

## 7. Locked choices work as designed (3 pts, bug check only)
- Full (3): Verified on the archive from the week each rule took effect: every line and price is FanDuel's, with a matched moneyline pair (from Week 3, 2026-09-25); only spreads and moneylines; every model bet $5 (from Week 4); 4-7 bets per week with any filler labeled (from Week 5).
- Partial (1-2): One deviation.
- Zero (0): Multiple deviations.
- Evidence required: scan `picks/2026/*_leans.csv` (`odds_source`, `bet_market`, stakes) and the card counts per week.

## 8. Input correctness at the time he bets (10 pts)
Why it matters: wrong inputs are fixable errors that cost picks no matter how good the model is. He bets on game day, so what counts is the information in front of him then.

### 8a. Quarterback starters (5 pts)
- Full (5): No wrong starter in the final pre-kickoff picks for Weeks 1-7, or every one caught and re-priced in the files he reads before he bet.
- Partial (3): 1-2 wrong starters in final picks. (1): 3-4.
- Zero (0): 5 or more, or no check.
- Evidence required: compare each archived pick's assumed QB (`weekNN_meta.json`) with the actual starter (nflverse attempts leader); state which picks or bets each error could have changed.

### 8b. Injuries and late news by game day (3 pts)
- Full (3): A Saturday/game-day refresh reliably runs and its picks and bets reach the files he reads.
- Partial (1-2): The procedure exists but has failed or been skipped in a week (count them).
- Zero (0): No refresh.
- Evidence required: `OPERATING.md` procedure, the Weeks 1-7 archive timestamps, `CLAUDE.md` section 0 notes.

### 8c. Prices match what he can bet (2 pts)
- Full (2): Bets and edges shown to him use FanDuel's number from close to when he bets, or the workbook tells him the minimum number at which each bet still qualifies.
- Partial (1): Edges are computed on mid-week prices while he bets on game day, with no guide to whether a moved line still qualifies.
- Zero (0): Wrong book or wrong prices.
- Evidence required: compare archived bet prices with closing prices; check for a "still a bet at" number in the outputs.

## 9. Process reliability and safeguards (8 pts)

### 9a. The weekly procedure produces the right files (4 pts)
- Full (4): Weeks 1-7 archives are complete and match what he was shown; first-published numbers are preserved; locks applied; no run that should have updated the real files happened only in a scratch copy.
- Partial (2): One or two procedure failures (count them).
- Zero (0): Archives unreliable.
- Evidence required: `picks/2026/`, git history, `CLAUDE.md` section 0.

### 9b. Tests and guards (4 pts)
- Full (4): The full test suite passes, and the known past bugs (sign convention, mixed-book de-vig, market-prior leak, QB override, tracker carry) each have a regression test.
- Partial (2): 1-3 failing tests, or a known bug without a guard.
- Zero (0): Suite broken or no guards.
- Evidence required: run `pytest tests/ -q` in the scratch copy; map past bugs to tests.

## 10. Workbook correct, carried, usable and honest (10 pts)

### 10a. Numbers and formulas correct (4 pts)
- Full (4): 20+ spot-checked cells (Picks, Weekly Slate, Bet Tracker, Chart Data) match the archive and recomputation.
- Partial (2): 1-2 errors that change no decision.
- Zero (0): An error that misstates a bet or a result.
- Evidence required: open a COPY of the most recent `output/NFL_Model_2026_WeekNN.xlsx` read-only (openpyxl, formulas evaluated where needed).

### 10b. His Bet Tracker carried and charts updated (3 pts)
- Full (3): His own cells and formulas (K6, M5, anything else he added) identical to his previous save; the charts he kept redrawn; deleted ones not restored.
- Partial (1-2): A minor discrepancy.
- Zero (0): His cells or formulas lost.
- Evidence required: compare the two most recent workbooks' Bet Tracker cells (copies only). Blank Closing Line / Closing Odds cells filled from FanDuel's recorded closes are his request (2026-10-29), not a carry error, provided nothing he typed changed and the run reports them.

### 10c. Usable and honest (3 pts)
- Full (3): He can see every game's straight-up pick ranked by confidence, each bet with its price, and an honest read of whether the bets have an edge (favorite baseline, CLV), with no overstated claims.
- Partial (1-2): Missing the favorite baseline or CLV view, or one overstated claim.
- Zero (0): Misleading presentation.
- Evidence required: review the most recent workbook copy and the run's terminal output.
