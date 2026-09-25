# How this model improves

> The short version: the model grades every prediction it has ever made, every
> week, and hunts for patterns in its mistakes. Patterns that survive a
> multiple-comparison correction become *candidates*. A candidate only becomes
> a change if it improves accuracy on seasons it was not discovered in. Most
> candidates die there, and that is the system working.

This document exists because "the model should be constantly improving" is
correct, and because the obvious way to do it — see what missed on Sunday,
adjust on Monday — makes the model measurably worse. Both of those statements
are demonstrated below with numbers from this repo.

---

## What already updates on its own

Every weekly run refits the ratings on **every game ever played**, through last
week, with an exponential recency weight (`recency_decay = 0.98`). Nothing is
stale, nothing is manual. A team that has been better than expected for a
month already carries a higher rating by the time it is projected again.

That is the legitimate form of learning from results: more data, refit from
scratch, no human in the loop. It happens automatically in
`scripts/run_week.py` and needs no permission.

What does **not** move on its own is the tuning — ridge penalty, recency
decay, home field, the QB term, bet thresholds. Those change only through the
protocol below.

---

## The weekly grade

```bash
.venv/bin/python -W ignore scripts/grade.py --save
```

Every prediction published this season, graded, whether or not a bet was ever
placed. Wagering is a downstream decision; accuracy is the product.

| section | question it answers |
|---|---|
| Straight up | how many picked winners actually won |
| Average error | how many points off the projected margin was |
| **Closing line error** | **the same number for the market — the benchmark** |
| Directional bias | does it lean home or away overall |
| Calibration | when it says 65%, does 65% happen |
| Value picks | the record of picks that disagreed with a price |
| Biggest misses | the games to actually look at |

The benchmark line is the one that matters. Being 11.8 points off is not good
or bad in isolation — NFL scores are violent. It is good or bad relative to
the closing line's error on the same games, because that is the number you
would have to beat to have an edge.

`--save` appends to `data/scorecard.json` so the season accumulates.

---

## The systematic error hunt

```bash
.venv/bin/python -W ignore scripts/grade.py --diagnose --scope all
```

A single week is noise. The hunt therefore runs over **walk-forward
predictions across 2010-2025** — every game, each one predicted using only
data that existed before it kicked off — and splits the errors into segments:
home favorites, dogs, spread buckets, divisional games, rest, dome/outdoors,
weather, early/late season, and which side the model disagreed with the line
on.

For each segment it reports the mean signed error, a t-statistic, and a
p-value, then applies **Benjamini-Hochberg at FDR 5%**. That correction is not
bureaucracy. Testing 22 segments at p<0.05 produces about one "significant"
result by chance every single time. Without the correction this script would
manufacture a discovery every week, forever.

### Reading a flag correctly

Two of the segments that flag are **artifacts by construction**, and knowing
this prevents a wasted month:

- `model likes home` (+1.71) and `model likes away` (-1.85) condition on the
  *sign of the model's own deviation*. Conditioning on your own error's
  direction guarantees apparent bias in that direction. It is the winner's
  curse, not a finding.
- `home favorite` / `home underdog` condition on the line, which correlates
  with the same thing.

What all of them actually encode is one claim: *the model's deviations from
the market are too large.* That claim is testable, so it was tested.

---

## The bar a change must clear

A candidate is a hypothesis, not a fix. Promoting one requires all four:

1. **State it as a correction before testing it.** Written down, with a sign
   and a magnitude. No fishing for the version that works.
2. **Fit it only on the discovery block.** Never on the seasons that will
   judge it.
3. **Improve out-of-sample accuracy** on seasons it was not discovered in —
   `scripts/run_backtest.py` (2021-2025 hold-out) or
   `scripts/selftune_sweep.py`.
4. **Log the result either way**, below. Rejected ideas are the most valuable
   content in this repo, because they stop the same idea being re-proposed
   every season.

Weekly results never clear this bar. At a true 53% ATS rate it takes roughly
1,100 bets for a win rate to separate from a coin flip. At ~9 value picks a
week that is over six seasons. A 16-game week moves a percentage by six points
on one result, and the adjustment it tempts you into will always be in the
direction that felt worst on Sunday.

---

## Log of tested candidates

### REJECTED — weekly self-correction from recent error (2026-09-22)

The direct implementation of "see what you got wrong, adjust." After each week
every team's residual (actual margin − projected margin) is folded into an
exponentially-weighted memory, and the next week's projection is nudged by
`alpha * (correction[home] − correction[away])`. `alpha = 0` is the frozen
model, so the comparison is exact. Code: `src/nflmodel/selftune.py`, swept by
`scripts/selftune_sweep.py`.

Hold-out seasons 2021-2025, memory half-life 3 weeks:

| alpha | MAE | vs frozen | SU% | ATS ≥1.5 |
|---|---|---|---|---|
| 0.00 (frozen) | **10.079** | — | 64.4% | 50.13% |
| 0.10 | 10.078 | −0.001 | 64.3% | 49.11% |
| 0.25 | 10.130 | +0.051 | 64.4% | 48.30% |
| 0.50 | 10.345 | +0.265 | 63.7% | 49.34% |
| 0.75 | 10.660 | +0.581 | 62.2% | 49.11% |
| 1.00 | 11.065 | +0.986 | 61.9% | 49.03% |

