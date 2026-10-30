# Grade: NFL Betting Model, rubric v2 (round 2)

**Total: 55 / 100**
**Confidence: medium-high.** Almost every number below was recomputed by me and matched the repo's own output where both exist. The lowest-confidence calls are 2c (one bucket sits right on the cut-off), 3a and 1c (the anchors are ambiguous; I took the lower level), and 9a (no anchor fits three failures).
**Self-graded: no.**

Grading date: Thursday 2026-10-29. Weeks 1-7 are played and locked. Week 8 is built and unplayed.

All work was done in the scratch copy. My scripts and outputs are in `/private/tmp/claude-501/-Users-jameson/f8af9ddc-e116-402b-81c6-f976dc266c74/scratchpad/grader-r2/work/`, and the workbooks were opened as copies in `work/wb/`. The owner's workbooks still match the checksums taken before grading (`shasum -c real_output_before.sha`: all 8 OK).

## Score table

| # | Criterion | Max | Score |
|---|---|---|---|
| 1a | Hold-out straight-up vs the closing favorite | 7 | 5 |
| 1b | The straight-up pick rule | 4 | 2 |
| 1c | Live straight-up tracking and explanation | 4 | 2 |
| 2a | Margin error vs the closing line | 4 | 3 |
| 2b | Win probability vs the de-vigged market | 4 | 2 |
| 2c | Calibration | 4 | 0 |
| 3a | Component ablation on the hold-out | 5 | 3 |
| 3b | Information beyond the line | 3 | 2 |
| 3c | Structural soundness | 2 | 1 |
| 4a | Leak-free hold-out, honest reporting | 4 | 2 |
| 4b | Reproducibility | 4 | 4 |
| **A** | **Model picks** | **45** | **26** |
| 5a | Logging completeness | 3 | 1 |
| 5b | Luck vs skill accounting | 5 | 3 |
| 5c | Closing line value and value at the price taken | 6 | 0 |
| 6a | Hold-out profitability of the selection rules | 6 | 4 |
| 6b | Bigger edges, better bets? Edge math | 4 | 2 |
| 7 | Locked choices work as designed (bug check) | 3 | 2 |
| **B** | **Bets** | **27** | **12** |
| 8a | Quarterback starters | 5 | 1 |
| 8b | Injuries and late news by game day | 3 | 1 |
| 8c | Prices match what he can bet | 2 | 1 |
| 9a | The weekly procedure produces the right files | 4 | 1 |
| 9b | Tests and guards | 4 | 4 |
| **C** | **Weekly inputs and process** | **18** | **8** |
| 10a | Numbers and formulas correct | 4 | 4 |
| 10b | His Bet Tracker carried, charts updated | 3 | 3 |
| 10c | Usable and honest | 3 | 2 |
| **D** | **Excel workbook** | **10** | **9** |
| | **Total** | **100** | **55** |

## Answers to the brief's eight questions (short)

1. **More or fewer winners than the favorite?** Fewer, by a margin inside the noise.
   - Hold-out: 65.99% vs 66.48% (-0.49 pt, t -0.66, 1,420 games).
   - Live: 64-42 vs 67-39.
   - The whole gap comes from games where the model picks against the favorite. On the hold-out those picks went 52 of 111 (46.8%); live they went 2-5 against the favorite at publication and 3-6 against the close.
2. **Accuracy and calibration vs the market?** Slightly less accurate than the closing line on both margin and win %.
   - Margin error: +0.114 pts (t 2.36).
   - Brier score: +0.0041 (t 2.75).
   - Mildly overconfident: calibration slope 0.93, and the 80-85% bucket is 6.25 pts too high.
3. **Which pieces help, which are neutral, which hurt?**
   - Help: market prior, trend pull, injuries.
   - Neutral: joint QB fit, home field, rest, win-% recalibration.
   - EPA/play hurt (Brier t +1.97) and was correctly dropped. No live piece measurably hurts.
4. **Any information beyond the line?** A hint, not proven: +0.34 (t 1.86), and one season was negative.
5. **Did the bets beat the close by more than noise?** No.
   - Closing line value is about zero.
   - Value at the price taken is -2.77% a bet (t -3.56).
   - The hold-out card at closing prices is +0.72% ROI (SE 3.59%): break-even within noise.
6. **Do bigger edges give better results?** No.
   - Results by edge size are not monotone, and the largest moneyline edges are the worst.
   - The highest-chance third of bets is the worst (-8.1%), and the card ranks bets by chance.
