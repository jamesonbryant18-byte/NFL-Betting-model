# Round 1: fix list (score 40 / 100)

Graded by a fresh, independent grader against rubric v1. Full report: `round-1/grade.md`; its scripts and outputs: `round-1/grader-work/`. Spot-checked by the reviewer: the hold-out "base model vs favorite" gap (-2.04 pts, 175 disagreements won 41.7%) and the Week 7 workbook's "Win Chance" column (DEN -4.5 shows 76%, its game win %) both reproduce.

| Area | Score |
|---|---|
| A. Model picks (1-4) | 14 / 45 |
| B. Bets (5-7) | 11 / 27 |
| C. Weekly inputs (8-9) | 7 / 18 |
| D. Workbook (10) | 8 / 10 |

## What's working (keep it; do more of it)
- **Leaning toward the betting line when the model is far from it** (the "trend pull"): the single most helpful piece on 2021-25 (margin error t -5.1, Brier t -5.1, SU +0.5 pt).
- **Non-QB injuries factor**: margin error -0.07 pts (t -2.5).
- **Market prior** (starting from the market's view of teams): margin error -0.06 (t -2.5).
- **Clean data**: no leak found; a from-scratch walk-forward rerun reproduces the cached hold-out exactly.
- **Workbook**: 363 spot-checked cells all correct; his tracker carried cell for cell; his kept charts updated, the deleted one stayed gone.
- **Locked rules** run exactly as set; pricing math is sound; every past bug has a regression test.
- The model as it runs now carries some information beyond the line (coefficient +0.30, t 1.9), more than the project's own "zero" claim, but not proven.

## What isn't working, and why
- **Straight-up picks lose to the favorite**: 65.3% vs 66.5% on 2021-25 (17 fewer winners over five seasons). When the model picks against the favorite it wins 43.7% (59/135); live 2 of 7. The pick is the model's own win %, with no market check.
- **Overconfident probabilities**: picks it calls 67% win 59%; picks it calls 82% win 73%. The win-% correction was fit on an older stack (base + trend) and is applied on top of the factors and self-tune, which already stretch the numbers.
- **Two pieces hurt**: the EPA/play factor (worse SU, error and Brier; Brier t +2.5; the repo's own factor lab rated efficiency "no help"; this season's factor check has it hurting 28 games, helping 19) and the weekly self-tune (SU -0.85 pt, t -2.1, no error gain) when run on top of the factors.
- **Bets are break-even at best**: the card replayed on 2021-25 at closing prices returns +0.0% (SE 3.4%); bigger edges do not win more; the model says its card bets win 63%, they win 57%. This season, valued at FanDuel's closing prices, the card's bets averaged about -2.8% per bet (t -3.6) and his own about -3.9%. The 25-19-1 card is about one SD above what the closing market expected.
- **Inputs and process**: 3 wrong QB starters in final picks (none flipped a pick or bet); 3 of 7 weeks had no game-day update reaching his files (Week 7's ran only in a test copy); no "still a bet at" number for game day.
- **Reporting**: no favorite baseline anywhere; CLV computed with method errors (moneylines not de-vigged, one DraftKings close, alt lines counted as CLV); "Win Chance" on spread bets shows the game win % (DEN -4.5: 76%, real chance about 55%); the Reference sheet still says "advisory mode, stakes $0"; 2 tests failing; caches stale.

## Fixes (applied only on approval)
Every model change below is chosen on 2013-20 and checked once on 2021-25; a change ships only if it holds there. If #9 is approved it runs first, because every other test should be measured on the model as it runs live.

1. **Straight-up pick from a better rule**: test four rules (model only; favorite only; favorite unless the model is very sure the other way; model + market blend), pick on 2013-20, confirm on 2021-25, use the winner for the SU pick and its win %.
   Criterion: 1a, 1b | Est. gain: +6 to +10 | Effort: M | Risk: low (does not change bets)
   Why: his #1 goal. The grader's exploration put the better rules at 66.6-67.1% vs the model's 65.3% (about 3-5 more correct picks a season).
2. **Refit the win-% correction on the model as it actually runs.**
   Criterion: 2c (2b) | Est. gain: +2 to +4 | Effort: S | Risk: low-med (moneyline bets and card ranking use these numbers; the card replay is re-checked)
   Why: fixes the 67%-said / 59%-won overconfidence at its cause.
3. **Honest scorecard in the weekly reports**: SU vs the favorite (at publication and close, with a band, each against-the-favorite miss labeled); expected wins under the model's and the market's odds; break-even vs actual; slices; CLV done right plus "value at the price taken"; his bets vs the card's numbers; a repo ablation script.
   Criterion: 1c, 5b, 5c, 6c, 3a | Est. gain: +5 to +8 | Effort: M-L | Risk: none (reporting only)
   Why: this is how "good, not lucky" gets measured every week.
4. **Turn off the EPA/play factor** (keep injuries; refit the remaining weights).
   Criterion: 3a (+ small SU/error gain) | Est. gain: +2 | Effort: S | Risk: low
5. **Fix the 2 failing tests** (`test_history`, known since 10/8).
   Criterion: 9b | Est. gain: +2 | Effort: S | Risk: none
6. **Rebuild the stale caches** with the live data loader, then re-check the trend gate (documented procedure, CLAUDE.md section 9).
   Criterion: 4b | Est. gain: +2 | Effort: S | Risk: low
7. **Workbook honesty**: "Win Chance" shows each bet's own chance (cover % for spreads); fix the stale advisory-mode text; add the favorite baseline and CLV to the Bet Log. Future workbooks only; past weeks untouched.
   Criterion: 10c | Est. gain: +2 (lands with the Week 8 workbook) | Effort: S | Risk: low
8. **Turn off the weekly self-tune.** This reverses his 2026-09-25 choice ("tune everything"). New evidence: on top of the factors it costs 0.85 pt of SU (about 12 picks over 2021-25, t -2.1) and improves nothing.
   Criterion: 3a | Est. gain: +1 to +2 | Effort: S | Risk: low
9. **Make the replay match live**: live, the market prior uses this week's lines and lines already posted for future weeks; the replay uses neither (projections differ by 0.34 pt on average; MAE 10.079 vs 10.022). Replay includes the week's own line, as the game-day run does; live stops using future weeks' lines. Re-measure everything on the matched model.
   Criterion: 3c (4a) | Est. gain: +1 to +2 | Effort: M | Risk: med (every hold-out number shifts)
10. **Game-day guardrails**: every bet shows "still a bet at" (the worst number or price where it still qualifies); every run checks each `--qb` override against the latest depth chart and flags stale ones (Week 7 TB); a game-day run updates the archive and a game-day card even while his workbook is open, so it never ends up test-copy only.
    Criterion: 8c now; 8a, 8b, 9a in future weeks | Est. gain: +1 now | Effort: M | Risk: low
    Why: worth more than its points. It stops bets placed at numbers that no longer qualify (Week 7 CIN +2.5 at -199).

## Bug in a locked part (FanDuel only)
- `shop._attach_single_book` fills a missing FanDuel spread price with the stored DraftKings price and still labels the row "fanduel". Fix: record where each price came from and never present a borrowed price as FanDuel's. Effort S.

## Needs your input
- **Closing numbers on your Bet Tracker are blank on all 28 rows**, so the tracker's own CLV cells are empty. The model already records FanDuel's closes each week. Do you want it to fill in only the "Closing Line" and "Closing Odds" columns on your tracker? Nothing else on the sheet would change.

## Strategy questions
- **S1. Should bets use the model + market blend too?** The card says 63% and wins 57%, bigger edges do not win more, and professionals compute edges from a blend. Testing it costs nothing; switching would mean fewer bets clear the bar, and the 4-bet minimum would be filled with labeled near-misses (card size stays as locked). Recommendation: test it, switch only if 2021-25 improves.
- **S2. Your own bet choices.** On the 22 bets you shared with the card, your numbers and prices (alt lines, moved lines) cost about 1.6% per bet compared with the card's. Example: CIN +2.5 at -199 after the card's bet had stopped qualifying. Option: bet the card's number, or skip when the game-day number is past "still a bet at" (fix #10). Your call.

## Rubric gaps flagged by the grader (adding any makes rubric v2; v1 and v2 scores are not strictly comparable)
- 5c: also score "value at the price taken" (after FanDuel's cut), not only line movement. Recommended.
- 1a/6a: name one canonical "deployed model" replay (the script from fix #3) so every round measures the same thing. Recommended.
- 8b: count only weeks after the game-day procedure started (Week 5 on).
- 3a: when metrics disagree, a component "hurts" only if it is worse with no significant offsetting gain.

## Points that will not come back this round
About 10 points grade Weeks 1-7 as they happened (wrong QBs, missed game-day runs, early weeks' missing first-published numbers). Several more need a real edge or market-level accuracy, which no fix can promise. Realistic score after all ten fixes: about 65-80. Above 95 is not reachable this season with honest numbers.
