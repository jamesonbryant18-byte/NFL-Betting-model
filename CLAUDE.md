# CLAUDE.md — context for a fresh session

Read this before touching anything. It is the accumulated result of a long
build-and-audit cycle (2026-08-28 to 08-31, including a 54-agent adversarial
audit) and it exists so you do not re-derive, re-measure, or re-break what is
already settled.

Owner: Jameson. Repo: `jamesonbryant18-byte/NFL-Betting-model` (private).
Working copy: `~/Desktop/NFL-Betting-model`. Python: `.venv/bin/python`
(always pass `-W ignore`).

---

## 1. The one thing that matters

**This model has no demonstrated edge against NFL closing lines.** It ships in
advisory mode — full analysis, "LEAN" not "BET", zero stakes — and that default
is a measured finding, not an unfinished feature.

Hold-out (2021-25, seasons the tuner never saw), n = 1,424:

| metric | model | closing line |
|---|---|---|
| MAE (bare ratings) | 10.154 | **9.762** |
| MAE (deployed `NFLModel`) | 10.079 | **9.762** |
| ATS @ 1.5pt edge | 50.1%, −4.3% ROI | break-even is 52.38% |
| Moneyline @ 3% edge | 38.8%, −9.5% ROI | |

The decisive test: regress actual result on **both** the closing line and the
model's projection. The model's incremental coefficient on hold-out is
**−0.018 (t = −0.1)**. Zero information beyond the line. The line's coefficient
is 1.07.

The tuning seasons (2013-20) showed 53.2% ATS and +1.6% ROI. That gap *is* the
overfitting, made visible. Never quote tuning-season numbers as results.

**Do not turn `ADVISORY_MODE` off on your own initiative.** It is one line in
`config.py` and it is Jameson's decision, not yours.

---

## 2. Dead ends — do NOT redo these

Every row was measured on this repo's data. Re-running them wastes tokens and
reaches the same answer.

| idea | result | verdict |
|---|---|---|
| EPA-blended regression target | MAE degrades monotonically 10.19 → 10.23 → 10.29 → 10.35 as EPA weight rises | rejected; `epa_margin_weight = 0` |
| Separate offense/defense ratings | hold-out 10.1530 vs 10.1544, paired t = −0.08 | no-op. In a *margin* regression the two columns are algebraically identical |
| Blowout / MOV dampening | +0.023 pts, t = −1.83 | not significant, and premise is backwards — baseline OLS slope is 1.087, i.e. under-confident |
| Rest (bye, short week) | t = −0.44 / −1.33 / −0.27 / −0.26 | market prices it |
| Weather (wind ≥15, ≥20, cold <32°F) | t = +0.24 / −0.44 / +1.33 | market prices it |
| Travel / timezone crossing | t = −1.46 / +1.15 | market prices it |
| Divisional games | t = −1.23 | market prices it |
| Week 17 / 18 motivation | t = +1.35 / +1.45 | market prices it |
| 480 subset hypotheses | 0 survive Bonferroni, BH-FDR, or permutation max-z | no bettable subset exists |
| Subset replication | tuning-selected subsets have r = −0.03 out of sample | zero predictive value |
| Opening lines instead of closing | entire open-to-close MAE gap is **0.14 pts** vs a 0.39 pt deficit | cannot rescue the model |
| ATS vs openers (looks like 55.3%!) | tuning-window artifact; clean 2021 hold-out gives 49.70%, −5.09% | **false positive** |
| Beat-the-line regression | optimal ridge → ∞ *even on tuning seasons* | strongest evidence against any persistent-mispricing edge |
| Blending model into the line | tuning-optimal weight makes hold-out **worse** than the raw line | optimal weight is zero |

Situational factors ship at **zero** in `config.Adjustments`. They are not
missing — they were tested and rejected. Across ~15 hypotheses none reached
|t| = 2, and the market's overall mean ATS residual is −0.04 points.