7. **What went wrong with inputs and process?**
   - 3 wrong starters, none of which changed a pick or a bet.
   - In 4 of 7 weeks the game-day refresh was missing or did not reach him.
   - 7 of 45 bets no longer qualified at FanDuel's close because the number moved.
   - One bug in a locked part, fixed 10/29.
   - The season scorecard script misgrades rematches and ties.
8. **Is the workbook correct, the tracker intact, the read honest?** Yes, with stale lines.
   - Every cell I spot-checked matched.
   - His tracker carried exactly; only the blank closing cells were filled, as he asked.
   - The verdict is honest. A few stale or wrong lines remain, and his tracker's CLV is inflated by his own typos.

---

## A. Model picks (26 / 45)

### 1a. Hold-out straight-up vs the closing favorite: 5 / 7
- **Evidence.**
  - `scripts/replay_deployed.py` reproduces exactly (`work/replay_deployed_out.txt`), and my independent recompute agrees (`work/holdout_metrics_out.txt`).
  - Model 65.99% (937/1420) vs closing favorite 66.48% (944/1420). Paired difference -0.49 pts, SE 0.74, t -0.66. 4 ties and 0 pick'ems excluded.
  - Per season (model vs favorite):

    | Season | Model | Favorite | Difference |
    |---|---|---|---|
    | 2021 | 61.6 | 62.3 | -0.70 |
    | 2022 | 64.9 | 66.3 | -1.42 |
    | 2023 | 66.0 | 67.4 | -1.40 |
    | 2024 | 71.2 | 70.5 | +0.70 |
    | 2025 | 66.2 | 65.8 | +0.35 |

  - The replay is faithful to the live path:
    - Base projections equal the live `NFLModel` path exactly (max difference 0.0 on 152 games across 10 hold-out weeks; `work/check_base_faithful.py`).
    - The market prior uses weeks up to and including the predicted week, both live and in replay.
    - The dataset and factor caches equal the live loaders.
- **What's costing points.** 0 to 0.5 pts below the favorite falls in the 5-point band. Three of five seasons are behind.
- **Confidence.** High.

### 1b. The straight-up pick rule: 2 / 4
- **Evidence.**
  - Hold-out disagreements with the closing favorite: 111 games, model right in 52 (46.8%).
  - By the model's confidence:

    | Model's win % | Games | Model right |
    |---|---|---|
    | 50-52% | 36 | 44.4% |
    | 52-55% | 46 | 50.0% |
    | 55%+ | 29 | 44.8% |

  - Alternative rules on the same 1,420 games:

    | Rule | Straight-up % |
    |---|---|
    | Model only | 65.99% |
    | Favorite only | 66.48% |
    | Disagree only if model p >= 0.58 | 66.55% |
    | Blend, model weight 0.25 | 66.69% (best) |
    | Blend, model weight 0.50 | 66.48% |

  - Live, the picks against the favorite went 2-5 at publication (7 games) and 3-6 against the close (9 games).
  - Round 1 proposed "pick the favorite in close games". He declined it, so the live pick rule is still the model's raw win %.
- **What's costing points.** Disagreement picks win 45-50%, and the best-tested rule is not used. The 0.25 blend would add about 0.7 pt straight up over the current rule. The rule is not a locked part, so it is graded.
- **Confidence.** High.

### 1c. Live straight-up tracking and explanation: 2 / 4
- **Evidence.**
  - `review_week.py`, run in a throwaway copy (`work/review_week7_out.txt`):
    - Model 64-42 vs the favorite 67-39, both at publication and at the close.
    - A ±5-pick noise band.
    - Expected wins 67.7 by the model's odds and 66.7 by FanDuel's close.
    - "Picks against the favorite this season: 2-5".
  - `miss_report.py --no-save` gives every miss a luck-or-model verdict, including all five losing disagreement picks: Week 1 HOU and Week 2 ATL (turnovers), Week 5 CLE (model miss), Week 6 NYG (turnovers), Week 6 ATL (model miss). The process check flags the input errors.
  - My recompute (`work/live_su_out.txt`) matches: -2.8 pts a game, SE 2.5 at publication and 2.8 at the close; expected 67.7 ± 4.8.
- **What's costing points.** The season scorecard `scripts/grade.py` has a matching bug. `season_scorecard` matches each pick to a game by team pair in either orientation with **no week filter**, takes `g.iloc[0]`, and sets `won = actual > 0`. As a result:
  - Run now (no `--save`), it prints "weeks 1-8, 110 games graded, 64-46 (58.2%)". It grades the unplayed Week 8 rematches CLE@PIT, PHI@WAS and KC@DEN against their earlier meetings. Every rematch from here on will be graded with the wrong game's result.
  - It counts the Week 5 tie as a loss. The committed `data/scorecard.json` says 64-43.
  - It has no favorite baseline and no band.
  - OPERATING.md Step 0a runs `grade.py --save` every week.

  The weekly review alone would earn 4. One of the two straight-up reports he is told to run is wrong on his main metric, so I took the lower level.
