# Round 2: fix list (score 55 / 100, rubric v2)

Round 1 was 40 / 100 on rubric v1. v1 and v2 are not strictly comparable (v2 grades the
model on its own card and adds value at the price taken), but most of the gain is real:
the replay now matches live, the factors that hurt are gone, and the reports are honest.

Verified by me before listing (not just taken from the grader):
- `scripts/grade.py` `season_scorecard` matches picks by team pair with no week filter
  (`g.iloc[0]`) and scores a tie as a loss (`won = actual > 0`). Run now, it grades
  Week 8's unplayed rematches (CLE@PIT, PHI@WAS, KC@DEN) with earlier meetings.
- His kept Week 5 workbook (and the 10/12 10:28 backup) shows Friday's card: MIN -1.5,
  CIN -320, TEN +7.5, NYG +3.5 -102, pick WAS. The archive (generated 10/11 15:58 UTC)
  has Sunday's: MIN -2.5, TEN +6.5, CHI -120, CIN dropped, pick NYG. The Sunday rebuild
  happened while Excel had the file open; his next save put Friday's version back.
- `trends.margin_model_for_history()` builds the win-% margin table from every season
  2010-2025, so the 2021-25 replay sees its own outcomes.
- Stale text: excel.py 844 ("sized to match"), 2341 ("four charts"), 2516 ("~2.1"),
  107 ("84% won 81%"); README 22, 83, 330 and the old -0.018 (t -0.1).

## Fixes (applied only on approval)

1. **Fix the season scorecard (`grade.py`)**: match each pick to its own week's game, score ties as ties, add the favorite baseline and noise band; regression test.
   Criterion: 1c | Est. gain: +2 | Effort: S | Risk: low
   Why: it now prints 64-46 (58.2%) on 110 games; the right answer is 64-42 vs the favorite's 67-39. It will misgrade every rematch from here on, and OPERATING.md runs it weekly.

2. **Bet slices in the weekly review**: record, ROI and value at the close by market, favorite/underdog, odds bucket and edge bucket, each with its noise band.
   Criterion: 5b | Est. gain: +2 | Effort: S | Risk: low
   Why: the full anchor needs slices. They also answer "great or lucky" by type of bet (e.g. live spread edges 3+ went 5-1 but at -3.6% value: lucky).

3. **Stale and wrong text**: "sized to match" (every bet is $5), the Reference backtest block (MAE 10.15, +0.39), "four charts" (three), "Home field ~2.1" next to +1.29 used, calibration shown in 5-pt buckets with counts, a caveat on his tracker's Avg CLV (his two sign typos and alt lines push it to +1.21; about +0.2 corrected), README's information-beyond-the-line number (+0.34, t 1.86, not -0.018).
   Criterion: 10c (+3b, 4b docs) | Est. gain: +1 | Effort: S | Risk: low

4. **Close the replay's last leak, and say where 2021-25 was used**: build the win-% margin table from 2013-20 only when scoring 2021-25; list on the Reference sheet the choices that looked at 2021-25 (trend-fix gate, dropping EPA, self-tune off), so 2026 live is named as the only untouched test.
   Criterion: 4a | Est. gain: +1 to +2 | Effort: S | Risk: low
   Why: the leak flatters the hold-out by about 0.3 pt straight up. Honest numbers get slightly worse (and the 80-85% calibration bucket goes from -6.3 to -7.1).

5. **A graded ledger of every model bet** (new derived file; the locked archive is not touched): each bet's own chance (cover % for spreads), both spread prices where archived, stake, result, P&L, close and value at the close, Weeks 1-8 on.
   Criterion: 5a | Est. gain: +1 | Effort: S | Risk: low
   Why: those fields are now recomputed at review time or live only in overwritten files. Weeks 1-4's first-published numbers can't be recovered.

6. **"Still a bet at" on every bet**: the worst line or price at which each bet still clears the bar (e.g. "PHI +5.5, still a bet at +4.5"), in the run and on This Week's Bets.
   Criterion: 8c | Est. gain: +1 | Effort: S-M | Risk: low
   Why: 7 of 45 bets no longer qualified at FanDuel's close. This was part of round 1's fix 10, which he passed on as his own job; it makes that game-day check a glance. If he says no again, it is dropped for good.

7. **Complete the ablation**: add the market prior, the joint QB fit and home field (each a full walk-forward without that piece) to the repo's ablation.
   Criterion: 3a | Est. gain: +2 | Effort: M | Risk: low
   Why: three of nine pieces were never measured on the deployed stack. The grader's own rebuild says none hurts; the repo should show it.

8. **Test the two untested design questions**, fit on 2013-20 and checked on 2021-25, ship only what holds: (a) the market prior already contains each team's QBs and the model adds the QB again; (b) the trend pull's 3-pt cliff vs a smooth pull.
   Criterion: 3c (+ straight-up accuracy, his first goal) | Est. gain: +1 | Effort: L | Risk: medium
   Why: both were flagged 10/14 and never measured. They are the two places a real accuracy gain could still hide.

9. **Game-day runs always reach the record**: if Excel has the week's workbook open, the run still updates the archive, saves the new workbook beside his (never over it), prints what changed on the card, and says "close Week N, open the new file". It also flags any `--qb` override the latest depth chart contradicts.
   Criterion: 8b, 9a, 8a | Est. gain: 0 now (Weeks 5 and 7 already happened) | Effort: M | Risk: medium
   Why: in 2 of 7 weeks the game-day card never reached the files (Week 7 scratch copy only; Week 5 overwritten by his open window). This protects every week from now on, starting this Sunday. Also part of round 1's fix 10, but this part is about the model's record, not his checks.

10. **Walk-forward win-% calibration**: in the replay, fit the slope each season on prior seasons only (as live does), and report the 5-pt reliability table with counts.
    Criterion: 2c | Est. gain: 0 to +2 (uncertain) | Effort: M | Risk: low (live already uses the latest fit)
    Why: the model is mildly overconfident (slope 0.93; the 80-85% bucket said 82%, won 76%, n 104).

If all ten land: about 66-70. The rest does not move without a real edge.

## Points that will not come back

- **5c (-6), 6a (-2), 6b (-2)**: the bets match FanDuel's close and pay the vig (value at the price taken -2.77% a bet, t -3.56; hold-out card +0.7%, SE 3.6%; bigger edges are not better). Nothing here creates an edge.
- **1b (-2)**: the only rule that beat taking the favorite was a 25% model / 75% market blend (66.69% vs 66.48%, inside the noise, found on the hold-out itself). He passed on favorite-based rules in round 1.
- **2a, 2b (-1, -2)**: the closing line is more accurate than the model, as expected.
- **8a, 8b, 9a, 5a (part)**: Weeks 1, 5 and 7 process misses and Weeks 1-4 first-published numbers already happened.

## Rubric gaps flagged by the grader (adding any makes rubric v3)

- 2c's zero cut ignores sampling error (-6.25 pts on 104 games is 1.7 SE). Suggest: a bucket fails only if off by more than 6 pts AND more than 2 SE.
- 9a has no anchor for three or more failures with intact files. Suggest: 3+ failures = 1.
- Others (3a reconstruction, 5c steep bar, 8a impact-blind, 7 latent bug, 10a vs Reference): leave as is.
