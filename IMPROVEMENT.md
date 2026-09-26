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

**Blowout guard, same day (`resid_clip = 7`).** Each game's miss is clipped
to ±7 points before the memory learns from it, so one upset (Week 3 TNF,
ATL 35-14 over a 6-point GB favourite) cannot rewrite a team. Swept clip
{4, 7, 10, 14} × alpha {0.1–0.4} with the 1-pt ceiling:

- MAE: clipping helps a little in BOTH blocks (alpha 0.15, clip 7: hold-out
  10.073 vs 10.079; tuning 10.138 vs 10.148). Kept.
- Value picks (ATS on edges ≥ 1.5 vs the close): no setting beat the frozen
  model on the hold-out (48.5–50.1% vs 50.13%); on the tuning seasons all
  settings were slightly above (52.7–53.4% vs 52.5%). Opposite signs across
  blocks, ±1.8% standard error: **the self-tune does not improve value bets.**
- Offered "tune the winners only, value bets on the frozen model"; Jameson
  chose to run the tune on everything. Recorded here so the choice is clear
  when CLV is reviewed.

### SHIPPED — miss-trend checker: fix REASONS, not games (2026-09-26)

Jameson's design, in his words: don't "make the Falcons the #1 team because
they looked good", but "if you are missing games because of some particular
reason, that should be adjusted in the model" — e.g. "always picking the
biggest underdog and it's consistently wrong".

`src/nflmodel/trends.py`, run weekly by `scripts/miss_report.py`, writes
`data/trends.json` (tracked); `run_week.py` applies whatever it marks
confirmed. ~28 candidate reasons: line size, home/road dog, divisional,
early/late season, rest, bye (13+ days), Thursday road, body clock, time
zones, new QB (no start for the team in its last 4 games), inexperienced QB,
after blowout win/loss, turnover luck, score-vs-EPA luck, wind, rain/snow,
cold, pass-heavy offense in bad weather, low/high total, night games,
neutral site, model far from the line, home field.

**The gate, per reason** (rebuilt after the adversarial audit below):

1. single-reason screen: Benjamini-Hochberg (FDR 10%) on 2013-2020, same
   sign on 2021+, and the SHRUNK 2013-2020 effect lowers 2021+ error;
2. joint SELECTION on 2013-2020 only: forward selection by
   leave-one-season-out error (a reason must cut it by 0.002+ pts);
3. joint PRUNE on 2021+: each selected reason must help 2021+ alongside the
   others (drop-one); 2021+ can only remove reasons, never add them;
4. the final set must beat the unfixed model on 2021+ with paired t >= 2;
5. live values: ridge on every graded game, shrunk n/(n+170), a reason past
   1.5 pt is FIXED at 1.5 and the rest refit around it; <= 2.0 pt per game.
6. watch-list reasons can be promoted PROSPECTIVELY (2013-2020 is frozen):
   40+ live games since 2026, same sign as history, one-sided p < 0.05 —
   then they still face step 3.

**Result (2026-09-26, 3,595 graded games incl. 33 from 2026):** ONE margin
fix survives — *when the model disagrees with the line by 3+ points, pull it
1.5 pts toward the line* (2013-20 −3.0, 2021+ −5.5; 2021+ average miss
10.13 → 10.02, paired t = 6.0). Big favorites (+2.3/+2.6), mid favorites,
home dogs, divisional dogs, night favorites and new QB (−3.1/−2.0) are all
real and consistent on their own but COVERED: once the line-disagreement fix
is in, none of them improves 2021+. They are one cause — the model's
compressed spreads (0.77 pt per point of market line) — seen through
different windows. Late-season favorites was selected on 2013-2020 but made
2021+ worse and was pruned. Honest reading: this is the model trusting the
line more where it disagrees most, i.e. the known no-edge finding (README)
surfacing as a trend. Capped at 1.5 so the model keeps an opinion.

**Longshots:** dogs at +151 or longer are overrated in BOTH periods even
after the margin fix (z = +6.9 and +5.1): +401 dogs said 23.7% / 24.7%, won
11.5% / 13.2%. Symmetric recalibration of win probability,
logit(p') = b·logit(p) (no intercept, so the pick always matches the margin
sign and nothing is added at neutral sites), fit on 2013-2020 on top of the
margin fix: +401 → 14.7% / 15.7%; 2021+ log loss 0.6297 → 0.6248. Confirmed
by a TAIL test (the problem lives in the tail; an all-games t-test, t = 1.5,
buries it). Plus Jameson's cap: no moneyline dogs longer than +250
(`THRESHOLDS.ml_max_underdog`, was 600) — a hand-set rule, labeled as such.

Replayed bets 2021+: underdog share 88% → 68%, moneylines longer than +250
162 → 0, return −1.8% → −3.6% (noise; SE ~3%). **The fixes make predictions
better and stop the longshot habit; they do not create an edge.**

Watching, not applied: rest edge, inexperienced QB (−1.0/−0.9), after a
21+ win (the ATL case: +1.6 then +0.3), score-beat-EPA luck, favorites in
wind (+0.1/+2.7), favorites in rain/snow (+3.2/+2.0), pass-heavy offense in
bad weather, low totals.

### Adversarial audit of the trend checker (2026-09-26)