- **Confidence.** Medium on the level, high on the facts.

### 2a. Margin error vs the closing line: 3 / 4
- **Evidence.** Hold-out mean absolute error 9.876 for the model vs 9.762 for the line: +0.114 pts (SE 0.048, t +2.36, n 1,424). Live: 9.594 vs FanDuel's close 9.439 (+0.155, t +0.94, n 107).
- **What's costing points.** The model is 0.114 pts worse than the line, inside the 0.15 band.
- **Confidence.** High.

### 2b. Win probability vs the de-vigged market: 2 / 4
- **Evidence.**
  - Hold-out Brier score 0.2156 vs 0.2115 for the de-vigged closing moneyline: +0.0041 (SE 0.0015, t +2.75, n 1,420; multiplicative de-vig on matched pairs). Log loss 0.6198 vs 0.6103.
  - Live: Brier 0.2352 vs 0.2343 (t +0.15, n 104 with FanDuel pairs); log loss 0.6650 vs 0.6649.
- **What's costing points.** 0.002-0.005 worse than the market.
- **Confidence.** High.

### 2c. Calibration: 0 / 4
- **Evidence.**
  - Hold-out reliability table in 5-pt buckets: every bucket is within 3 pts except **[0.80, 0.85): n 104, said 82.2%, won 76.0%, -6.25 pts** (about 1.7 binomial SE).
  - Calibration slope: 0.934 (home probability, no intercept); with intercept 0.957 (home side) and 0.876 (picked side).
  - The margin-histogram leak (4a) flatters this bucket. With a histogram built only from pre-2021 data it is -7.09. Only the in-sample live weights bring it to -2.7.
  - Live 5-pt buckets, my recompute with counts and 95% bands: all 8 buckets are inside their bands.
  - The repo's own tables use coarse bins ("84% said, 81% won"). The review gives weekly tiers with bands; `grade.py` gives season tiers without bands.
- **What's costing points.** One bucket is off by more than 6 pts, which is the Zero anchor. This is knife-edge (6.25 vs 6.0) and within sampling noise.
- **Confidence.** Medium.

### 3a. Component ablation on the hold-out: 3 / 5
- **Evidence.** `scripts/ablation.py` reproduces exactly (`work/ablation_out.txt`). For each piece, the effect of that piece on the deployed stack:

  | Piece | Straight up | MAE | Brier |
  |---|---|---|---|
  | Trend pull | +0.78 pt (t 1.92) | -0.071 (t -4.36) | t -4.59 |
  | Injuries | +0.63 | t -2.59 | t -2.2 |
  | Rest | 0 | t -0.4 | — |
  | Win-% recalibration | — | — | t -1.4 |
  | EPA/play (off) | — | t +1.22 | t +1.97 (correctly dropped) |
  | Self-tune (off) | neutral | neutral | neutral |

  The repo's ablation **omits the market prior, the joint QB fit and home field.** I reconstructed each with a full walk-forward (`work/ablate_structural.py` and `work/score_structural.py`, output in `work/score_structural_out.txt`):

  | Piece | Straight up | MAE (t) | Brier (t) | Card ROI without it |
  |---|---|---|---|---|
  | Market prior | -0.28 | -0.0785 (-3.10) | -0.0019 (-2.38) | -0.5% (vs +0.7% with) |
  | Joint QB fit | -0.14 | -0.029 (-1.0) | n.s. | -1.4% |
  | Home field | -0.07 | -0.032 (-0.83) | +0.0007 (+0.54) | +3.0% to +4.0% (SE about 3.6%) |

  No live piece is measurably worse.
- **What's costing points.**
  - The repo's reproducible ablation does not cover three of the nine listed pieces. Those were only tested one at a time when they were added (README: QB decomposition -0.096 MAE; market-prior "deployed" rows), never on the deployed stack.
  - I took the lower level. If my reconstruction is meant to complete the ablation, this is 5/5.
  - Smaller caveats:
    - The live rest weight (0.048) is 12× its clean 2013-20 fit (0.004).
    - Injuries alone (66.06% / 9.873 / +1.5%) edges injuries plus rest (65.99% / 9.876 / +0.7%).
- **Confidence.** Medium on the level, high on the numbers.

