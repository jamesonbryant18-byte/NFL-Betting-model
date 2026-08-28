# NFL Betting Model

Points-based power ratings for NFL spreads and moneylines, with walk-forward
validation and bet tracking. Built for the 2026 season.

## Read this first

**The hold-out backtest found no edge against closing lines.** The model ships
in advisory mode: it computes and displays everything, reports LEANs rather
than BETs, and stakes nothing. That default is a finding, not a placeholder.

Here is the number that matters, from 1,424 games in seasons the model's
parameters were never tuned on:

| | tuning seasons (2013-20) | hold-out (2021-25) |
|---|---|---|
| Model MAE | 10.19 pts | 10.15 pts |
| Closing line MAE | 10.02 pts | **9.76 pts** |
| ATS @ 1.5pt edge | 53.2%, +1.6% ROI | **48.6%, −7.3% ROI** |
| ATS @ 3pt edge | 53.8%, +2.7% ROI | **48.5%, −7.3% ROI** |
| Moneyline @ 3% edge | — | **38.8%, −9.5% ROI** |

On the seasons used for tuning, this looks like a winning model. On unseen
seasons it loses money at every threshold. That gap is what overfitting looks
like, and it is the single most useful thing this repository produced.

The decisive test — regressing actual results on both the closing line and the
model's projection — gives the model an incremental coefficient of **−0.018
(t = −0.1)** out of sample. Zero. Every piece of information in the model is
already in the line.

Turning this into a bet-placing system takes one line (`ADVISORY_MODE = False`
in `src/nflmodel/config.py`). Nothing in the code stops you. But you would be
betting on a model that has been measured and does not beat the market, and
you should know that before you do it rather than after.

## What it does

```
team + QB power ratings  →  projected margin  →  cover / win probabilities
                                              →  compare vs de-vigged market
                                              →  edge  →  Kelly stake
```

- **Ratings** are ridge-regularized least squares over every game, so they are
  opponent-adjusted. Fit in points: a rating of +4.0 means four points better
  than an average team on a neutral field.
- **Quarterbacks** are fit jointly with teams rather than bolted on. About 15%
  of team-games are started by a non-primary QB and that swing is worth ~6
  points — bigger than home field. Decomposing them improved out-of-sample MAE
  by 0.096 pts.
- **Home field** is fitted at ~2.1 points, not the folklore 3. The fanless 2020
  season came in at 0.17, which is good evidence the effect is really crowd.
- **Early season** defers to ratings backed out of posted spreads. In Week 1
  the model has seen no 2026 football while the market has priced every
  offseason move; without this the model invents 5-point edges out of its own
  ignorance. The deference decays as real games accumulate.
- **De-vigging** happens before any edge is computed, using multiplicative,
  power, or Shin's method. Two sides at −110 sum to 104.8%; comparing a model
  against raw implied odds measures edge against a price shaded against you.
- **Push probability** is modeled explicitly. Whole-number spreads push ~2.7%
  of the time and that mass has to come out of both sides.

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/python scripts/run_backtest.py          # validate + freeze params
.venv/bin/python scripts/run_week.py              # this week's slate
.venv/bin/python scripts/run_week.py --week 5     # a specific week
.venv/bin/python -m pytest tests/ -q              # 18 invariant tests
```

Output lands in `output/` as a terminal report, a CSV, and an Excel workbook
(Weekly Slate / Game Detail / Power Ratings / Bet Tracker / Reference).

## What was tested and rejected

Situational adjustments were measured against 5,431 games of closing lines
from 2006-2025. The test is not "does this factor affect the game" — of course
rest and weather do, and the market knows. The test is whether the market
*misprices* it, because that residual is the only place edge can live.

| factor | ATS residual | t |
|---|---|---|
| home off bye | −0.27 | −0.44 |
| away off bye | −0.94 | −1.33 |
| short week (either side) | −0.21 / −0.20 | −0.27 / −0.26 |
| wind ≥ 15 mph | +0.16 | +0.24 |
| cold < 32°F | +1.13 | +1.33 |
| 2+ timezone crossing | +0.56 / −0.73 | +1.15 / −1.46 |
| Week 17 | +1.03 | +1.35 |
| divisional game | −0.36 | −1.23 |
| favorite of 10+ | +0.71 | +1.48 |

Not one reaches |t| = 2. Across ~15 hypotheses you would expect a couple of
false positives at that bar by chance, and there were none — so this is not
"underpowered, probably real". The market's overall mean residual is −0.04
points, unbiased to four hundredths of a point over two decades.

All of these therefore ship at **zero**. They are not missing; they were tested
and rejected. Rerun `scripts/measure_situational.py` each offseason.

**EPA was also rejected.** The regression target was designed to blend scoring
margin with EPA-implied margin. Grid search says use none of it — MAE degrades
monotonically as EPA weight rises (10.19 → 10.23 → 10.29 → 10.35). The ridge's
opponent adjustment already captures what EPA was meant to add. The code stays
parameterized so this is one config value away if it ever changes.

## An important caveat about the benchmark

Every number here is measured against **closing** lines, because that is what
nflverse stores. The closing line is the hardest forecast in sports to beat —
it has absorbed all week's information and money.

If you bet Tuesday openers rather than Sunday closers, you are playing a
genuinely easier game, and this backtest does not measure that. It is not
evidence the model beats openers; it is a limit on what was tested. The cheap
way to find out is CLV: bet nothing, log the model's leans and the number
available when you see them, compare against the close. Positive CLV over a
few dozen games is real evidence. That is what the tracker's CLV columns are
for, and it costs nothing to run.

## Layout

```
src/nflmodel/
  config.py       every tunable, nothing hardcoded elsewhere
  data.py         nflverse fetch + cache (schedules, closing lines, QBs, EPA)
  ratings.py      ridge power ratings, QB decomposition, market-implied fit
  market.py       odds conversion, de-vigging, margin→probability, Kelly
  adjustments.py  situational factors (all measured to zero — read the header)
  model.py        the prediction pipeline
  backtest.py     walk-forward validation
  excel.py        workbook builder
scripts/
  tune.py                 grid search on tuning seasons only
  run_backtest.py         hold-out validation, freezes parameters
  run_week.py             weekly slate + workbook
  measure_situational.py  re-test situational factors
```

## Data

All free, no API keys required:
- `nflverse/nfldata` — schedules, closing spreads and moneylines, rest days,
  weather, starting QBs, 1999-present
- `nflverse-data` — play-by-play with EPA, 1999-present

## Honest limits

- A 53% ATS model needs several hundred bets before its win rate is
  distinguishable from noise. Judge by CLV first and P&L much later.
- Ratings are relative and fitted; they are not truth, and Week 1 ratings in
  particular are mostly the market's opinion wearing the model's clothes.
- Staking rules control the *rate* of ruin. They do not remove it.