Before the checker drove real bets, 11 agents audited it (leakage, signs,
statistics, weather/workbook), each finding re-checked by a skeptic. Fixed:

- **Fixes would have been applied twice from Week 4.** Archived picks hold
  the post-fix margin; the next check treated it as raw. Now every archived
  pick carries `raw_margin` (before trend fix and self-tune), `trend_adj`,
  `selftune_adj` and the pick-time `spread_line`; the history uses
  `raw_margin`; the EPA self-tune learns against its own shipped number minus
  `trend_adj`. Verified: history == pre-fix margin, max diff 0.0.
- **Set-level confirmation.** 4 of 7 "confirmed" reasons made 2021+ worse
  individually → the per-reason gate above.
- **Calibration intercept** put the 50% crossover at a +0.35 home margin
  (pick disagreed with margin; home term at neutral sites) → symmetric fit.
- **Clipped coefficients** ran a combination never fit → capped ridge.
- **Live "far from the line" test** saw the self-tuned projection while
  history was frozen → first pass subtracts `selftune_adj`.
- **Weather**: live flags used the 4-hour max wind / mean temp vs history's
  single kickoff reading → flags now use the kickoff hour (display keeps
  the max). Gamebook "chance of rain"-style wording no longer counts as rain;
  missing schedule wind/temp filled from the gamebook text. Paris, Munich and
  Melbourne were coded as domes (all open-air) → fixed; Madrid retractable.
- New-QB rule flagged a starter back from one missed game → "no start for
  this team in its last 4 games". Off-bye was rest >= 10 (includes post-TNF
  mini-rest) → >= 13.
- Bet-type z-test exploded on zero-variance groups (12 straight losses =
  p 0) → such groups are not evidence.
- Workbook: Rio game labeled a DAL home game (duplicate `neutral` merge);
  Game Detail drivers did not sum to the projection (now shows self-tune and
  trend rows); the Miss Report called the hand-set +250 cap a learned fix.
- Mid-week rerun stamped Thursday's carried pick with its own time and fix
  state → `meta["carried"]` keeps the original publish time per game.

Known and accepted: history uses observed kickoff weather while live uses a
forecast (weather reasons are watch-only, so no live effect today); published
2026 rows use the actual starter and closing line rather than pick-time values.

### SHIPPED — self-tune learns from EPA, not the score (2026-09-25)

Why the score-based tune could not work: the ratings are re-fit on every game
every week, so last Sunday's score is already in them. Nudging by the same
score counts it twice. An adjustment can only help if it learns from
information the ratings do not use.

`scripts/adjust_lab.py` (on frozen walk-forward projections from
`scripts/build_base_projections.py`) tested six signals × shrinkage × ceiling
× strength = 180 configs, choosing on 2013-2020 and confirming on 2021-2025:
score, score minus turnover luck, score minus fumble luck, EPA margin,
EPA/score blend, and result vs the closing line.

- Only **EPA margin** (how well each team played, play by play) improved
  accuracy on both blocks broadly. Fine grid (half-life 3/6/10, clip 7/14/none,
  alpha 0.5/1/2) by per-game ceiling, share of 27 configs improving hold-out MAE:
  **0.5 pt: 27/27** (mean −0.012) · 1.0: 15/27 · 1.5: 6/27 · 2.0: 1/27.
- The "diminishing returns" is about the SIZE of the move, not the strength of
  learning. At a 0.5-pt ceiling alpha 0.5, 1 and 2 are indistinguishable.
- Value picks (ATS ≥ 1.5 vs close) are **not** improved: 10/27 configs better
  on hold-out, mean −0.23 pts. An early hl3/clip7 slice showed +0.5-0.8 ATS; the
  grid showed it was a lucky slice.
- Per-season: 7 of 13 seasons improve. Shuffling which team gets each EPA
  residual makes it clearly worse (40/40 shuffles), so the signal is real
  information — just small.

Shipped: `SELFTUNE = signal epa, alpha 1.0, half-life 3, clip 14, ceiling 0.5`.

### REJECTED — weather × team style (2026-09-25)

Jameson's hypothesis: a pass-reliant offense with a weak run game
underperforms in rain/snow/wind. `scripts/fetch_weather_history.py` pulls the
gamebook weather line (precipitation) for 2016-2025; `scripts/weather_style_test.py`
builds each offense's pre-game pass-minus-rush EPA/play and tests
bad-weather × style-difference against the model's and the market's misses.

| | 2016-20 (fit) | 2021-25 (hold-out) |
|---|---|---|
| bad weather (precip or wind ≥ 15), n | 177 | 164 |
| slope vs model miss | **+13.1 (t +2.1)** — pass teams did BETTER | −1.9 (t −0.3) |
| precip only, n | 81 | 78 |
| slope vs model miss | +6.5 (t +0.8) | −8.3 (t −0.9) |

Opposite of the hypothesis in the fit block, gone in the hold-out; applying
the fit slope made hold-out bad-weather MAE worse (9.99 → 10.29). Also checked
"skip value bets in bad weather": 53.6% in 2016-20, 42.3% in 2021-25 — does
not replicate. Nothing shipped. (Cold ≤ 32°F showed 39.6% on 53 value picks;
post-hoc and small — watch, don't act.)

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