### 3b. Information beyond the line: 2 / 3
- **Evidence.**
  - Hold-out OLS of result on (line, projection): line 0.751 (SE 0.172), projection **+0.340 (SE 0.182, t +1.86)**.
  - With projection minus line as the second regressor: line 1.090, difference +0.340 (t 1.86).
  - Per-season t: 0.54, -0.42, 1.32, 1.42, 0.63.
- **What's costing points.** Positive with 1 <= t < 2. The README still quotes the old -0.018 (t -0.1).
- **Confidence.** High.

### 3c. Structural soundness: 1 / 2
- **Evidence.** All four issues are identified in CLAUDE.md or IMPROVEMENT.md:
  - (i) QB double counting: noted 10/14, "untested fix".
  - (ii) Trend-pull cliff at 3.0 pts: flagged 10/14; a smooth pull is untested.
  - (iii) Replacement-level QBs: on the watch list, with QBs under 8 starts measured at about 0.8-1.1 pts worse than the model; not fixed.
  - (iv) Live/replay mismatch: fixed 10/29, both now use lines up to the predicted week.
- **What's costing points.**
  - (i) and (ii) were never measured, and (iii) was not shown to be harmless.
  - A residual of (iv) is unmeasured: the replay's prior uses nflverse closing lines for the current week, while live uses FanDuel's mid-week lines.
- **Confidence.** High.

### 4a. Leak-free hold-out, honest reporting: 2 / 4
- **Evidence.**
  - The as-of guard on the market prior is correct (`fit_market_ratings`, regression tests).
  - I hand-checked five games (`work/spot_timing_out.txt`): 2021_06_LV_DEN, 2022_12_CIN_TEN, 2023_09_SEA_BAL, 2024_14_LAC_KC, 2025_10_DET_WAS. In each:
    - Ratings were fit only on games before that week.
    - The prior used only that season's lines through the predicted week.
    - Rest came from the schedule.
    - Injuries counted only players listed Out/Doubtful or on reserve that week, none of whom played.
    - Player importance comes from the **prior** season's snaps.
  - The win-% slope b was fit on 2013-20 (1.477).
- **What's costing points.**
  - The empirical margin histogram used for the probability tilt includes 2021-25 outcomes: about +0.29 pt straight up and -0.0004 Brier in its favor (`work/margin_dist_leak.py`).
  - The hold-out was used for selection:
    - Trend fixes must also be "consistent in 2021+" to go live.
    - EPA was dropped and the self-tune turned off after looking at 2021-25.
  - The replay uses the starters who actually played rather than the pregame-assumed ones.

  Each is minor. Together they are more than none, which puts this at the Partial anchor.
- **Confidence.** Medium-high.

### 4b. Reproducibility: 4 / 4
- **Evidence.**
  - Reproduced exactly from repo scripts: straight-up 65.99 vs 66.48, MAE 9.876 vs 9.762, Brier 0.2156 vs 0.2115, slope 0.934, card ROI +0.72% (SE 3.59%), the full `refit_factors.py` table and the ablation table.
  - The dataset cache equals the live loader (0 differing rows for QBs, results, lines and moneylines).
  - The factor cache equals the live injury and rest code for 2022 and 2025.
- **What's costing points.** Nothing. Some docs are stale: the README and the `fitted_params.json` "deployed" MAE of 10.079.
- **Confidence.** High.

## B. Bets (12 / 27)

### 5a. Logging completeness: 1 / 3
- **Evidence.**
  - The archive has, for every bet: game, market, side, number and price (`weekNN_leans.csv`).
  - It has the FanDuel moneyline pair, so the moneyline market probability can be derived.
  - It has the close (`weekNN_closing.csv`). 2 of 45 bets closed against DraftKings, and both are flagged.
  - Results come from the Bet Log.
- **What's costing points.** More than two fields are missing or backfilled:
  - The bet's own model probability for spreads (the cover chance) is not archived. It is recomputed at review time.
  - Only the bet side's spread price is archived, so the de-vigged spread market at publication cannot be rebuilt.
  - Stake and P&L for model bets are not archived. They live only in the gitignored, overwritten `output/slate_*.csv`, and the Bet Log shows the result only.
  - First-published numbers for Weeks 1-4 were backfilled from the final card.
- **Confidence.** High.

