# Expert Brief: NFL Betting Model review (2026 season, Weeks 1-7)

## The project in one paragraph
A personal NFL model (`~/Desktop/NFL-Betting-model`, Python, `.venv/bin/python -W ignore`). Each week it fits ridge-regularized team + quarterback power ratings in points (recency-weighted, joint team/QB fit, QBs under 8 career starts pooled at replacement level), blends them toward ratings backed out of this season's posted spreads (weight `0.8 * 10/(10 + games played per team)`), adds home field (~1.7-2.1), a small per-team EPA "self-tune" nudge (max 0.5 pt/game), three live game factors (non-QB injuries 0.703 pt per starter-equivalent out, opponent-adjusted net EPA/play x1.191, rest-day difference x0.087), and one live "trend fix" (when the model is 3+ pts from the line, pull 1.5 pts toward it). Margins become probabilities by tilting the empirical margin distribution (keeps the 3/7 spikes), then a win-% recalibration. It picks every game straight up (by win probability) and bets spreads (edge >= 1.5 pts) or moneylines (edge >= 3% vs the de-vigged FanDuel pair; favorites no shorter than -350, underdogs no longer than +250), keeping at most 7 bets a week ranked by the model's chance the bet wins (at least 4, topped up with labeled filler). Outputs: terminal report, an Excel workbook per week, and a tracked archive in `picks/2026/`. The owner bets $5 per bet at FanDuel, mostly on game day.

## The owner's goals (in priority order)
1. **Pick more winners straight up.** He sees "59.8%" and wants it higher. The fair yardstick is the betting favorite on the same games.
2. **Edge bets that are good bets, not lucky ones.** Judge bets on price (closing line value, hold-out replays), never on a hot week.
Review weighting he chose: model picks > bets > weekly inputs > workbook.

**Locked (check for bugs only, never propose changing):** FanDuel only; spreads + moneylines only; $5 flat stake; 4-7 bets a week.

