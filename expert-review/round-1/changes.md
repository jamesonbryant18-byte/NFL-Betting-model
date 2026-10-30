# Round 1: changes made (2026-10-29)

Approved by Jameson: every fix except 1 (favorite-based straight-up pick: "basic and
boring") and 10 (game-day guardrails: his own check before betting), plus the
FanDuel-label bug, plus his answers A-D. Branch `expert-review/round-1`, one commit
per fix, then merged to `main`. Full test suite after every commit; 236 pass at
the end (179 + new tests; the 2 long-failing test_history tests now pass).

| fix | commit | what changed | how it was verified |
|---|---|---|---|
| 9. replay matches live | 6e1720b | `ratings.fit_market_ratings` uses lines from weeks up to and including the week being predicted, never a later week, live and in the replay alike. Leak test now keeps the current week's lines and checks its results/scores are never used. | `tests/test_model.py` leak test; live and replay projections now agree. |
| 5. failing tests | ae76675 | `closing.py` looks up `archive.ARCHIVE_DIR` at call time, so a test's scratch archive is honored. | Both `test_history` CLV tests pass. |
| 4 + 8. factors and self-tune | 99ffe88 | `config.FACTORS` = `inj_total 0.637, rt_rest_diff 0.048` (EPA/play dropped); `SELFTUNE` alpha 0. New `src/nflmodel/replay.py` (canonical replay) and `scripts/refit_factors.py`. `run_week` records weights and self-tune state in `weekNN_meta.json`. | `refit_factors.py` on 2021-25 (fit 2013-20): no factors SU 65.4% / error 9.944 / card -3.5%; injuries + rest 66.0% / 9.876 / +0.7%; + EPA 66.0% / 9.881 / -2.4%. New tests: FACTORS keys, self-tune off. |
| 2 + 6. win-% slope, caches | 1177230 | `trends.run_all` adds the live game factors (`replay.history_factor_points`) before fitting the win-% slope and replaying bets. Caches rebuilt with the live loader. `data/trends.json` regenerated. | Live slope 1.483 -> 1.402; 2021-25 base MAE 10.079 -> 10.026; trend gate re-run: the one live fix still confirmed (9.99 -> 9.91), long-dog recalibration still confirmed. Old caches kept in the scratchpad. |
| 3. honest scorecard | 028858b | New `src/nflmodel/scorecard.py`; `review_week.py` gains VS THE FAVORITE and GOOD OR LUCKY? (from the archive only, answer C); moneyline CLV de-vigged at both ends; non-FanDuel closes flagged. New `scripts/replay_deployed.py`, `scripts/ablation.py`. | `tests/test_scorecard.py` (5 tests). Weeks 1-7: model 64-42 vs favorite 67-39; card 25-19-1, value at the price taken -2.8% a bet (+/- 1.5%). |
| FanDuel label bug | 3c648af | `shop._attach_single_book`: a spread price borrowed from the stored line is labeled as such, used only for the same number (else -110 assumed and labeled), and the run warns. | New test in `tests/test_weekly_tune.py`. |
| A. tracker closes | 2583252 | `history.tracker_close_fills` + `excel._fill_tracker_closes`: FanDuel's recorded close into Closing Line / Closing Odds cells he left blank; the carry check expects exactly those fills and prints them on their own line. | `tests/test_tracker_carry.py`; dry run on his Week 7 save: 42 cells on 28 rows, his 2,242 cells and formulas (K6, M5) carried exactly. |
| 7. workbook honesty | ac13373 | 'Bet Wins %' = the bet's own chance; Bet Log adds Favorite, Favorite Right?, Model Bet Value @ Close and two scoreboard lines; Reference verdict and hold-out numbers rewritten from `replay_deployed.py`. Future workbooks only. | Week 8 dry run in a scratch copy of the repo; Weeks 1-7 workbooks untouched (checksums). |
| B. card ranking | (no code change) | Tested a model/market blend for the edge (w x model + (1-w) x market): w chosen on 2013-20 (0.35: +9.0% vs +4.2%), on 2021-25 no weight beats the live w = 1 (+0.72%; 0.75 -2.88%, 0.5 -0.47%, 0.35 -2.06%, 0.25 +0.96%; SE about 4%). | Logged in IMPROVEMENT.md. Recommended not to switch; his call. |
| D. rubric | (rubric v2) | Value at the price taken added to 5c ("a small difference can be neglected" = the 4/6 anchor); canonical replay required as evidence; workbook evidence = the two latest workbooks; tracker fills are not carry errors. v1 saved as `rubric-v1.md`. | v1 and v2 scores are not strictly comparable. |
| docs | (docs commit) | CLAUDE.md section 0 entry and stale sections (1b, 5, 7, 9); OPERATING.md weekly loop and current setup; IMPROVEMENT.md log entries. | Read back. |

## A correction to the fix list

Fix 8 said the self-tune "costs 0.85 pt of SU (t -2.1)". That was measured with the
EPA/play factor still in: both read EPA, so it was counted twice. With the EPA factor
dropped (fix 4), `ablation.py` shows the self-tune neutral (no gain, no loss). It is
off because it adds nothing, not because it hurts. Jameson is told this plainly.