### 5b. Luck vs skill accounting: 3 / 5
- **Evidence.**
  - The repo's review prints:
    - Expected wins of 24.3 by the model and 21.8 ± 3.2 by the close, vs 25 actual.
    - Won 57% vs a 51% break-even.
    - Value -2.8% ± 1.5%.
    - A verdict that follows from the numbers: "the record is running ahead of the bets".
  - My recompute (`work/live_bets_out.txt`): 45 bets, 25-19-1, +7.20 units, ROI +16.0% (SE 16.9%). Expected wins 24.3 ± 3.2 (model) and 21.8 ± 3.2 (market).
  - My slices (record / ROI / value at close):

    | Slice | Record | ROI | Value at close |
    |---|---|---|---|
    | Spreads | 13-8-1 | +17.5% | -2.1% |
    | Moneylines | 12-11 | +14.5% | -3.4% |
    | Favorites | 10-6 | +7.6% | -4.3% |
    | Underdogs | 15-13-1 | +20.6% | -1.9% |

  - By edge bucket (`work/live_edge_slices_out.txt`):

    | Edge bucket | Record | Value at close |
    |---|---|---|
    | Spread 1.5-2.5 | 3-6 | 0.0% |
    | Spread 2.5-3 | 5-1-1 | -3.5% |
    | Spread 3+ | 5-1 | -3.6% |

    The rising spread ROI is not matched by better prices.
- **What's costing points.** The repo has no slices by market, favorite/underdog, odds bucket or edge bucket, so this is the "expected wins and topline" level.
- **Confidence.** High.

### 5c. Closing line value and value at the price taken: 0 / 6
- **Evidence.**
  - Value at the price taken on the final card: **-2.77% a bet, SD 5.2%, SE 0.78%, t -3.56, n 45**. This matches the repo's `scorecard.value_at_price` exactly.
  - Without the largest news-driven move (CIN +2.5, Lamar out, +23.2%): -3.36% (t -6.48).
  - Spreads -2.10% (t -1.60); moneylines -3.41% (t -3.92). First-published card -2.75% (t -3.14).
  - CLV from the first-published number (repo `card_clv`, 49 bets):
    - Spreads +0.33 pts (t 0.97); converted with the key-number table, +1.5% (t 1.63).
    - Moneylines +0.10% (t 0.27).
  - CLV from the final card: spreads +0.39 pts (t 1.48), moneylines +0.14% (t 0.38).
  - Measurement is mostly correct: same-book FanDuel close, de-vigged at both ends for moneylines, key-number-aware value, reported every week.
- **What's costing points.**
  - Value at the price taken is significantly negative (t <= -2), which is the Zero anchor. The bets roughly matched the close and paid the vig.
  - Minor method issue: spread CLV in probability uses a single per-point value at the line taken (`betlog.clv_for_row`) rather than summing across key numbers.
- **Confidence.** High.

### 6a. Hold-out profitability of the selection rules: 4 / 6
- **Evidence.** The canonical replay card at closing prices and juice:
  - 649 bets, 355-283-11, won 55.6% vs a 56.0% break-even (the model said 61.5%).
  - **ROI +0.72% (SE 3.59%)**, 95% interval -6.3% to +7.8%.
  - Spreads +2.43% (SE 4.59%); moneylines -2.52% (SE 5.67%).
  - By season: -8.9, +4.5, +4.0, +8.3, -4.8%.
- **What's costing points.** ROI >= 0 but not significant.
- **Confidence.** High.

### 6b. Bigger edges, better bets? Edge math: 2 / 4
- **Evidence.**
  - Edge math is right: single-book (FanDuel) matched-pair de-vig, push probability from the tilted margin distribution, key numbers kept, real juice, and an EV>0 gate at the actual price (`model._recommend`, `market`, `shop`).
  - Outcomes by edge on all qualifying hold-out bets (`work/edge_buckets_out.txt`):

    | Bucket | ROI |
    |---|---|
    | Spread 1.5-2 | +2.4% |
    | Spread 2-2.5 | -10.4% |
    | Spread 2.5-3 | +21.9% |
    | Spread 3+ | -0.4% |
    | Moneyline 3-5% | +4.5% |
    | Moneyline 5-8% | -19.2% |
    | Moneyline 8%+ | -18.5% |

  - By the model's chance of winning:

    | Tercile | All qualifying bets | Card |
    |---|---|---|
    | Lowest chance | +6.0% | +12.1% |
    | Highest chance | -8.1% | -9.7% |

    The card ranks bets by chance.
- **What's costing points.** Outcomes do not improve with edge size; edges behave like noise.
- **Confidence.** High.

