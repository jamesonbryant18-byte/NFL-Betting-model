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

**Jameson turned `ADVISORY_MODE` off on 2026-09-14** (decision mode: BETs with
half-Kelly stakes). That was his call, made after seeing the numbers above; do
not flip it back on your own initiative either. Week 1 review: 11-5 straight
up once Monday night was graded (inside the noise band), leans 3-6, one input error (ATL starter changed
after the Wednesday run). No ratings parameters were changed on one week.

---

## 1b. Self-improvement — read IMPROVEMENT.md

Jameson asked for continuous week-to-week self-improvement (2026-09-22). It was
built (`selftune.py`), measured, and **rejected**: hold-out MAE goes 10.079
frozen -> 11.065 at full strength, degrading monotonically, and value picks get
worse at every setting. `alpha=0.1` is a no-op (paired t=-0.08, p=0.93). It
fails on the tuning seasons too.

The mechanism, which is the useful part: the weekly refit ALREADY moves a team
in the direction the self-tuner wants, 69% of the time (r=+0.45, n=2,688
team-weeks). But the ridge moves the rating ~0.05 pts per 1 pt of residual,
because most of one game's surprise is noise. The self-tuner adds the raw
residual on top, unshrunk. It is not adaptation vs no adaptation — it is the
same adaptation applied twice, the second time without the shrinkage.

`recency_decay` is the legitimate knob for "react more to recent form" and it
is already at its measured optimum (0.98; 0.90/0.95/0.99/1.00 are all worse).

**The gate is evidence, not the calendar.** A change ships any day of the
season if it improves out-of-sample accuracy. What never clears the bar is a
16-game weekly scoreboard. Process defects (wrong QB, stale line, missing game)
are fixed immediately and need no gate.

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

4. **QB starters, and the fillna trap.** This used to read "nflverse only
   populates QB names for PLAYED games." **That is no longer true** — as of
   2026 nflverse pre-fills the starters for the upcoming week, and it fills
   all 32 correctly.

   That change silently broke the override. The slate took its starters via
   `fillna`, so once the columns arrived populated there was nothing to fill:
   every resolved starter *and every explicit `--qb` override* was discarded.
   Verified against the committed code — `--qb KC="Chris Oladokun"` moved the
   KC line by exactly 0.0 points. It now **assigns** rather than fills, and
   `test_qb_override_actually_reaches_the_projection` fails if the path ever
   goes dead again.

   Starters now resolve through `depth.resolve_starters()`, four layers deep:
   `--qb` override → published depth chart (nflverse's daily ESPN pull,
   timestamped) → the game file's own value → `ratings.projected_starters()`
   carry-forward. Where the depth chart and the game file disagree, the run
   prints a WARNING naming both rather than picking silently.

   Names resolve **by player id, never by string**. The depth chart says
   "Michael Penix Jr." where the game file says "Michael Penix"; a string
   match returns replacement level without complaining. `--starters` prints
   all 32 with their source.

   The carry-forward remains the last resort and is the only layer blind to
   the offseason: checked against the live 2026 Week 1 depth charts it was
   wrong for 7 of 32 teams (ATL, CLE, LV, MIA, MIN, NO, NYJ). It was never
   consulted for that slate, because the game file was already right.

5. **Only grid-searched keys may be frozen** to `data/fitted_params.json`.
   Freezing the whole dataclass once pinned hand-set judgment values —
   `market_prior_weight` ran at a stale 0.5 instead of the documented 0.80.
   `config.py` defaults now equal the fitted values; keep them in sync.

6. **macOS Accelerate BLAS emits spurious FP warnings** on large matmuls.
   Inputs were audited and are clean. Suppressed with `np.errstate`; ignore.

7. **ESPN's hosts want OPPOSITE User-Agent behaviour.** This was recorded
   backwards. Measured 2026-09-09, repeatedly:

   | host | with a browser UA | with no UA |
   |---|---|---|
   | `site.api.espn.com` | **403** | 200 |
   | `site.web.api.espn.com` | **200** | 200 |
   | `sports.core.api.espn.com` | 200 | 200 |

   So "always send a User-Agent" is wrong for `site.api` specifically.
   `espn._get_json` tries `site.web.api` with a UA and falls back to
   `site.api` without one. `cdn.espn.com/core/...?xhr=1` returns HTTP 202
   with an empty body and is useless.

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