## Where the evidence is
- Live archive (what was actually published): `picks/2026/weekNN_picks.csv` (every game's SU pick, win prob, margin, factor terms, `market_favorite`), `weekNN_leans.csv` (lines, prices, edges, bets, factor terms, odds source), `weekNN_first_leans.csv` (first-published bet numbers, Weeks 5-7 only; Weeks 1-4 were backfilled from the final card), `weekNN_closing.csv` (FanDuel closes via Action Network), `weekNN_meta.json` (assumed starters and their source, lock state, weather, trend fixes). `picks/2026/superseded/` holds replaced early versions.
- Results: `nflmodel.data.load_games(seasons)` returns nflverse schedules with `result` (home minus away), `spread_line` (home favored by, positive = home favored; DraftKings close), moneylines and spread odds. **It returns every season regardless of the argument; filter on `season` yourself.**
- Hold-out projections (walk-forward, each game projected only from games before it): `data/cache/base_projections_2013_2025.parquet` (3,562 games: projected_margin, spread_line, result, moneylines). Factor features: `data/cache/factors_2013_2025.parquet`. `scripts/factor_lab.py` scores the factor stack on 2021-25 with weights fit on 2013-20 and the live trend pull.
- His own bets: the Bet Tracker sheet in `output/NFL_Model_2026_Week07.xlsx` (his last save) and `data/bet_log.csv`.
- Scripts: `review_week.py` (weekly grading, CLV, his tracker; **it locks weeks, do not run it**), `grade.py` (season scorecard; run WITHOUT `--save`), `miss_report.py` (run only with `--no-save`), `factor_check.py`, `factor_lab.py`, `adjust_lab.py`, `selftune_sweep.py`, `measure_situational.py`, `measure_injuries.py`. Docs: `README.md` (validation), `IMPROVEMENT.md` (every tested and rejected idea), `OPERATING.md` (weekly procedure), `CLAUDE.md` (running state and decisions).

## Safety rules for anyone grading
- Work ONLY in a scratch copy of the repo. Never write to `~/Desktop/NFL-Betting-model` itself: not `data/`, not `picks/`, not `output/`.
- Never run `run_week.py`, `review_week.py`, `run_backtest.py` (refreezes parameters), `tune.py`, `build_base_projections.py`, `miss_report.py` without `--no-save`, or `grade.py --save`, even in the scratch copy unless you need its output and accept that it rewrites scratch files.
- The scripts do `sys.path.insert(0, 'src')`, so run them from the scratch copy's root with the original interpreter `~/Desktop/NFL-Betting-model/.venv/bin/python -W ignore`.
- Open workbooks only as copies, read-only.

## Pitfalls specific to this project (hunt for these)
1. **Picking against the favorite.** The SU pick is the model's own win probability. Check how often it disagrees with the favorite and whether those disagreements win (hold-out and live). A model with no information beyond the line will lose SU accuracy every time it disagrees.
2. **Live/replay mismatch in the market prior.** `ratings.fit_market_ratings(asof_week=)` keeps lines from earlier weeks "and any game not yet played". Live, that includes the current week's lines; in a replay of a completed season every game is played, so it does not. Verify, and judge whether the hold-out numbers describe the model that runs live.
3. **QB double counting.** The market prior is backed out of spreads that already price each team's starting QB; the QB rating is then added on top.
4. **The trend-fix cliff.** The 1.5-pt pull switches on at exactly 3.0 pts from the line, so 2.9 off keeps 2.9 of edge and 3.1 off shows 1.6.
5. **Replacement-level QBs.** Unrated or inexperienced starters (< 8 starts) all get one pooled value; several 2026 bets rested on that assumption.
6. **Factor weights fit on 2013-2025 run live.** Fine for live use, but any hold-out claim must come from a 2013-20 fit.
7. **Stale caches.** `CLAUDE.md` section 9: the dataset and base projections predate the stale-QB correction (about 0.01 pt MAE).
8. **Timing.** Picks and edges are computed mid-week (Tuesday/Wednesday build, optional Sunday re-run), but he bets on game day. A bet that qualified at Wednesday's number may not at the game-day number. The Week 7 Sunday re-run happened only in a scratch copy, so the archive kept Wednesday's card and a wrong TB starter.
9. **CLV from QB news.** Large CLV on a bet can come from injury news after publication (both directions), which is timing luck unless the model anticipates it.
10. **Small samples.** ~106 live games and ~49 bets. Report SDs; never credit a record by itself.

## Domain standards
(From the research pass; numbered sources at the end.)

**1. Straight-up picks: the closing favorite is the bar, and almost nobody clears it.**
- The closing-line favorite wins about 66-67% of NFL games over the long run: 65.9% in 2007-2020 [1], 65.8% in 1994-2000 (the most accurate method in every one of seven seasons) [2], 66.69% over 4,737 games 2009-2026 Week 7 [3]. The opening-line favorite does worse (63.5% [1]; 66.20% [3]), so later lines carry more information.
- Strong public models do not beat it. nfelo: 66.50% vs the closing favorite's 66.69% over 4,737 games, ahead in 8 of 18 seasons, average gap -0.19 pts [3]. Prediction Tracker 2025: the line went 66.5% (3rd of 52 systems), the average computer system tied it, ESPN FPI 63.4%, Massey and Sagarin 62.7%; over 2023-25 the best computer system was one game better than the line in 855 games [4].
- So: matching the closing favorite on the hold-out is a very good result, and any gap below it is lost wins, because "always take the favorite" is a free alternative pick rule.

**2. Models alone are less accurate than the market; blending is standard practice.**
- On Brier score the market spread alone beat every model tested alone over 2009-19 (nfelo unregressed 4.0% worse, FiveThirtyEight Elo 11-22% worse) [5]. A de-vigged 7-book moneyline consensus scored Brier 0.2103 in 2025 vs ESPN 0.2216 and Polymarket 0.2224; a coin flip scores 0.25 [6].
- Professionals blend toward the market: Massey-Peabody about 45% model / 55% market [7]; nfelo's Brier peaks near 65% market [5]; Benter fits a second-stage logit on log(model p) and log(market p) [8]. The test of whether a model carries signal: if the best blend gives the market 100% of the weight, the model adds nothing [5].
- When a fundamental model disagrees with the market, its own probability is biased toward its view. In Benter's data the model's picks against the public won less often than the model said in all 10 probability bins, so raw model-vs-market gaps overstate edges and must be computed from a blended probability [8]. Data Golf (45,866 bets): betting every positive raw edge lost money (-0.9% realized vs +5.2% expected), realized ROI rose with the size of the disagreement but stayed far below the model's expectation at every threshold, and a large edge threshold was needed to profit [9].

**3. Judging a small sample honestly.**
- Win/loss needs hundreds to thousands of bets: a 10% yield at even money takes about 540 bets to reach 99% confidence [10]; 36% of random 100-bet samples at -3.7% expected ROI finish in profit [9].
- Closing line value is the fast signal: per-bet SD about 0.1 vs about 1.0 for profit and loss, so consistent CLV can show skill in about 50 bets [11]. But the average beat must exceed the bookmaker's margin: a tipster who beat the close on 17 of 23 picks by about 2% was projected to break even [12], and in NBA data only the top CLV decile was profitable [13].
- Re-testing significance every week inflates false positives. In simulation the Diebold-Mariano test's type I error passed 5% after about 100 looks [14]. A Brier gap between a strong model and the closing market took about 10,000 games to resolve [14], so ~100 live games cannot separate forecasters that differ by that much.

**4. What the market already prices and where edges plausibly live.**
- A professional says the market is "much better" than models at injuries, player ratings and qualitative news; model edges come from process: opponent adjustment, discounting garbage time, weather, and how much to weight recent games. Fumble recoveries are random [7].
- Byes: no detectable bye-week effect after the 2011 CBA (+0.31 pts, 95% CrI -1.01 to 1.64), while spreads price a bye at about +0.97, so a separate rest factor on top of the line is unlikely to add information [15].
- Backup QBs: weak evidence the market over-adjusts when a good starter is out (first-start backups replacing above-average starters covered 54% vs 46%, no sample size given) [16].
- Key numbers: a 1.5-pt gap that crosses 3 is more likely a bet than a 2-pt gap that crosses nothing; about 2 pts of disagreement is a rough NFL threshold [7].
- NFL lines overreact from open to close (about a third of the move reverses: spreads beta -0.34, t -6.3) [17], yet systematic betting-market mispricings are small and do not cover the vig [18]. NFL moneylines 2007-16 showed a reverse favorite-longshot bias that was unstable season to season [19].

**5. Timing.** The closing line is sharper than the opener on both straight-up picks and margin error (MAE 10.10 vs 10.21) [3]. A bettor who bets near kickoff at one book faces the sharpest price, so any edge must come from being more accurate than the close, which is the hardest kind. Early-week bets capture value only if the model predicts where the line moves.

## What good numbers look like
| Measure | Benchmark | Good | Exceptional |
|---|---|---|---|
| Straight-up % | Closing favorite, same games (long run ~66.5-67%) | Within 0.5 pt of the favorite on the hold-out | Ahead of the favorite on the hold-out |
| Margin MAE | Closing spread (~9.8-10.1 pts long run) | Within 0.15 pt of the line | At or below the line |
| Brier (win prob) | De-vigged closing moneyline (~0.205-0.215) | Within 0.002 | At or below the market |
| Calibration slope | 1.0 | 0.9-1.1 | 0.95-1.05 with n >= 1,000 |
| Model's incremental coefficient (result on line + model) | 0 = no information | Positive, t >= 1 | Positive, t >= 2 |
| Best model/market blend weight | 100% market = no signal | 10-30% model | 35-45% model (pro level [7]) |
| Spread ATS at real juice | 52.4% at -110 | > break-even on the hold-out | > break-even with a CI excluding it |
| CLV | 0 | Positive, larger than the margin | Positive with t >= 2 over 50+ bets |

## Sources
1. PFF, "Why betting early is critical to beating NFL markets" (2021): https://www.pff.com/news/bet-why-betting-early-critical-beating-nfl-markets
2. Boulier & Stekler, "Predicting the outcomes of NFL games", International Journal of Forecasting 19(2) (2003): https://brendanwhit.github.io/ds1-final-project/lit-review/boulier2003.pdf
3. nfelo model performance dashboard (2009-2026): https://nfeloapp.com/games/nfl-model-performance/
4. The Prediction Tracker, NFL results 2025 and 2023-25: https://www.thepredictiontracker.com/nflresults.php
5. nfelo, "Using market regression to improve prediction accuracy in the NFL" (2020): https://www.nfeloapp.com/analysis/using-market-regression-to-improve-prediction-accuracy-in-the-nfl/
6. J. Tin, NFL 2025 forecast analysis (sportsbooks vs ESPN vs Polymarket): https://johanntin.github.io/nfl2025-analysis
7. RotoWire interview with Rufus Peabody (Massey-Peabody) (2018): https://www.rotowire.com/football/article.php?id=40172
8. Benter, "Computer based horse race handicapping and wagering systems" (1994): https://www.gwern.net/doc/statistics/decision/1994-benter.pdf
9. Data Golf, "How sharp are bookmakers?" (2020): https://datagolf.com/how-sharp-are-bookmakers
10. Football-Data, "Luck vs skill in sports betting": https://www.football-data.co.uk/blog/luck_skill_sports_betting.php
11. Buchdahl on CLV (Pinnacle Odds Dropper, 2024): https://www.pinnacleoddsdropper.com/blog/closing-line-value--clv-demystified-by-expert-joseph-buchdahl
12. Football-Data, "Closing odds" (2016): https://www.football-data.co.uk/blog/closing_odds.php
13. K. Whelan, CLV and NBA moneylines (2026): https://www.karlwhelan.com/?p=2595
14. Choe & Ramdas, "Comparing sequential forecasters" (arXiv 2110.00115): https://arxiv.org/abs/2110.00115
15. Bye-week effect in the NFL, Bayesian state-space model 2002-2023 (arXiv 2408.10867): https://arxiv.org/abs/2408.10867
16. nfelo, "Team and scheme: NFL QBs" (2021): https://www.nfeloapp.com/analysis/team-and-scheme-nfl-qbs/
17. Moskowitz, "Asset pricing and sports betting" (NBER draft, 2017): https://conference.nber.org/conf_papers/f92072/f92072.pdf
18. Moskowitz, Journal of Finance 76(6) (2021): https://econpapers.repec.org/RePEc:bla:jfinan:v:76:y:2021:i:6:p:3153-3209
19. Journal of Economic Insight, NFL money line efficiency 2007-2016: https://journalofeconomicinsight.com/index.php/joei/article/view/1335

## Questions the grader must answer
1. Does the deployed model pick more or fewer winners than the betting favorite on the same games (hold-out and live), and exactly where is the difference made?
2. Is the model more or less accurate than the closing line on margin and win probability, and is it calibrated?
3. Which live components help on the hold-out, which are neutral, and which hurt?
4. Is there any information in the model beyond the line?
5. Have the bets beaten the closing line by more than noise? What does the hold-out say about the selection rules at closing prices?
6. Do bigger edges produce better results?
7. What went wrong with inputs (QB, injuries, prices) and the process, and what did it cost?
8. Is the workbook correct, is his Bet Tracker intact, and does it tell him the truth?