### 7. Locked choices work as designed (bug check): 2 / 3
- **Evidence.**
  - Every Week 3-7 bet, final and first-published (32 final, 25 first), has `odds_source` = fanduel, with the FanDuel moneyline pair.
  - Only spreads and moneylines.
  - $5 on every model bet from Week 4. Checked in the slates for Weeks 4 and 7 and in the Week 5 and 6 workbooks. The two Thursday bets, TB +8.5 and DEN +2.5, were checked in the earlier builds' workbooks.
  - Cards ran 7, 7 and 7 in Weeks 5-7, with no filler needed.
- **What's costing points.** One deviation: a bug in the FanDuel-only path, active through Week 7. When FanDuel posted no spread price, the stored nflverse (DraftKings) price was used and still labeled "fanduel". It was fixed 10/29 (commit 3c648af) with a regression test. Raw odds pulls were never kept, so I cannot verify that no archived spread price was borrowed.
- **Confidence.** Medium.

## C. Weekly inputs and process (8 / 18)

### 8a. Quarterback starters: 1 / 5
- **Evidence.** Each week's `meta.json` starters compared with the actual starters (nflverse attempts leader, after the stale-QB fix; `work/qb_check_out.txt`):

  | Week | Team | Assumed (source) | Started |
  |---|---|---|---|
  | 1 | ATL | Tua Tagovailoa (depth chart) | Cooper Rush |
  | 7 | TB | Jalon Daniels (override) | Baker Mayfield |
  | 7 | NYG | Jameis Winston (depth chart) | J.J. McCarthy |

  The TB error was caught only in a scratch-copy Sunday run, never in his files.
  - None changed a pick or a bet.
  - ATL @ PIT: PIT was picked, and Rush is weaker than Tua.
  - TB @ CAR: CAR by 3.2 with Daniels, and Mayfield is worth about 2.4 pts, so still CAR. The scratch run added no TB bet.
  - NYG @ HOU: a 0.1-pt swing.
- **What's costing points.** 3 wrong starters in the final picks falls in the 3-4 band.
- **Confidence.** High.

### 8b. Injuries and late news by game day: 1 / 3
- **Evidence.**
  - OPERATING.md has a Saturday/Sunday roster run.
  - Archive generation times: Weeks 1 and 2 Wednesday, Week 3 Saturday, Weeks 4-5 Sunday, Week 6 Saturday, Week 7 Wednesday. The Week 7 Sunday run happened in a scratch copy only.
  - **Week 5:** the Sunday run updated the archive, but the workbook he kept shows the Friday card. The disk copy he last saved 10/13 and all three backups in `output/superseded/` (10/09 10:01, 10/09 13:07, 10/12 10:28) have:
    - MIN -1.5, CIN -320, TEN +7.5, NYG +3.5 at -102.
    - The NYG@WAS pick as WAS.
  - The archive's final card is Sunday's:
    - MIN -2.5, TEN +6.5, CHI -120; CIN dropped.
    - The pick is NYG.
  - His tracker's Week 5 bets follow the Friday card: CIN -322, TEN +7.5, MIN "1.5". He did not bet CHI.
- **What's costing points.** The refresh was skipped or did not reach him in 4 of 7 weeks (1, 2, 5, 7).
- **Confidence.** Medium-high. How the Friday card came back is inferred from timestamps and his entries.

### 8c. Prices match what he can bet: 1 / 2
- **Evidence.**
  - No "still a bet at" number exists anywhere in the code or workbook; the only guide is "Re-run Sunday morning with --refresh before placing anything".
  - The Weeks 1, 2 and 7 cards used Wednesday prices.
  - At FanDuel's close, with the model's published view, 7 of 45 bets no longer qualified because the number moved:
    - From mid-week cards (4 of 20): NO +250 to +275, CIN +2.5 to -3, MIA +205 to +166, DET -172 to -205.
    - From game-day cards (3 of 25): MIA +10.5 to +9.5, NYG +118 to +114, BUF -245 (fair price moved).
  - Two Week 1 underdogs were already beyond today's +250 cap when published (`work/still_qualifies_out.txt`).
- **What's costing points.** Mid-week prices with no guide to whether a moved line still qualifies.
- **Confidence.** High.

### 9a. The weekly procedure produces the right files: 1 / 4
- **Evidence.**
  - All Weeks 1-7 archives exist and are locked.
  - Git history shows no archive file changed after its lock.
  - The Bet Log matches the archive cell for cell.
- **What's costing points.** Three procedure failures:
  1. The Week 7 game-day run that should have updated the real files happened only in a scratch copy.
  2. Week 5: the archive's final card is not the card in the workbook he kept and bet from.
  3. First-published numbers for Weeks 1-4 were not preserved.

  "One or two" failures earns 2, and the files are not "unreliable" (0). I scored 1 between the two; see Rubric gaps. The `grade.py` scorecard bug is charged under 1c, not here.
