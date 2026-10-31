# Report card

| round | date | rubric | score | grader |
|---|---|---|---|---|
| 1 | 2026-10-28 | v1 | 40 / 100 | fresh subagent |
| 2 | 2026-10-29 | v2 | 55 / 100 | fresh subagent |
| 3 | not run | v2 | | |

v1 and v2 are not strictly comparable: v2 grades the model on its own card and adds
value at the price taken. Most of the 40 to 55 is real: the replay matched live, the
factors that hurt were dropped, and the reports became honest.

## By section (round 2)

| section | max | round 2 |
|---|---|---|
| A. Model picks | 45 | 26 |
| B. Bets | 27 | 12 |
| C. Weekly inputs and process | 18 | 8 |
| D. Excel workbook | 10 | 9 |

## What round 2's fixes should move (to be confirmed by a fresh grader)

All ten were applied (`round-2/changes.md`). The fix list estimated about 66-70 if
all landed. Points most likely to come back: 1c (season scorecard), 5b (slices), 5a
(ledger), 3a (full ablation), 3c (design questions tested), 4a (leak closed, choices
disclosed), 2c (only partly: the 80-85% bucket still fails by 2.3 SE), 8c (still a
bet at), 9a/8b (only going forward: Weeks 5 and 7 already happened).

## What still costs points, and why it was not fixed

- **5c, 6a, 6b (about 10 points):** the bets match FanDuel's close and pay the vig.
  Value at the price taken is -2.8% a bet live; the hold-out card is break-even at
  best. Nothing in the process can create an edge the model does not have.
- **1b, 2a, 2b:** the closing line is more accurate than the model, and taking every
  favorite picks as many winners. Expected for a model with no proven information
  beyond the line. He declined favorite-based pick rules in round 1.
- **2c:** picks the model calls 80-85% win about 74% on the hold-out. Recalibrating to
  that bucket on the hold-out itself would be fitting to the test.
- **Past process misses** (Weeks 1, 5, 7) cannot be undone.

## Open strategy questions

- Rubric v3 gaps from round 2 (calibration sampling error; 9a anchor for three or more
  failures): not taken up. Adding them makes v3, not comparable with v2.
- Whether to run round 3 now or after more live weeks. With the bet side capped by the
  absence of an edge, the next real information is live 2026 straight-up results and
  CLV, which arrive one week at a time.

## Honest paragraph

The project is now well instrumented and honest about itself: one replay of the model
as it runs, no known leaks, every piece measured, and a record of every bet that grades
it on value at the price taken, which luck cannot move. What it does not have is an
edge. It picks winners at about the closing favorite's rate, its margins are a little
worse than the line, and its bets pay the vig. The next level is not more process; it is
information the market does not already price, and every candidate tested so far
(situational spots, weather, EPA, self-tuning, QB double counting, a smooth trend pull)
either failed or was neutral out of sample.
