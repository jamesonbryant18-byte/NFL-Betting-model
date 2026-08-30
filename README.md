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
| **Deployed model MAE** (what `run_week.py` runs) | — | **10.08 pts** |
| Closing line MAE | 10.02 pts | **9.76 pts** |
| ATS @ 1.5pt edge | 53.2%, +1.6% ROI | **48.6%, −7.3% ROI** |
| ATS @ 1.5pt, deployed | — | **50.1%, −4.3% ROI** |
| ATS @ 3pt edge | 53.8%, +2.7% ROI | **48.5%, −7.3% ROI** |
| Moneyline @ 3% edge | — | **38.8%, −9.5% ROI** |

The "deployed" rows matter because they describe `NFLModel` with market-prior
blending — the object `run_week.py` actually constructs. An earlier version of
this backtest validated a bare ridge fit while the weekly script shipped
something else, so the headline number described an estimator nobody ran.

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

## A leak worth documenting

While validating the deployed path, the market-prior blend briefly reported
**56.5% ATS on the hold-out with z > 2** — a result that would have looked like
a genuine, bettable edge.

It was a bug. `fit_market_ratings` was being called without its as-of cutoff, so
replaying a completed season let the preseason prior see every closing line in
that year, including games that had not happened at the simulated moment. The
leak moved ratings by 0.8 points and manufactured the entire result. With the
cutoff applied the same configuration gives 50.1% and −4.3% ROI.

Two things are worth taking from that. First, a leak does not announce itself —
it announces success, which is exactly when scrutiny is weakest. Second, the
fix that introduced it was a `str.replace` that silently matched nothing;
`tests/test_model.py::test_deployed_model_is_leak_free` now asserts the full
deployed path is invariant to whether future games exist in the input, because
a comment claiming leak-freedom is worth nothing.

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
- **Key numbers are modeled explicitly**, by exponential tilting of the
  empirical margin distribution: start from the observed frequency of every
  integer margin, then tilt it to the mean this game projects. Tilting shifts
  the mean without smearing the shape, so the spikes survive. Football scores
  in 3s and 7s — a game lands on exactly 3 about **4.7x** as often as on 4, and
  the model reproduces 3.5x of that. Adding noise to a continuous projection
  and rounding, which is what this did first, reports a flat push probability
  at every line and is wrong by roughly 9x on a three-point spread.
- **Live odds across six books** via `src/nflmodel/odds.py` (Action Network,
  keyless), with ESPN as a DraftKings cross-check. Line shopping runs behind a
  median-deviation guard: on a live Week 1 slate one book's feed was
  sign-inverted and unguarded shopping reported a **phantom 3.0-point better
  line**, which at a 1.5pt threshold manufactures a bet out of a data error.

## Using it week to week

See **[OPERATING.md](OPERATING.md)** for the weekly procedure, what to log, and
the decision gate that determines whether this is ever worth betting.

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
| away travelled east / west 2+ zones | −0.73 / +0.56 | −1.46 / +1.15 |
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

**Separate offense/defense ratings were rejected.** Fitting a team's offense
and defense as distinct parameters moved hold-out MAE by 0.0014 (paired
t = -0.08) — a no-op. Worth understanding why: in a *margin* regression the
offense and defense columns are algebraically identical, so the split is only
even identified when fitting points-scored, and there it adds nothing.

**Blowout dampening was rejected.** Capping margin-of-victory helped 0.023 pts
(t = -1.83, not significant), and its premise is backwards anyway — the
baseline's OLS slope on the tuning seasons is 1.087, meaning the model is
*under*-confident, not inflated by blowouts.

**480 subset hypotheses were tested. Zero survived.** Spread magnitude,
home/away dog, week ranges, divisional, primetime, dome/outdoor, rest, season,
and which side the model picked — none clears Bonferroni, BH-FDR, or a
permutation max-z test. Only 1 of 48 subsets beats break-even in both eras
where 12 would be expected if the model were genuinely bettable, and
tuning-selected subsets have **zero** predictive value out of sample (r = -0.03).
The model is below break-even across essentially the whole market, not merely
on average. Subset filtering cannot rescue it.

**The most decisive single result:** fitting a model directly to
`result - spread_line` — the beat-the-line target — drives the optimal ridge
penalty to infinity *even on the tuning seasons*. Where overfitting is not just
allowed but rewarded, the best available action is still to not deviate from
the closing line at all. And the blend curve says the same thing in one line:
the tuning-optimal amount of this model to mix into the closing line makes the
hold-out **worse** than the raw line. The optimal weight is zero.

## The benchmark, and why openers do not rescue it

Every number here is measured against **closing** lines. That provenance is
verified, not assumed: against Sportsbook Reviews Online's open/close archives
(3,766 games, 2007-2021), nflverse's `spread_line` sits **0.27 points from the
close and 1.33 points from the open**, matching the close exactly 61% of the
time versus 20% for the open.

It is tempting to think betting Tuesday openers instead of Sunday closers
would rescue the model. It would not, and the number is small enough to say so
flatly: **the entire open-to-close accuracy gap is 0.14 points of MAE** (10.50
vs 10.35). The model is 0.39 points worse than the close. Openers close about
a third of that deficit — the model still loses to an opening line on raw
accuracy, in both the tuning and hold-out samples.

An ATS simulation against openers superficially looks profitable (55.3%, +5.4%
ROI at a 3pt edge over 2013-2021). **That is a false positive** and it is worth
naming why, because it is the exact trap this project is built to avoid: those
seasons are mostly the tuning window, no threshold reaches p < 0.05, the clean
2021 hold-out gives 49.70% and -5.09% ROI, and the "edge" is substantially just
predicting the market's own open-to-close move (slope +0.349, t = +21.7).

So: no demonstrated edge at any line, opening or closing.

The cheap way to keep testing is CLV — log the model's leans and the number
available when you see them, and compare against the close. Positive CLV over a
few dozen games is real evidence. That costs nothing to run, and it is what the
tracker's CLV columns are for.

## Line shopping is worth more than the model

Real spread juice ranges from about **+100 to -133**, not a flat -110, and half
a point of spread is worth more than anything these ratings can find. The model
has been measured at zero incremental signal; the number you get filled at has
not. If you want an edge in this project, that is where it is — which is the
argument for an Odds API key and multi-book coverage, not for more feature
engineering.

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
  odds.py         live multi-book odds + guarded line shopping
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