- **Confidence.** Medium.

### 9b. Tests and guards: 4 / 4
- **Evidence.** `pytest tests/ -q`: 236 passed. Each of the five known past bugs has a regression test:

  | Past bug | Regression test |
  |---|---|
  | Sign convention | `test_model.py::test_ticket_sign_matches_the_real_bet` (plus sign tests in closing, teamstats, trends) |
  | Mixed-book de-vig | `test_weekly_tune.py::test_single_book_uses_only_that_books_numbers` |
  | Market-prior leak | `test_model.py::test_market_ratings_respect_asof_cutoff`, `test_deployed_model_is_leak_free` |
  | QB override | `test_model.py::test_qb_override_actually_reaches_the_projection` |
  | Tracker carry | `test_tracker_carry.py` |

  The 10/29 borrowed-price fix also has a test.
- **What's costing points.** Nothing. There is no test for the `grade.py` matching bug.
- **Confidence.** High.

## D. Excel workbook (9 / 10)

Evidence is the Week 8 workbook, with Week 7 as the previous save, both opened as copies.

### 10a. Numbers and formulas correct: 4 / 4
- **Evidence.** Everything checked matched (`work/wb_betlog_check_out.txt`):
  - **Picks:** all 14 games (pick, opponent, win %, margin, moneyline, favorite/underdog) match `week08_picks.csv`.
  - **Weekly Slate:** 84 cells match the archive and slate output: both moneylines, spread, edge and home win % for every game, plus the pick's win %.
  - **This Week's Bets:** all 6 bets match `week08_leans.csv` (side, market, odds, $5). 'Bet Wins %' is within 0.0003 of my recomputation.
  - **Bet Log, 107 games:**
    - Pick, win chance, final score, winner, right/wrong, favorite at publication and favorite right all match the archive and results.
    - The 45 model bets' results and value at close match to 1e-16.
    - The summary formulas evaluate to 64/106, a favorite baseline of 67/106, value picks 12/23, and -2.77% over 45 bets.
  - **Bet Tracker:** all 42 filled cells equal FanDuel's archived closes. The P&L, CLV and bankroll formulas are correct.
  - **Chart Data:** the formulas are correct by reading (cumulative counts and profit, W/(W+L), break-even |odds|/(|odds|+100) or 100/(odds+100), weekly SUMIFS). I did not evaluate them in Excel.
- **What's costing points.** Nothing material. One cosmetic glitch: "DEN -0.0".
- **Confidence.** High.

### 10b. His Bet Tracker carried, charts updated: 3 / 3
- **Evidence.**
  - A cell diff of A1:P500, Week 7 vs Week 8, shows exactly 42 changes, all previously blank Closing Line / Closing Odds cells now filled with FanDuel's recorded closes (his 10/29 request).
  - K6 (his Kalshi converter), M5 `=SUM(H12:H300)`, J6 and every formula are identical.
  - The 3 charts he kept are redrawn at the same anchors (R12, AB12, R29), reading Chart Data rows 2-491. The 4th, which he deleted, was not restored.
  - The fill is reported on its own line (`excel._tracker_carry_line`) and in CLAUDE.md: "2,242 cells exact, K6/M5 named, 3 charts redrawn, 42 blank closing cells filled".
- **What's costing points.** Nothing.
- **Confidence.** High.

### 10c. Usable and honest: 2 / 3
- **Evidence.**
  - Every game's straight-up pick is ranked by confidence.
  - Every bet is shown with its price and $5 stake.
  - The Bet Log has a favorite baseline and value at FanDuel's close.
  - The Reference verdict is honest: no proven edge, 66.0 vs 66.5, card +0.7% (SE 3.6%), "the record ran ahead of the bets".
