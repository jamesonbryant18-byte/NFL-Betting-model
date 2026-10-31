# NFL Betting Model: the reference

Everything researched, graded and tested on this model, in one place.
Current as of **Saturday 2026-10-31**. Written for Jameson ("you").

- **Every test, one row each:** [`test_database.csv`](test_database.csv) in this
  folder. It opens in Excel; filter the `verdict` column. The same rows are grouped
  by topic in section 5.
- **The raw material** is in this folder too: the research report and its sources,
  both graders' full reports, and the scripts and outputs behind every number (map
  in section 9).
- **Before testing a new idea, look it up here.** Most ideas have already been
  tested, and the usual answer is "the betting line already knows it."

## Contents

1. [The short version](#1-the-short-version)
2. [The model today](#2-the-model-today)
3. [The research](#3-the-research)
4. [The grading](#4-the-grading)
5. [Every test, by topic](#5-every-test-by-topic)
6. [Live 2026 results](#6-live-2026-results)
7. [Decisions you have made](#7-decisions-you-have-made)
8. [Open questions](#8-open-questions)
9. [Where everything is](#9-where-everything-is)

---

## 1. The short version

- **No proven edge against the closing line.** That was the finding of the first
  build in August, and nothing since has changed it.
- **Straight-up picks are about as good as always taking the favorite, not better.**
  On 2021-25 (seasons nothing was fit on) the model picked 66.1% of winners and the
  closing favorite 66.5%. The research says the same about the best public models.
  nfelo and ESPN FPI don't beat the closing favorite over many seasons either.
- **The bets are about break-even before the vig and lose a little after it.** The
  weekly card replayed on 2021-25 returned −0.3% a bet. Anything between about −7%
  and +7% is noise at that sample size.
- **Live through Week 7, the card went 25-19-1, +$36 at $5.** But the prices it got
  were worth 2.8% a bet less than FanDuel's closing prices. The record is running
  ahead of the prices: luck, not edge.
- **What helps, measured:**
  - the market prior (starting from the betting market's view of each team);
  - the "far from the line" pull (when the model is 3+ points off the line, move 1.5
    toward it);
  - the non-QB injuries factor.
- **What didn't help:** almost everything else tested. That covers situational spots,
  weather, EPA efficiency, self-tuning, referees, schedule spots, coaching changes,
  opening lines, line timing and 480 subsets of games.
- **Grades:** 40/100 in round 1 and 55/100 in round 2 (the two rubrics differ
  slightly). The round-2 fixes have not been graded yet.

## 2. The model today

**How it works.**
1. Each week it rates every team and starting quarterback in points. This is a ridge
   regression on every game, with recent games weighted more. Quarterbacks are fit
   together with their teams.
2. Early in the season the ratings lean on the market prior: ratings backed out of
   this season's spreads.
3. It adds home field and two game factors:
   - non-QB injuries, 0.637 pt per starter out;
   - rest days, 0.048 pt a day.
4. It applies one trend fix: when the model is 3+ points from the line, it moves 1.5
   toward it.
5. Margins become win and cover chances from the real spread of NFL final margins, so
   3 and 7 keep their extra weight.
6. A win-% correction is applied last, because longshots were overrated.

**Switched off:**
- the EPA/play factor (dropped 10-29);
- the weekly self-tune (off 10-29).

Advisory mode has been off since 09-14 (your call).

**Bet rules**

| rule | value | set by |
|---|---|---|
| Book | FanDuel only | you (locked) |
| Markets | spreads and moneylines | you (locked) |
| Stake | $5 flat | you (locked) |
| Bets a week | 4 to 7, ranked by the model's chance the bet wins; topped up with labeled filler if fewer than 4 qualify | you (locked) |
| Spread bet | model 1.5+ points from FanDuel's line | model |
| Moneyline bet | model's win % 3+ points above FanDuel's de-vigged % | model |
| Moneyline limits | favorites no shorter than −350; underdogs no longer than +250 | −350 model; +250 you |
| Whole numbers | no spread bets at 3, 7 or any whole number; that game's moneyline is still considered | you (2026-10-31) |
| Both qualify | spread over moneyline | model |
| Still a bet at | each bet's worst half-point line or price that still qualifies; worse than that, skip it | expert review round 2 |

---

## 3. The research

Done once, on 2026-10-27, by a deep-research run.
- 5 search angles and 21 sources.
- 101 claims pulled out; 7 confirmed by a 3-vote check, 0 refuted.
- 18 left unverified: the checks stopped when the account hit its spend limit.

The full report is `research/deep-research-report.md`. The grader's summary of it is
`expert-brief.md`. Reuse both. Only redo the research if the model changes in kind
(a new kind of model, new markets, new data).

### What it found

Only the straight-up and margin-error benchmarks (nfelo, the Prediction Tracker)
passed the research's 3-vote check. The rest comes from the sources as summarized
in `expert-brief.md`, several of them from the research's unverified list: strong
leads, not checked facts.

**Straight-up picks: the closing favorite is the bar, and almost nobody clears it.**
- **The closing favorite wins about 66-67% of NFL games:**
  - 66.69% over 4,737 games, 2009 to 2026 Week 7 (nfelo's data);
  - 65.8% in 1994-2000, the most accurate method in every one of those seasons
    (Boulier & Stekler);
  - about 65.9% in 2007-20 (PFF).
- **nfelo, one of the best public models:** 66.50% against the favorite's 66.69%.
  - It beat the favorite in only 8 of 18 seasons, by an average of −0.19 points.
  - Its average margin error (10.089) is about the same as the closing line's (10.095).
- **Prediction Tracker 2025:**
  - The line picked 66.5% of winners, 3rd of 52 systems.
  - The average computer system only tied it. ESPN FPI went 63.4%, Massey and Sagarin
    62.7%.
  - Over 2023-25 the best computer system beat the line by one game out of 855.
  - The top system changes every year.
- **2026 through Week 7 (107 games):**
  - The line went 68-38 (64.2%), and no system did better.
  - The average system went 60.4% and ESPN FPI 57.5%.
  - Your model's 64-42 sits in the middle of the public systems.
- **Margin error:** the line was the most accurate of all 52 systems in 2025, and is
  again so far in 2026. One system beat it for one season (Donchess, 2024), not over
  three.

**The market is more accurate than models, and professionals blend toward it.**
- **On Brier score (win-% accuracy), the market spread beat every model** (2009-19).
  - A de-vigged 7-book moneyline scored 0.2103 in 2025, against ESPN's 0.2216.
  - A coin flip scores 0.25.
- **Professionals blend:**
  - Massey-Peabody uses about 45% model and 55% market;
  - nfelo does best at about 65% market;
  - Benter fits a second step on top of model and market.
  - The test: if the best blend gives the market 100%, the model adds nothing.
- **Picks against the market win less often than the model says.**
  - Benter saw this in all 10 probability bins.
  - At Data Golf, betting every positive edge lost money (−0.9% against +5.2%
    expected).
  - Their returns rose with the size of the edge but stayed far below what the model
    expected.

**Judging a small sample.**
- **Win-loss records need hundreds to thousands of bets.**
  - A 10% edge at even money takes about 540 bets to show at 99% confidence.
  - 36% of random 100-bet samples at −3.7% expected still finish ahead.
- **Closing line value (CLV) is the fast signal,** because it is about ten times less
  noisy per bet than profit. It can show skill in about 50 bets.
  - The average beat must be bigger than the book's cut.
  - A tipster who beat the close on 17 of 23 picks by about 2% projects to break even.
- **Re-testing every week inflates false alarms.**
  - A standard test passed its 5% error rate after about 100 looks.
  - Separating FiveThirtyEight from Vegas took about 10,000 games.

**What the market already prices.**
- **Injuries, player ratings and news:** the market is "much better" than models
  (Rufus Peabody). Model edges come from process instead: opponent adjustment,
  garbage time, weather and how much to weight recent games.
- **Byes:** no detectable effect since the 2011 labor deal (+0.31 points, interval
  −1.01 to +1.64), while spreads price a bye at about +0.97.
- **Backup quarterbacks:** weak evidence that the market overreacts when a good
  starter is out.
- **Key numbers:** a gap that crosses 3 is worth more than a bigger gap that crosses
  nothing. About 2 points is a rough NFL threshold.
- **Line moves:** lines overreact from open to close (about a third of a move
  reverses), but no strategy built on that beats the vig.
- **Moneylines:** in 2007-16 they showed a reverse favorite-longshot bias, which
  changed from season to season.

**Timing.**
- The close is sharper than the opener: margin error 10.10 against 10.21.
- Betting near kickoff at one book means beating the sharpest number there is, the
  hardest kind of edge.

### What good numbers look like (the grader's yardsticks)

| measure | benchmark | good | exceptional |
|---|---|---|---|
| Straight-up % | closing favorite, same games (~66.5-67% long run) | within 0.5 pt of the favorite | ahead of the favorite |
| Margin error | closing spread (~9.8-10.1 pts) | within 0.15 pt of the line | at or below the line |
| Brier (win %) | de-vigged closing moneyline (~0.205-0.215) | within 0.002 | at or below the market |
| Calibration slope | 1.0 | 0.9-1.1 | 0.95-1.05 on 1,000+ games |
| Information beyond the line | 0 = none | positive, t ≥ 1 | positive, t ≥ 2 |
| Best model/market blend | 100% market = no signal | 10-30% model | 35-45% model (pro level) |
| Spreads against the spread | 52.4% at −110 | above break-even on the hold-out | above, with a range that excludes it |
| CLV | 0 | positive, bigger than the book's cut | positive, t ≥ 2 over 50+ bets |

Where the model stands (2021-25):
- straight up: 0.4 pt behind the favorite, which is "good";
- margin error: 0.11 behind the line, "good";
- Brier: 0.0043 behind the market, short of "good";
- calibration slope 0.96 on 1,420 games, in the top band, though the 80-85% bucket
  runs 2.3 SE short;
- information beyond the line: +0.34 (t 1.86), "good";
- CLV: about zero.

### Leads the research did not verify (check before relying on them)

- **Line timing:** the midweek line is nearly as good as the close, and the opener is
  clearly worse (Prediction Tracker 2023-25).
- **Momentum, value and size betting strategies** have negative returns after the
  vig, across four sports (Moskowitz).
- **Data Golf (golf):** a profit needed an edge threshold of 5%+. Even at 1,000 bets,
  luck is a big share of the result.
- **NFL moneylines 2007-16** were inefficient at open and close, but in a way that
  changed season to season (Journal of Economic Insight; abstract only).
- **Opening and closing lines predicted equally well** in 2002-11, and about 80% of
  lines moved 1 point or less (arXiv 1211.4000).

### Sources

1. nfelo model performance (2009-2026): https://nfeloapp.com/games/nfl-model-performance/
2. The Prediction Tracker, NFL results: https://www.thepredictiontracker.com/nflresults.php
3. Boulier & Stekler, Predicting the outcomes of NFL games (2003): https://brendanwhit.github.io/ds1-final-project/lit-review/boulier2003.pdf
4. PFF, why betting early is critical (2021): https://www.pff.com/news/bet-why-betting-early-critical-beating-nfl-markets
5. nfelo, market regression: https://www.nfeloapp.com/analysis/using-market-regression-to-improve-prediction-accuracy-in-the-nfl/
6. J. Tin, NFL 2025 forecasts (books vs ESPN vs Polymarket): https://johanntin.github.io/nfl2025-analysis
7. RotoWire interview with Rufus Peabody (2018): https://www.rotowire.com/football/article.php?id=40172
8. Benter, computer-based horse race handicapping (1994): https://www.gwern.net/doc/statistics/decision/1994-benter.pdf
9. Data Golf, how sharp are bookmakers: https://datagolf.com/how-sharp-are-bookmakers
10. Football-Data, luck vs skill: https://www.football-data.co.uk/blog/luck_skill_sports_betting.php
11. Buchdahl on CLV: https://www.pinnacleoddsdropper.com/blog/closing-line-value--clv-demystified-by-expert-joseph-buchdahl
12. Football-Data, closing odds: https://www.football-data.co.uk/blog/closing_odds.php
13. K. Whelan, CLV and NBA moneylines: https://www.karlwhelan.com/?p=2595
14. Choe & Ramdas, comparing sequential forecasters: https://arxiv.org/abs/2110.00115
15. Bye-week effect 2002-2023: https://arxiv.org/abs/2408.10867
16. nfelo, team and scheme QBs: https://www.nfeloapp.com/analysis/team-and-scheme-nfl-qbs/
17. Moskowitz, asset pricing and sports betting (NBER): https://conference.nber.org/conf_papers/f92072/f92072.pdf
18. Moskowitz, Journal of Finance (2021): https://econpapers.repec.org/RePEc:bla:jfinan:v:76:y:2021:i:6:p:3153-3209
19. NFL money line efficiency 2007-2016: https://journalofeconomicinsight.com/index.php/joei/article/view/1335
20. Point spreads and straight-up winners 2002-11: https://arxiv.org/abs/1211.4000

---

## 4. The grading

**How it works** (the expert-review loop):
1. Research the field.
2. Write a 100-point rubric and lock it.
3. A fresh grader that has never seen earlier rounds grades the project as it stands.
   It runs the code and recomputes the numbers, in a copy of the repo without this
   folder, so no earlier score can steer it.
4. A numbered fix list goes to you, and you pick what to apply.
5. The changes are logged, then the next round starts.

The README in this folder explains how to grade again without redoing the research.

### The rubric (v2, locked 2026-10-29)

| # | criterion | points |
|---|---|---|
| **A** | **Model picks** | **45** |
| 1 | Straight-up accuracy vs simply taking the favorite | 15 |
| 2 | Margin and win-% accuracy vs the market | 12 |
| 3 | Model design: does every live piece earn its place? | 10 |
| 4 | Validation rigor and leakage | 8 |
| **B** | **Bets** | **27** |
| 5 | Live bets: good bets or lucky ones? | 14 |
| 6 | Bet selection logic | 10 |
| 7 | Locked choices work as designed (bug check only) | 3 |
| **C** | **Weekly inputs and process** | **18** |
| 8 | Input correctness at the time you bet | 10 |
| 9 | Process reliability and safeguards | 8 |
| **D** | **Excel workbook** | **10** |
| 10 | Workbook correct, carried, usable and honest | 10 |

v1 to v2 (your call after round 1):
- 5c grades value at the price taken as well as line movement;
- the canonical replay is the required evidence;
- the 2 points for your own bet choices (old 6c) moved into 5c;
- the tracker fills you asked for don't count as carry errors.

v1 is kept as `round-1/rubric-v1.md`.

### Scores by criterion

| criterion | max (v2) | round 1 (v1) | round 2 (v2) |
|---|---|---|---|
| 1a straight up vs the favorite, hold-out | 7 | 1 | 5 |
| 1b the straight-up pick rule | 4 | 0 | 2 |
| 1c live straight-up tracking | 4 | 2 | 2 |
| 2a margin error vs the line | 4 | 3 | 3 |
| 2b win % vs the market | 4 | 2 | 2 |
| 2c calibration | 4 | 0 | 0 |
| 3a every piece measured | 5 | 0 | 3 |
| 3b information beyond the line | 3 | 2 | 2 |
| 3c structural soundness | 2 | 0 | 1 |
| 4a leak-free, honest reporting | 4 | 2 | 2 |
| 4b reproducibility | 4 | 2 | 4 |
| 5a bet logging | 3 | 1 | 1 |
| 5b luck vs skill accounting | 5 | 1 | 3 |
| 5c CLV and value at the price taken | 6 (v1: 4) | 1 | 0 |
| 6a hold-out profit of the bet rules | 6 | 2 | 4 |
| 6b bigger edges, better bets? | 4 | 2 | 2 |
| 6c your own bet choices (v1 only) | (v1: 2) | 1 | |
| 7 locked choices work (bug check) | 3 | 3 | 2 |
| 8a quarterback starters | 5 | 1 | 1 |
| 8b injuries and late news | 3 | 1 | 1 |
| 8c prices match what you can bet | 2 | 1 | 1 |
| 9a weekly procedure, right files | 4 | 2 | 1 |
| 9b tests and guards | 4 | 2 | 4 |
| 10a workbook numbers correct | 4 | 4 | 4 |
| 10b your tracker carried, charts updated | 3 | 3 | 3 |
| 10c usable and honest | 3 | 1 | 2 |
| **total** | **100** | **40** | **55** |

### Round 1: graded 2026-10-28, 40/100

**What the grader found**
- **Nothing measured the model as it actually runs.** Each lab rebuilt its own
  version, and the replay's market prior saw different lines than the live run
  (0.34 pt apart).
- **Picks lost to the favorite:** 65.3% against 66.5%. When the model picked against
  the favorite it won 43.7% (59 of 135).
- **Probabilities were overconfident:** picks called 67% won 59%, and picks called 82%
  won 73%.
- **Two live pieces hurt:**
  - the EPA/play factor (Brier t +2.5);
  - the self-tune on top of it (straight up −0.85 pt, because EPA was counted twice).
- **The bets were break-even at best.** The replayed card returned +0.0% (SE 3.4%), and
  value at the price taken was −2.8% a bet live.
- **Inputs and process:**
  - three wrong QB starters (none changed a pick or a bet);
  - game-day runs that never reached your files;
  - no favorite baseline anywhere;
  - CLV computed with method errors;
  - "Win Chance" showed the game's win % on spread bets;
  - two tests failing.

**What the grader called strong:** clean data with no leaks, honest documentation,
correct workbook cells, your tracker carried exactly, and sound pricing math.

**Fixes**

You approved:
- one canonical replay that matches live;
- EPA/play dropped and the self-tune off;
- the win-% slope refit on the model as it runs;
- the honest weekly scorecard (vs the favorite, good or lucky);
- the 2 failing tests fixed;
- the caches rebuilt;
- workbook honesty fixes;
- the FanDuel-label bug in a locked part;
- your tracker's blank closing cells filled from FanDuel's close;
- rubric v2.

You declined:
- picking straight up from the favorite or a blend ("basic and boring");
- game-day QB guardrails (your own check).

Tested and not switched: ranking the card on a model/market blend.

Details are in `round-1/fixes.md` and `round-1/changes.md`.

### Round 2: graded 2026-10-29, 55/100

**What the grader found**
- **The replay is now faithful and reproducible,** and the reporting is honest.
- **The last leak:** the replay's win-% table had seen 2021-25's own scores.
- **`grade.py`** graded rematches against the earlier game and counted ties as losses.
- **Two game-day cards never reached the record:**
  - Week 5: the workbook was open in Excel;
  - Week 7: the run happened in a scratch copy only.
- **The bets still matched FanDuel's close and paid the vig:** value at the price taken
  was −2.77% a bet (t −3.56).
- **Bigger edges did not win more.** The highest-chance third of bets was the worst.
- **Calibration:** picks called 80-85% won 76% (n 104).

**What the grader called strong:**
- the replay matches the live path to 0.0;
- the edge math is right;
- the workbook is correct and your tracker is respected;
- the guards hold (236 tests);
- pieces were cut on evidence.

**Fixes: you approved all ten.**
1. Season scorecard fixed.
2. Bet slices in the weekly review.
3. Stale text fixed.
4. Leak closed, and the choices that looked at 2021-25 are now listed on the Reference
   sheet.
5. A graded ledger of every model bet.
6. "Still a bet at" on every bet.
7. Full ablation: the market prior helps; the QB fit and home field are small; nothing
   hurts.
8. Two design questions tested. Neither held, so neither shipped: QB taken out of the
   prior, and a smooth trend pull.
9. Game-day runs always reach the record, never write over a workbook Excel has open,
   print card changes and flag stale `--qb` overrides.
10. Walk-forward win % in the replay.

Details are in `round-2/fixes.md`, `round-2/changes.md` and `round-2/fix-outputs/`.

### Where the grading stands now

- **Round 3 has not been run.** Round 2's fix list estimated about 66-70 if every fix
  landed; only a fresh grader can confirm that.
- **Points that won't come back without a real edge:**
  - 5c, 6a and 6b: the bets pay the vig;
  - 1b, 2a and 2b: the line is more accurate than the model.
- **Points that won't come back at all:** the process misses of Weeks 1, 5 and 7
  already happened.
- **Rubric gaps you did not take up** (adding them would make a v3 that can't be
  compared with v2):
  - calibration buckets should allow for sampling error;
  - 9a needs a level for three or more failures.

---

## 5. Every test, by topic

Verdicts:
- SHIPPED / KEPT: live in the model.
- REJECTED / NOT SHIPPED: tested and turned down.
- WATCH: tracked, not applied.
- FINDING: a measurement, not a change.
- FIXED: a bug or process fix.
- YOUR RULE: your own hand-set rule, so it ships whatever the test says.

"2013-20" are the fitting seasons and "2021-25" the hold-out. A t of 2 or more is
roughly the bar for "real".

### Model structure (the ratings engine)

| # | date | test | result | verdict | details |
|---|---|---|---|---|---|
| 1 | 2026-08 | EPA-blended target (rate teams on a mix of score margin and EPA margin) | Error gets worse every step as EPA weight rises: 10.19, 10.23, 10.29, 10.35 | **REJECTED** | README 'What was tested'; CLAUDE.md s2 |
| 2 | 2026-08 | Separate offense and defense ratings | 10.1530 vs 10.1544 (t -0.08). In a margin model the two columns are the same thing | **REJECTED** | README |
| 3 | 2026-08 | Damp blowouts (cap margin of victory) | +0.023 pts (t -1.83); premise backwards (model is under-confident, slope 1.087) | **REJECTED** | README |
| 4 | 2026-08 | How fast old games fade (recency decay) | 0.98 a week is best; every other value worse | **SHIPPED (0.98)** | CLAUDE.md s1b |
| 5 | 2026-08 | Home field size | About 2.1 pts long run (not 3); 2020 without fans 0.17; about 1.3 in 2026 | **FITTED (no hand value)** | CLAUDE.md s4 |
| 6 | 2026-08 | Rate quarterbacks jointly with teams | About 15% of team-games have a backup, a ~6-pt swing. Ablation: error -0.029 (t -1.0), helps a little | **KEPT** | scripts/ablation.py; IMPROVEMENT.md |
| 7 | 2026-08 | Market prior (start from ratings backed out of this season's spreads) | The most useful piece: error -0.078 (t -3.1), Brier t -2.4 | **KEPT** | scripts/ablation.py |
| 8 | 2026-10-31 | Home field term (ablation) | Error -0.032 (t -0.8), Brier neutral | **KEPT** | scripts/ablation.py |
| 9 | 2026-09-22 | Stretch or shrink the model's projections (it looked under-confident) | Every multiplier made 2021-25 worse (1.138: +0.019 error). A 'significant' in-sample bias that did not repeat | **REJECTED** | IMPROVEMENT.md |
| 13 | 2026-10-31 | QB counted twice? Take QB values out of the lines behind the market prior | Error 9.855 vs 9.876 (t -1.4) but straight up 65.49% vs 66.06% (t -2.0), worse in 2013-20 too | **NOT SHIPPED** | scripts/design_checks.py; round-2/fix-outputs |
| 14 | 2026-10-31 | Smooth trend pull (same 1.5 cap) instead of the 3-pt cliff | Error 9.833 vs 9.876 (t -2.4), Brier t -2.1, but SU 66.27% vs 66.06% (t 0.4), 563 bets vs 653, card -1.8% vs -0.3%; trend checker then switched on a fix it had rejected. Uncapped it goes all the way to the line | **NOT SHIPPED** | scripts/design_checks.py; round-2/fix-outputs |

### Model vs the market

| # | date | test | result | verdict | details |
|---|---|---|---|---|---|
| 10 | 2026-08 | Blend the model into the closing line | 2021-25 got worse than the raw line; best weight is zero | **REJECTED** | README |
| 11 | 2026-08 | Fit directly to beat the line (target = result minus spread) | Best penalty goes to infinity even on 2013-20: the best move is to not disagree with the line | **REJECTED** | README |
| 12 | 2026-10-31 | Information beyond the line (regress result on line + model) | First build: -0.018 (t -0.1). Model as it runs now: +0.34 (t 1.86): a hint, not proven | **FINDING** | README; round-2 grade |

### Validation and leaks

| # | date | test | result | verdict | details |
|---|---|---|---|---|---|
| 15 | 2026-08-30 | Market prior leak (no as-of cutoff) | Leak fabricated 56.5% ATS at z > 2; with the cutoff 50.1%, -4.3% ROI | **FIXED + test** | README 'A leak worth documenting' |
| 16 | 2026-08 | Tuning seasons vs hold-out seasons | ATS at 1.5 pts: 53.2% (+1.6% ROI) on 2013-20 vs 48.6% (-7.3%) on 2021-25 bare, 50.1% (-4.3%) deployed: overfitting made visible | **FINDING** | README |
| 17 | 2026-10-29 | Replay = live (the market prior saw different lines live and in the replay) | Projections differed 0.34 pt; now one canonical replay (replay.py) used for every number | **FIXED** | round-1/changes.md |
| 18 | 2026-10-31 | Win % in the replay saw 2021-25's own scores | Now walk-forward: SU 65.99% -> 66.06%, card +0.7% -> -0.3%, 80-85% bucket a bit worse | **FIXED** | round-2/changes.md |
| 19 | 2026-10-29 | Lab caches built before the live data loader | 2021-25 base error 10.079 -> 10.026; trend gate re-checked, still holds | **FIXED** | CLAUDE.md s9 |

### Situational spots (does the market misprice them?)

| # | date | test | result | verdict | details |
|---|---|---|---|---|---|
| 20 | 2026-08 | Bye week, short week (rest) | Home off bye -0.27 (t -0.44), away off bye -0.94 (t -1.33), short week t -0.27 / -0.26 | **REJECTED (market prices it)** | README; scripts/measure_situational.py |
| 21 | 2026-08 | Weather: wind 15+ / 20+, cold under 32F | Wind t +0.24 / -0.44, cold t +1.33 | **REJECTED (market prices it)** | README |
| 22 | 2026-08 | Travel / time zones | East / west 2+ zones t -1.46 / +1.15 | **REJECTED (market prices it)** | README |
| 23 | 2026-08 | Divisional games; Week 17/18; favorites of 10+ | Divisional t -1.23; Week 17/18 t +1.35 / +1.45; big favorites t +1.48. None reaches /t/ = 2; market's mean miss -0.04 pts | **REJECTED (market prices it)** | README |
| 24 | 2026-08 | 480 subset hypotheses (spread size, home/away dog, weeks, primetime, dome, rest, season, side) | Zero survive; subsets picked on 2013-20 predict nothing later (r = -0.03) | **REJECTED** | README |

### Game factors

| # | date | test | result | verdict | details |
|---|---|---|---|---|---|
| 25 | 2026-09-28 | Factor lab batch 1: efficiency (EPA), matchups, weather, rest/travel, coaching/situation | No help: cross-validation picked the maximum penalty; error slightly worse | **REJECTED** | CLAUDE.md s0 (09-28) |
| 26 | 2026-09-28 | Non-QB injuries (starters out) | About 0.6 pt per starter out; 2021-25 error -0.09 (t 2.7), SU up in 4 of 5 seasons; vs the line not significant (t 1.1). Round-1 ablation: error t -2.6, card -3.5% without it | **SHIPPED (0.637 pt per starter)** | config.FACTORS; refit_factors.py |
| 27 | 2026-09-28 | Factor lab batch 2: letdown/lookahead, after OT, after London, 3rd road game, interim coach, last-3 form, team-specific home field, altitude, surface, referee crew, 2+ starters out at one unit, total-aware win % | All no help alone or on top of injuries (referee 'passed' by 0.0004 pts = nothing) | **REJECTED** | CLAUDE.md s0 (09-28) |
| 28 | 2026-09-28 | Live factor set from Week 4: injuries + EPA/play + rest | SU 65.6% -> 65.8%, error 9.966 -> 9.901, ATS 50.1% -> 52.1%, moneyline ROI -7.8% -> -1.8% | **SHIPPED Week 4 (EPA part later dropped)** | CLAUDE.md s0 |
| 29 | 2026-10-29 | EPA/play factor | Brier worse (t +2.0 to +2.5); card -2.4% with it vs -0.3% without; live t -1.7 on 47 games | **DROPPED** | IMPROVEMENT.md round 1 |
| 30 | 2026-10-29 | Rest-day factor | Effect about zero (0.048 pt a day) | **KEPT (harmless)** | config.FACTORS |
| 31 | 2026-08 | Injury burden, older pooled test | Looked like the best factor pooled, but failed season clustering, lost money in 6 of 12 seasons, stale absences beat fresh ones | **SUPERSEDED by the factor-lab version** | CLAUDE.md s9 |
| 32 | 2026-09-25 | Weather x team style (pass-heavy offense in rain/wind, your idea) | 2016-20 slope +13.1 (t +2.1), the OPPOSITE sign; 2021-25 -1.9 (t -0.3); applying it made bad-weather error worse (9.99 -> 10.29) | **REJECTED** | IMPROVEMENT.md; scripts/weather_style_test.py |
| 33 | 2026-09-25 | Skip value bets in bad weather | 53.6% vs 42.3%: does not repeat | **REJECTED** | IMPROVEMENT.md |
| 34 | 2026-09-25 | Cold (32F or less) value picks | 39.6% on 53 picks, small and after the fact | **WATCH** | IMPROVEMENT.md |

### Learning from results

| # | date | test | result | verdict | details |
|---|---|---|---|---|---|
| 35 | 2026-09-22 | Weekly self-correction from each team's score miss | Error 10.079 -> 11.065 at full strength, worse at every setting; alpha 0.1 is a no-op (t -0.08) | **REJECTED** | IMPROVEMENT.md; scripts/selftune_sweep.py |
| 36 | 2026-09-25 | Which signal could a weekly nudge learn from? 6 signals x 180 settings | Only EPA margin helps, and only with a 0.5-pt cap per game (27 of 27 settings, error -0.012); bets not improved | **SHIPPED 09-25 as the EPA self-tune** | IMPROVEMENT.md |
| 37 | 2026-09-25 | Score self-tune with a 1-pt cap and a 7-pt blowout clip | Error -0.004 (noise), ATS drifts down: safe, not helpful | **REPLACED by the EPA version** | IMPROVEMENT.md |
| 38 | 2026-10-29 | EPA self-tune on the model as it runs | With the EPA factor in: SU -0.85 (t -2.1), EPA counted twice. Without it: neutral | **TURNED OFF** | IMPROVEMENT.md round 1 |
| 39 | 2026-09-26 | Miss-trend checker: about 28 reasons the model keeps missing | One fix survives: model 3+ pts from the line -> pull 1.5 toward it (2021+ error 10.13 -> 10.02, t 6.0; ablation t -4.4). Big/mid favorites, home dogs, divisional dogs, night favorites, new QB: real but covered by it; late-season favorites pruned | **SHIPPED (one fix live)** | IMPROVEMENT.md; data/trends.json |
| 40 | 2026-09-26 | Trend watch list | Rest edge, inexperienced QB (-1.0 / -0.9), after a 21+ win, score-beat-EPA luck, favorites in wind (+0.1 / +2.7), favorites in rain/snow (+3.2 / +2.0), low totals; divisional dogs moved to watching 10-27 | **WATCH** | IMPROVEMENT.md; Miss Report sheet |
| 41 | 2026-09-26 | Adversarial audit of the trend checker (11 agents) | Fixes would have been applied twice from Week 4; set-level confirmation; calibration intercept; clipped coefficients; weather and venue errors | **ALL FIXED** | IMPROVEMENT.md |

### Win % and longshots

| # | date | test | result | verdict | details |
|---|---|---|---|---|---|
| 42 | 2026-09-26 | Longshots overrated (+151 and longer) | z 6.9 / 5.1; +401 dogs said 24%, won 12-13%. Symmetric win-% recalibration: 2021+ log loss 0.6297 -> 0.6248 | **SHIPPED** | IMPROVEMENT.md; trends.py |
| 43 | 2026-09-26 | No moneyline dogs longer than +250 (your rule) | Underdog share of bets 88% -> 68%; return -1.8% -> -3.6% (noise) | **YOUR RULE** | config THRESHOLDS.ml_max_underdog |
| 44 | 2026-10-29 | Win-% slope fit on the model as it runs | 1.483 -> 1.402 | **SHIPPED** | round-1/changes.md |
| 45 | 2026-10-31 | Calibration on 2021-25 | Slope 0.962 (1 = honest). Picks called 80-85% won 73.8% on 107 games (2.3 SE short) | **OPEN (re-fitting on 2021-25 would be fitting the test)** | round-2 grade; replay_deployed.py |

### Bet selection

| # | date | test | result | verdict | details |
|---|---|---|---|---|---|
| 46 | 2026-08 | Edge thresholds 1.5 pts (spread) and 3% (moneyline), original build | ATS 50.1%, -4.3% ROI (deployed); moneyline 38.8%, -9.5% | **FINDING (no edge)** | README |
| 47 | 2026-08 | Bet the opening line instead of the close | The whole open-to-close accuracy gap is 0.14 pts; the model trails the close by 0.39 | **REJECTED** | README |
| 48 | 2026-08 | ATS vs openers (looked like 55.3%, +5.4%) | False positive: tuning-window artifact; clean 2021 49.70%, -5.09% | **REJECTED** | README |
| 49 | 2026-08 | Real spread juice instead of a flat -110 | Juice runs +100 to -133 (median -107); ROI -7.26% -> -6.54%. The price you get matters more than the model | **SHIPPED** | README 'Line shopping' |
| 50 | 2026-10-07 | Weekly card: top 7 by chance to win vs all bets vs top 7 by edge | All qualifying 52.2% / -3.9%; top 7 by chance 55.4% / -0.7%; top 7 by edge 50.8% / -4.4% (later replays could not reproduce the 55.4% exactly) | **SHIPPED (top 7 by chance)** | CLAUDE.md s0 (10-07); tests/test_card.py |
| 51 | 2026-10-29 | Rank the card on a model/market blend | No weight beats the model alone on 2021-25 (w 1: +0.72%, 0.75: -2.88%, 0.5: -0.47%, 0.35: -2.06%, 0.25: +0.96%; SE ~4%) | **NOT SWITCHED** | IMPROVEMENT.md |
| 52 | 2026-10-29 | Pick straight up from the favorite or a model/market blend | Favorite only 66.48%; 0.35 blend 67.11% (in-sample); 0.25 blend 66.69% (found on the hold-out); model 66.06% | **DECLINED by you ('basic and boring')** | round-1/fixes.md |
| 53 | 2026-10-29 | Do bigger edges win more? | No: not monotone; the biggest moneyline edges are the worst; the highest-chance third of bets is the worst (-8.1%) | **FINDING** | round-2/grade.md |
| 54 | 2026-10-31 | No spread bets at a whole number (your rule: you can't place them) | 2013-20 ROI +2.65% -> +5.57% (t +1.4), 2021-25 -0.30% -> -2.76% (t -1.2): no measurable cost. Skipping the whole game instead is no better. The card shifts toward moneylines | **YOUR RULE (shipped)** | scripts/half_point_rule.py; expert-review/half-point-rule/ |
| 55 | 2026-10-31 | Spreads vs moneylines in the replayed card | No rule: spreads +2.8% (SE 4.5%) on 450, moneylines -7.1% (SE 6.2%) on 203. With the rule: +7.5% on 268 vs -10.4% on 360 | **FINDING (spreads + moneylines locked)** | half_point_rule.txt |

### Live 2026 evaluation

| # | date | test | result | verdict | details |
|---|---|---|---|---|---|
| 56 | 2026-10-27 | Closing line value (first-published number vs FanDuel's close), Weeks 1-7 | Spreads +0.33 pts on 23, moneylines +0.1% on 26: about zero | **FINDING** | review_week.py; CLAUDE.md s0 |
| 57 | 2026-10-29 | Value at the price taken (card bets, Weeks 1-7) | -2.8% a bet (t -3.56, 45 bets): the bets match the close and pay the vig | **FINDING** | data/model_bet_ledger_2026.csv |
| 58 | 2026-10-29 | Straight up vs the favorite, Weeks 1-7 | Model 64-42 vs favorite 67-39; against the favorite 2-5 | **FINDING** | review_week.py |
| 59 | 2026-10-29 | Good or lucky? The card's 25-19-1 | Model expected 24.3 wins, the close 21.8: about 1 SD lucky | **FINDING** | review_week.py |

### Data bugs found and fixed

| # | date | test | result | verdict | details |
|---|---|---|---|---|---|
| 60 | 2026-09-30 | nflverse lists a QB who threw 0 passes | Replaced by the attempts leader; error 10.090 -> 10.085 (neutral) | **FIXED** | tests/test_qb_correction.py |
| 61 | 2026-09 | --qb override silently discarded (fillna) | Override moved the line by 0.0 | **FIXED + test** | CLAUDE.md s3 |
| 62 | 2026-08-30 | Displayed spread sign inverted | Printed the opposite side of every game | **FIXED + test** | README 'Bugs' |
| 63 | 2026-08-30 | Push/cover chances blind to 3 and 7 | Flat 3.3% push everywhere; now the real margin distribution | **FIXED** | README |

### Process fixes

| # | date | test | result | verdict | details |
|---|---|---|---|---|---|
| 64 | 2026-10-11 | In-progress London game re-priced | Kickoff time now counted | **FIXED + test** | tests/test_kickoff.py |
| 65 | 2026-10-29 | Spread price borrowed from another book labeled FanDuel | Labeled and warned | **FIXED** | round-1/changes.md |
| 66 | 2026-10-31 | Season scorecard graded rematches with the earlier game, ties as losses | 64-46 printed; right answer 64-42 | **FIXED** | scripts/grade.py |
| 67 | 2026-10-31 | Game-day cards that never reached the record (Week 5 open in Excel, Week 7 scratch copy only) | Run now saves beside an open workbook, prints card changes, flags stale --qb | **FIXED** | workbook_guard.py |
| 68 | 2026-10-31 | 'Still a bet at' number for game day | Worst number or price each bet survives (half points only since your rule) | **SHIPPED** | NFLModel.still_qualifies |

---

## 6. Live 2026 results

Graded from the model's own published card (`picks/2026/`, the bet ledger), never
from your tracker. Straight-up columns leave out the one tie (Week 5 NYG @ WAS,
27-27). "Value" is each bet's value at the price taken, measured against FanDuel's
de-vigged close.
Weeks 1-3 were staked half-Kelly at the time, and Week 1 had 9 bets (before the 4-7
card); "$ at $5" puts every week on the same $5 footing.

| week | straight up: model / favorite | model's picks against the favorite (at publication), won | card W-L-P | $ at $5 | value at the price taken | the card's bets |
|---|---|---|---|---|---|---|
| 1 | 11 / 12 of 16 | 0 of 1 | 3-6 | +2.05 | -4.0% | NYG +3.0 (W); TEN -122 (L); IND +145 (L); CLE +360 (L); ARI +390 (W); SF +164 (W); CAR +136 (L); NO +250 (L); TB +170 (L) |
| 2 | 10 / 11 of 16 | 0 of 1 | 1-3 | -10.54 | -4.9% | ATL +2.5 (L); JAX +2.5 (L); CLE +8.5 (W); DET +185 (L) |
| 3 | 8 / 8 of 16 | 0 of 0 | 4-1 | +11.59 | -1.6% | CHI +4.5 (W); MIA +10.5 (L); NYG -138 (W); IND +108 (W); BAL -178 (W) |
| 4 | 11 / 9 of 16 | 2 of 2 | 4-1-1 | +14.43 | -2.8% | JAX +2.5 (W); ATL +2.5 (W); CHI -3.5 (W); TB +3.0 (P); BUF -350 (L); NYG +118 (W) |
| 5 | 8 / 9 of 14 | 0 of 1 | 4-3 | +2.83 | -4.5% | TB +8.5 (W); NYG +3.5 (W); MIN -2.5 (W); BAL +3.5 (W); TEN +6.5 (L); SEA -172 (L); CHI -120 (L) |
| 6 | 7 / 9 of 14 | 0 of 2 | 3-4 | -8.91 | -5.0% | DEN +2.5 (W); NYG +1.5 (L); PHI +3.5 (L); JAX -2.5 (L); IND -340 (L); BUF -245 (W); GB -118 (W) |
| 7 | 9 / 9 of 14 | 0 of 0 | 6-1 | +24.55 | +3.2% | DEN -4.5 (W); PHI +4.5 (L); CIN +2.5 (W); PIT -174 (W); CLE -126 (W); MIA +205 (W); DET -172 (W) |

**Season through Week 7**
- **Straight up:** the model went 64-42 and the favorite 67-39. When the model picked
  against the favorite it went 2-5.
- **Card:** 25-19-1, +$36.00 at $5. By its own odds the model expected 24.3 wins;
  FanDuel's close expected 21.8.
- **Value at the price taken:** −2.8% a bet (t −3.56). The bets matched the close and
  paid the vig.
- **CLV from first-published numbers:** spreads +0.33 pts on 23 bets, moneylines +0.1%
  on 26. About zero.
- **Your own tracker** (Week 7 save): 20-8, +$46.13.
- **Margin error:** the model averaged 9.59 against the closing line's 9.41.

<!-- WEEK8 -->

---

## 7. Decisions you have made

**Locked** (checked for bugs only, never changed):
- FanDuel only;
- spreads and moneylines (no totals);
- $5 flat;
- 4 to 7 bets a week.

**Your rules:**
- no moneyline underdogs longer than +250 (09-25);
- no spread bets at a whole number (10-31: "I can't do that").

**Your calls:**
- **Decision mode on (09-14):** real bets, against the original advisory default.
- **Ranking:** the card is ranked by the model's chance the bet wins, not by edge
  (10-07).
- **Self-tune:** on everything (09-25), then off once it was shown neutral (10-29).
- **Trend fixes:** on, but only for consistent reasons, never single games ("don't
  make the Falcons #1 because they looked good once").
- **Grading the model:** from its own card, never your tracker (10-29).
- **Your tracker:** K6, M5 and every formula you add carry exactly, and the charts you
  keep are updated every week (10-12, 10-13).
- **Tracker closes:** the build fills FanDuel's close into the Closing Line and Closing
  Odds cells you leave blank (10-29).
- **Past weeks' workbooks:** read-only, never rebuilt (10-07).

**Declined:**
- picking straight up from the favorite or a model/market blend ("basic and boring");
- game-day QB guardrails (your own check before betting).

## 8. Open questions

- **Round 3: now or later?** The next real information is live 2026 straight-up results
  and CLV, one week at a time. Waiting a few weeks gives a grader more to work with.
- **The 80-85% calibration bucket.** Picks called 82% won 74% on 107 games, 2.3 SE
  short. Re-fitting on 2021-25 would be fitting the test; 2026 live will tell.
- **Moneylines replay worse than spreads.** On 2021-25 spreads returned +2.8% and
  moneylines −7.1%, both inside the noise. Spreads + moneylines are locked, so this is
  only noted. Your half-point rule moves more of the card to moneylines.
- **Information beyond the line.** The model as it runs shows +0.34 (t 1.86), a hint
  that isn't proven. Only live seasons can confirm it.
- **Replacement-level quarterbacks.** Several 2026 bets (PHI with McKee, TB with Jalon
  Daniels) rested on the pooled value for QBs with fewer than 8 starts. History says
  such QBs run about 1 pt worse than the model thinks (watch list).
- **The one lever the research and the tests agree on is price,** but you bet at one
  book (locked).

## 9. Where everything is

| what | where |
|---|---|
| This reference | `expert-review/REFERENCE.md` |
| Every test, one row each | `expert-review/test_database.csv` |
| Start here for re-grading | `expert-review/README.md` |
| Rubric (v2, locked) / v1 | `expert-review/rubric.md` / `round-1/rubric-v1.md` |
| Research summary for a grader | `expert-review/expert-brief.md` |
| Full research report / raw output | `expert-review/research/deep-research-report.md` / `deep-research-raw.json` |
| Source texts and data (this Mac only, not in git) | `expert-review/research/sources/` |
| Grader prompt | `expert-review/grader-prompt.md` |
| Round 1 and 2: grade, fixes, changes, grader scripts | `expert-review/round-1/`, `expert-review/round-2/` |
| Outputs behind round-2 fixes (ablation, design checks, not-shipped runs) | `expert-review/round-2/fix-outputs/` |
| Half-point rule replay | `expert-review/half-point-rule/half_point_rule.txt` |
| Score history | `expert-review/report-card.md` |
| The test log, in prose | `IMPROVEMENT.md` (log of tested candidates) |
| Running state, decisions, dead ends | `CLAUDE.md` |
| Weekly and game-day procedure | `OPERATING.md` |
| Original validation, rejected ideas, bugs fixed | `README.md` |
| Live picks and bets (the record) | `picks/2026/` |
| Every model bet, graded | `data/model_bet_ledger_2026.csv` |
| Scripts that reproduce the numbers | `scripts/replay_deployed.py`, `ablation.py`, `design_checks.py`, `half_point_rule.py`, `refit_factors.py`, `factor_lab.py`, `miss_report.py` |