The **workbook** (`excel.py`) is the human interface: Picks, Weekly Slate,
Model Picks %, Game Detail (a dropdown matchup picker driven by INDEX/MATCH
into a hidden `Model Data` sheet), Team Stats, Power Ratings, Bet Tracker,
Bet Log, Rosters, Injuries, Reference. `model.components()` exposes the terms
behind a projection for display and feeds nothing back. Rosters and injuries
come from `espn.py`/`teamstats.py`; graded history from `history.py`; the
tracker's merge-across-runs from `betlog.py`.

---

## 5. Commands

```bash
.venv/bin/python -W ignore scripts/run_week.py                 # next unplayed week
.venv/bin/python -W ignore scripts/run_week.py --week 5
.venv/bin/python -W ignore scripts/run_week.py --qb LV="Name"  # override a starter
.venv/bin/python -W ignore scripts/run_week.py --starters       # print all 32 starters + source
.venv/bin/python -W ignore scripts/run_week.py --no-depth-chart # ignore depth charts
.venv/bin/python -W ignore scripts/run_week.py --archive-anyway # archive a week that already kicked off
.venv/bin/python -W ignore -m pytest tests/ -q                 # 24 invariant tests
.venv/bin/python -W ignore scripts/run_backtest.py             # revalidate + refreeze
.venv/bin/python -W ignore scripts/measure_situational.py      # re-test situational factors
.venv/bin/python -W ignore scripts/grade.py --save             # grade every prediction this season
.venv/bin/python -W ignore scripts/grade.py --diagnose --scope all   # systematic error hunt (FDR-corrected)
.venv/bin/python -W ignore scripts/selftune_sweep.py           # does weekly self-tuning help? (no)
.venv/bin/python -W ignore scripts/run_week.py --no-live-odds  # skip the multi-book pull
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

- ~~`odds.py` not wired in~~ **DONE 2026-09-22.** `shop.attach_live_odds()`
  now runs by default in `run_week.py`: six books, the *median* becomes the
  market number, best price per side rides along, `--no-live-odds` opts out,
  and a dead feed degrades to the stored line instead of killing the week.
  On the first live run the stored nflverse line was already stale on 3 of 16
  games (PHI@CHI by 1.5 pts, which added a bet). **The de-vig pair must stay
  matched to one book** — mixing the best price from each side shrinks the
  overround (4.30% -> 2.34% on a real Week 3 pair) and inflates every edge.
  Guarded by `test_devig_pair_is_never_mixed_across_books`.
- A quarterback below `min_qb_starts` silently becomes replacement level
  (-1.87 pts). `run_week.py` now WARNS when a slate starter is unrated —
  2026 Week 3 CHI/Tyson Bagent (5 career starts) was driving a bet off that
  assumption. Depth-chart names also differ from game-file names
  ("Michael Penix Jr." vs "Michael Penix"), so anything passing a name to
  `qb_value()` by string can hit replacement without complaining.
- No test covers `excel.py` or `backtest.py` directly. `teamstats.py`,
  `betlog.py` and `history.py` each have one (117+ tests total).
- CLV for spreads converts points→probability via a per-line lookup written to
  the workbook's `Lists` sheet; moneyline CLV uses prices. `betlog.clv_for_row`
  reproduces the same arithmetic in Python and the two were checked to agree.
  Still no real settled bet has exercised it end to end.
- The **injury-burden term ships at zero** and the roster feed is reporting
  only. See `scripts/measure_injuries.py`: pooled it looks like the best factor
  in the repo, but it fails season-clustering, loses money in six of twelve
  seasons, and stale absences carry more signal than fresh ones — backwards for
  an injury story, and a sign it proxies team quality. Re-test it
  prospectively against CLV rather than re-running the pooled regression.
- `HFA_TEAM_DELTAS` and several config knobs are declared but unused.