- **What's costing points.** Stale or wrong statements:
  - "These lose more often and are sized to match" (This Week's Bets). Every bet is a flat $5.
  - The Reference sheet's backtest block still says model MAE 10.15, "+0.39 pts worse". That contradicts its own headline of 9.88 vs 9.76.
  - "The four charts" when three remain.
  - "Home field ~2.1" next to "+1.29 used".
  - The coarse calibration summary ("84% won 81%") hides the 82% vs 76% bucket.
  - His tracker's headline Avg CLV (pts) is now about +1.21. It is inflated by his own sign typos (MIN "1.5" and JAX "2.5" show +4.0 and +5.0) and alt lines. Corrected, it is about +0.2. The review prints +1.21 without a caveat; only CLAUDE.md notes it.
  - The model's own CLV in points appears only in the terminal review, not in the workbook.
- **Confidence.** Medium-high.

---

## Biggest point losses (top 5)
1. **5c, -6.** The bets have not beaten FanDuel's close.
   - Value at the price taken is -2.77% a bet (t -3.56, 45 bets).
   - CLV is about zero: spreads +0.33 pts (t 0.97), moneylines +0.1% (t 0.27).
   - The 25-19-1 record is about 1 SD above market expectation (21.8 ± 3.2): luck, not price.
2. **2c, -4.** Calibration: the 80-85% bucket said 82.2% and won 76.0% (-6.25 pts on 104 games). This is knife-edge on a 6-pt cut and within noise. The model is mildly overconfident (slope 0.93; picked side 0.88).
3. **8a, -4.** Three wrong starters in the final picks: Week 1 ATL, Week 7 TB and Week 7 NYG. The TB error was caught only in a scratch copy. None changed a pick or a bet.
4. **9a, -3.** Three process failures:
   - The Week 7 roster run happened in a scratch copy only.
   - The Week 5 workbook he kept and bet from shows Friday's card while the archive records Sunday's.
   - Weeks 1-4 first-published numbers were lost.
5. **1b, -2 (tied with ten other -2 items).** Picks against the favorite win 46.8% (52/111) on the hold-out and 2-5 live. The best-tested rule (a 0.25 model/market blend, 66.69%) beats both the model (65.99%) and the favorite (66.48%) and is not used. Of the tied items, **1c** (the `grade.py` rematch/tie bug) is the cheapest to fix.

## What's genuinely strong
- **The replay is faithful and reproducible.**
  - It matches the live path to 0.0, and the caches equal the live loaders.
  - Every documented headline number reproduced exactly.
  - The 10/29 fix made the live and replayed market prior use the same lines.
- **The reporting is honest.**
  - The workbook and review lead with "no proven edge".
  - They show the favorite baseline and value at the close, and label the record as running ahead of the prices.
  - This is rare and correct.
- **The edge math is right:** single-book matched de-vig, push-aware cover chances that keep key numbers, real juice, and an EV>0 gate at the actual price.
- **The workbook is correct and his tracker is respected.**
  - Every spot-checked cell matched.
  - His cells, formulas and chart choices were carried exactly; only his requested fills were added, and they were reported.
- **Guards:** 236 passing tests, a regression test for every known past bug, and locks on every played week.
- **Pieces were cut on evidence.** EPA/play and the self-tune were dropped when the hold-out said so, and the kept pieces (market prior, trend pull, injuries) each help measurably.

## Rubric gaps
- **9a** has no anchor for three or more failures when the archive files themselves are intact. I scored 1, between "1-2 failures" (2) and "unreliable" (0).
- **3a.** It is unclear whether the grader's reconstruction of the market prior, QB fit and home field counts as the ablation being "reported". I took the lower level (3). My reconstruction shows none of the three hurts, so it is 5 if it counts.
- **1c.** The Full conditions are met by `review_week.py`, but `grade.py` is also named as evidence and is wrong. The anchors do not say how to weigh a wrong second report. I took the lower level (2).
- **2c.** The Zero cut ("any bucket off by more than 6 pts") ignores sampling error. The failing bucket is -6.25 pts at n 104 (1.7 SE).
- **5c.** Value at the price taken is measured at the close including the vig. A bettor with exactly zero CLV scores about -2% to -3% a bet, which is "significantly negative" over 45 bets. To clear the Zero anchor, a model must beat the close by about the vig. That is a fair bar, but it is steep.
- **8a** counts wrong starters regardless of impact. None of the three mattered here.
- **7.** It is not stated whether a latent bug that cannot be shown to have fired counts as a deviation. I counted it.
- **10a** lists Picks, Weekly Slate, Bet Tracker and Chart Data. A stale number on the Reference sheet fits 10c better, and I scored it there.

## Couldn't verify
- Whether the borrowed-spread-price bug fired on any archived Week 3-7 spread price. Raw odds pulls were never stored.
- That the Weeks 1-2 archive files are exactly what was shown. They were first committed 9/25, after those games were played. Their book (before the FanDuel-only rule) also could not be checked.
- The Week 8 run's terminal output, which is not archived. The tracker-report line was checked from the code and CLAUDE.md.
- Chart Data and summary formulas as evaluated by Excel. I did not open his Excel, to avoid touching his session, and verified the logic by reading and recomputing.
- How the Friday card came back into the Week 5 workbook (his open Excel window, or bets placed before the Sunday run). The outcome is verified; the mechanism is inferred.
- Kickoff times on This Week's Bets.