The only thing that reliably improved accuracy was **leaning harder on the
market**, monotonically — which is the signature of a model whose own signal is
noise being averaged away. Take the accuracy, never call it model improvement.

---

## 3. Gotchas that have already caused real bugs

1. **Sign convention.** `spread_line` is *points the HOME team is favored by*
   (positive = home favored). A bet ticket shows the **negation**: a 7-point
   home favorite reads `DET -7.0`. This shipped inverted once and printed the
   opposite side of every game. All display must route through
   `market.format_spread()`. Internal math (`spread_edge_pts`,
   `projected_margin`, cover probabilities) uses the raw convention — do not
   negate those.

2. **The market-prior leak.** `fit_market_ratings` MUST be called with
   `asof_week=`. Without it, replaying a completed season sees every closing
   line in that year. This moved ratings 0.8 pts and fabricated a **56.5% ATS
   hold-out at z > 2** — a result that looked like a genuine edge. Guarded by
   `test_deployed_model_is_leak_free`. If a result suddenly looks good, suspect
   a leak before believing it.

3. **Verify your edits actually applied.** A `str.replace` that matched the
   wrong indentation silently no-opped, and a fix was claimed in a commit
   message that had never landed. Assert the target exists before writing.

4. **QB names are only populated for PLAYED games.** An upcoming slate has
   none, which silently collapses the QB term to replacement on both sides
   where it cancels out — making the whole decomposition inert.
   `ratings.projected_starters()` carries them forward. Week 1 uses the prior
   season's *most frequent* starter **excluding Week 18**, because Week 18 is
   where playoff teams rest everyone (naive last-starter gave KC "Chris
   Oladokun" instead of Mahomes). Neither can know offseason moves — use
   `--qb TEAM="Name"`.

5. **Only grid-searched keys may be frozen** to `data/fitted_params.json`.
   Freezing the whole dataclass once pinned hand-set judgment values —
   `market_prior_weight` ran at a stale 0.5 instead of the documented 0.80.
   `config.py` defaults now equal the fitted values; keep them in sync.

6. **macOS Accelerate BLAS emits spurious FP warnings** on large matmuls.
   Inputs were audited and are clean. Suppressed with `np.errstate`; ignore.

7. **`site.api.espn.com` intermittently 403s.**
   `sports.core.api.espn.com` is reliable. Always send a User-Agent.

---

## 4. How it works (one paragraph)

Ridge-regularized least squares over every game gives each team a rating in
points, opponent-adjusted automatically because teams appear on both sides of
many games. Quarterbacks are fit **jointly** with teams
(`margin = (team_h + qb_h) − (team_a + qb_a) + HFA`), because ~15% of
team-games have a non-primary starter and that swing is worth ~6 points —
larger than home field. Home field is fitted at **~2.1 pts**, not 3 (the
fanless 2020 season came in at 0.17). Games are recency-weighted (decay 0.98/wk,
offseason = 70 wk-equivalents). Early season blends toward ratings backed out
of posted spreads (Week 1 ≈ 80% market, decaying as games accumulate), because
the model has seen no current-season football while the line has priced every
offseason move. Projected margin converts to probabilities by **exponential
tilting of the empirical margin distribution** — which preserves the real spikes
at 3 and 7. Market odds are **de-vigged** before any edge is computed. Staking
is half-Kelly, 2.5% per bet, 10% per week.

Full detail in `README.md`. Weekly procedure in `OPERATING.md`.

---

## 5. Commands

```bash
.venv/bin/python -W ignore scripts/run_week.py                 # next unplayed week
.venv/bin/python -W ignore scripts/run_week.py --week 5
.venv/bin/python -W ignore scripts/run_week.py --qb LV="Name"  # override a starter
.venv/bin/python -W ignore -m pytest tests/ -q                 # 24 invariant tests
.venv/bin/python -W ignore scripts/run_backtest.py             # revalidate + refreeze
.venv/bin/python -W ignore scripts/measure_situational.py      # re-test situational factors
.venv/bin/python -W ignore scripts/tune.py                     # grid search (~7 min)
```

Fresh machine: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.

---

## 6. Data facts (verified, do not re-investigate)

- **`spread_line` is the CLOSING line**, and it is DraftKings. Verified three
  ways: nflverse's pbp dictionary says so; against Sportsbook Reviews Online
  open/close archives (3,766 games, 2007-2021) it sits 0.27 pts from the close
  vs 1.33 from the open; and it matches ESPN/DraftKings 16/16 exactly on a live
  slate. For *unplayed* games it is a live snapshot that freezes at kickoff.
- **Sign conventions** (verified empirically): `result = home − away`;
  `spread_line` positive = home favored; home covers when
  `result > spread_line`. Home cover rate 49.05%, push rate 2.68%, residual SD
  vs closing line **13.20**.
- **Real spread juice runs +100 to −133**, not a flat −110 (median −107). Using
  actual odds moved hold-out ROI from −7.26% to −6.54% — the earlier numbers
  were slightly *pessimistic*.
- **Key numbers**: a point at a line of 2 is worth 2.0% win probability; the
  point crossing **3 is worth 8.1%**. Never use a single average conversion rate.
- **Odds sources**: ESPN exposes only DraftKings (no line shopping). Action
  Network is keyless and gives 6 real books + consensus + opening line. The
  Odds API needs a key (500 credits/mo free; spreads+h2h on `us` = 2 credits
  per call). ESPN deletes odds once a game is final — the feed is live-only and
  cannot be backtested.
- **Line shopping needs the outlier guard.** On a live Week 1 slate one book's
  feed was sign-inverted and unguarded max/min shopping reported a **phantom
  3.0-point better line**, which manufactures bets at a 1.5pt threshold. Use
  `consensus_line()` as the market number; `best_lines(max_dev=1.0)` by default.

---

## 7. Decisions Jameson has already made

- Markets: **spread + moneyline only**. Totals deliberately excluded (a margin
  model gives spread and ML natively; totals would need a separate scoring
  model). Do not add them unbidden.
- Engine: points-based power ratings, not the 0-100 scorecard style of his MLB
  model.
- Data: fully automated pull, no paid subscriptions.
- Validation: backtest first, hold-out required.
- Bankroll $1,000, half-Kelly, 2.5% per-bet cap, 10% weekly cap.
- **The plan is to paper-trade first**: log leans and the number available,
  accumulate CLV over ~40-50 picks (~6 weeks), then decide whether to bet.
  See the decision gate in `OPERATING.md`.

He also has a separate MLB model (`MLB-Betting-model-`) whose de-vig bug
(comparing against raw implied odds) is still unfixed — he was offered a fix
and has not taken it up.

---

## 8. Working agreement

- **Lead with hold-out numbers.** Never report tuning-season results as
  results. Real money rides on this; a false positive that sends him betting is
  far worse than a missed improvement.
- **Try to break good-looking results before reporting them.** Two near-misses
  already: a 53.2% tuning-season ROI and a leaked 56.5% ATS.
- **Say plainly when something doesn't work.** He responds well to it and the
  whole project depends on it.
- Answer the question asked; he asks direct practical questions and wants
  direct answers.

---

## 9. Known gaps / open items

- `odds.py` is written and validated but **not yet wired into `run_week.py`** —
  the weekly run still uses nflverse's stored `spread_line` rather than live
  multi-book numbers. This is the most useful next piece of work.
- No test covers `excel.py`, `backtest.py`, or `data.py` directly.
- CLV for spreads converts points→probability via a per-line lookup written to
  the workbook's `Lists` sheet; moneyline CLV uses prices. Both work, but no
  real bets have been logged yet to validate end to end.
- Depth-chart integration for projected starters is not built; Week 1 QBs are
  carried forward from 2025 and will be wrong for any offseason move.
- `HFA_TEAM_DELTAS` and several config knobs are declared but unused.