Accuracy degrades monotonically with how hard the model chases recent error.
The `alpha = 0.10` row is a no-op, not a win: paired t-test on absolute error
gives **t = −0.08, p = 0.93** on the hold-out (95% CI −0.033 to +0.031) and
**t = −1.41, p = 0.16** on the tuning seasons. Value picks get *worse* at every
setting — ATS at the 1.5-point threshold never again reaches the frozen
model's 50.13%.

Robustness: the same shape holds at memory half-lives of 3, 6 and 10 weeks,
with league-wide home-field adaptation switched on, and with residuals carried
across the offseason. It also holds **on the tuning seasons**, where
overfitting is rewarded — the best alpha there is 0.10 for a 0.019-point
gain that does not clear significance.

The mechanism of the failure is visible in the `|adj|` column of the sweep: at
alpha = 0.5 the correction moves projections an average of 2.27 points, which
is larger than home-field advantage, on the evidence of a handful of games.

### SHIPPED (by choice, not by evidence) — gentle weekly self-tune (2026-09-25)

Jameson wants the model to learn from its misses each week without chasing
them. Shipped the same mechanism as above with a per-game ceiling added
(`max_adj`): `config.SELFTUNE = alpha 0.15, half-life 3, ceiling 1.0 pt/game`.
Corrections come from this season's ARCHIVED projections vs results
(`selftune.live_corrections`), so they learn from what was actually published.

Hold-out 2021-2025 with the 1-point ceiling:

| alpha | MAE | vs frozen | SU% | ATS ≥1.5 | mean move |
|---|---|---|---|---|---|
| 0.00 | 10.079 | — | 64.4% | 50.13% | 0.00 |
| 0.10 | 10.077 | −0.002 | 64.2% | 49.32% | 0.46 |
| 0.15 | 10.075 | −0.004 | 64.4% | 49.17% | 0.58 |
| 0.20 | 10.075 | −0.005 | 64.6% | 48.84% | 0.66 |

Honest reading: the ceiling removes the damage the uncapped version did, and
what is left is noise — 0.004 points is not an improvement, and ATS on value
picks drifts down ~1 point. It is safe, not helpful. Side effect seen live in
Week 3: a 1-point nudge flips marginal games across the bet threshold (added
ARI ML, NE +2.5, IND ML; dropped PIT +3.5; MIA spread became MIA ML).
Set `alpha = 0` to turn it off.

### REJECTED — shrink or extend the model's deviations (2026-09-22)

The claim the flagged segments actually encode. Discovery block 2010-2020,
n = 2,939: regressing actual result on the projection gives

```
result = 1.1379 * projection − 0.486      (slope SE 0.0474)
```

The slope is **2.91 standard errors above 1.0** — the model looks reliably
*under*-confident, p ≈ 0.004. A textbook finding.

Applied to the 2021-2025 hold-out it was not fitted on:

| multiplier | hold-out MAE | vs frozen |
|---|---|---|
| 1.000 (frozen) | **10.0793** | — |
| 1.138 (fitted on 2010-2020) | 10.0982 | +0.019 |
| 0.95 | 10.0909 | +0.012 |
| 0.90 | 10.1031 | +0.024 |
| 0.80 | 10.1433 | +0.064 |

Every direction is worse. The significant in-sample bias did not replicate.
Leaving the projections alone is optimal, and this is the clearest example in
the repo of why step 3 exists: with only step 1 and a p-value, this ships.

### Previously rejected

See README.md for 480 subset hypotheses, EPA blending, separate offense/defense
ratings, blowout dampening, and nine situational factors — none of which
survived. Of particular relevance here: fitting directly to `result −
spread_line` drives the optimal ridge penalty to infinity *on the tuning
seasons*, where overfitting is rewarded. Where the math is allowed to cheat,
the best available action is still to not deviate from the closing line.

---

## Where improvement is actually available

The grading has been unambiguous about this. The largest single miss of the
2026 season is Week 2 Atlanta: projected +0.2, actual −31.0. The ratings were
not the problem. The model had Cooper Rush at quarterback and Tua Tagovailoa
started.

That is a **process defect**, and process defects are the one category that
gets fixed immediately, without waiting for a hold-out test, because they are
wrong regardless of whether the pick won:

- wrong starting quarterback (twice in 2026 through Week 2, both Atlanta)
- stale depth chart or injury data
- a missing game, a stale line
- a data pipeline that silently no-ops

`scripts/run_week.py --starters` lists all 32 with their source, and the run
warns when the depth chart is more than 36 hours stale. Checking the four or
five quarterbacks whose status is genuinely in doubt is worth more accuracy
per week than any tuning change in this document.

The second place real improvement lives is **price**, not prediction. See
"Line shopping is worth more than the model" in README.md.
