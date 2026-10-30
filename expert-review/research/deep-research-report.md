# Deep research: NFL spread / moneyline modeling (2026-10-27)

Generated from the `deep-research` workflow run for the expert review (raw output: `deep-research-raw.json`). Its conclusions were folded into `../expert-brief.md`, which is what a grader reads. This file keeps the evidence so it never has to be re-searched.

**Question.** For an expert review of a personal NFL prediction and betting model (ridge-regularized team + quarterback power ratings in points, blended early-season with a market prior backed out of point spreads, plus non-QB injury, opponent-adjusted EPA/play and rest-day factors; it picks every game straight up and bets 4-7 spreads or moneylines a week at FanDuel only, flat stakes, usually placed on game day near kickoff). The owner's goals: (a) raise straight-up pick accuracy (currently ~60% this season vs ~63-64% for simply taking the betting favorite), and (b) make the value bets genuinely positive-expectation rather than lucky. Research: (1) What straight-up accuracy do the best public NFL models achieve (FiveThirtyEight Elo/QB-adjusted Elo, ESPN FPI, Massey/Sagarin, nfelo, prediction markets, the closing-line favorite), and is there credible evidence any model beats the closing-line favorite on straight-up picks over multiple seasons? (2) Which inputs are documented to add predictive information beyond the closing spread (QB adjustments and backup-QB pricing, injuries, EPA/success-rate efficiency, rest/bye, travel, weather, early-season priors, market-blending), and which are already fully priced by the market? (3) Best practices for honestly evaluating a small live sample (about 107 games and 49 bets): closing line value as the primary skill signal, Brier score/log loss versus de-vigged market probabilities, expected-versus-actual wins, how many bets are needed to detect a real edge. (4) Timing: early-week versus game-day line value in NFL markets, how efficient the NFL closing line is, and whether a bettor who bets near kickoff at one sportsbook can realistically hold an edge. (5) Bet selection: edge thresholds, key numbers (3, 7) in spread betting, the favorite-longshot bias in NFL moneylines, and whether larger model-vs-market disagreements historically predict better or worse outcomes.

**Run.** 5 search angles, 21 sources fetched, 101 claims extracted, 7 confirmed by 3-vote adversarial check, 0 refuted, 18 unverified (their verification votes errored when the account hit its spend limit, so they are leads, not facts).

## Confirmed claims (2 of 3 verifiers or more agreed)

1. Over 4,737 games from 2009 through Week 7 of 2026, nfelo's straight-up accuracy was 66.50%. That is 0.19 percentage points below simply picking the closing-line favorite (about 66.69%) and 0.30 points above picking the opening-line favorite (about 66.20%). Its margin error (MAE 10.1 pts) beat the closing spread by only 0.01 pts, compared with 0.12 pts vs the opener. So this leading public model has not beaten the closing favorite on SU picks across 17 full seasons plus 2026 to date, and the closing line is clearly sharper than the opener. The sign convention is confirmed by the page's red/green styling and its embedded data: marketCloseSuAvg 0.6669, marketOpenSuAvg 0.6620, model 0.6650; close-line MAE 10.095, open-line MAE 10.213, model 10.089.
   - Source: https://nfeloapp.com/games/nfl-model-performance/
   - Quote: "Accuracy 66.50% % of winners predicted vs Opening Line +0.30% vs Closing Line -0.19% … Prediction Error 10.1 Model Mean Absolute Error vs Opening Line MAE +0.12 vs Closing Line MAE +0.01"
   - Vote: 3-0

2. Season by season, nfelo beat the closing-line favorite's SU accuracy in only 8 of 18 seasons (2009 to 2026 to date): 2010, 2012, 2014, 2015, 2017, 2018, 2020 and 2021. It trailed in 8 (2009, 2011, 2013, 2016, 2019, 2022, 2023, 2025) and tied in 2 (2024 and 2026 to date). The yearly gaps ran from -1.5 pts (2011) to +1.6 pts (2020) and average -0.19 pts. That looks like noise around zero, not a durable SU edge over the closing favorite.
   - Source: https://nfeloapp.com/games/nfl-model-performance/
   - Quote: "Season | Model SU% | vs Close … 2011 | 65.2% | -1.5% … 2020 | 69.9% | 1.6% … 2024 | 70.5% | 0.0% … 2026 | 63.2% | 0.0%"
   - Vote: 3-0

3. In the 2026 season through Week 7 (107 games, per the page's embedded data), picking the closing-line favorite went 63.2% straight up (about 67 of 106 games with a favorite). nfelo matched it exactly at 63.2% (0.0 vs close), which is the same ~63% favorite baseline the owner is measuring against. nfelo's 2026 spread plays went 60.0% vs the opening line (18-12, +4.8 units) and 55.2% vs the close (16-13-1, +1.7 units) on 30 plays each, with only +1.95% average CLV.
   - Source: https://nfeloapp.com/games/nfl-model-performance/
   - Quote: "2026 | 63.2% | 0.0% | 9.4 | -0.01 | 30 | 60.0% | +4.8 | 1.95% | 30 | 55.2% | +1.7"
   - Vote: 3-0

4. nfelo's spread plays do much better against opening numbers than closing numbers. Against the opening line they went 57.01% ATS (1,041-785-39 on 1,865 plays, +177.5 units, scored as +1 per win and -1.1 per loss at -110). Against the closing line they went 54.15% (881-746-45 on 1,672 plays, about +60.4 units, roughly 3.4% ROI). Average closing line value is +6.02% per play. Plays chosen and graded at closing numbers, which is what a bettor near kickoff gets, earned only about a third of the opening-line profit. The page lists 'Expected Units 112.2' without defining it. It also does not say which seasons were tracked live versus back-tested, or how plays are selected (no edge-threshold breakdown).
   - Source: https://nfeloapp.com/games/nfl-model-performance/
   - Quote: "ATS Win Rate 57.01% Against the opening line Against the closing line 54.15% Units since 2009 177.5 … CLV 6.02% Average Closing Line Value / play Expected Units 112.2"
   - Vote: 2-1

5. Straight-up (SU) accuracy, 2025 season (285 games): the tracker's updated betting line picked 66.5% of winners (189-95) and ranked 3rd of 52 entries. Daniel Curry Index was the only entry with a higher rate (66.9%), but it had fewer wins on fewer games (186-92 of 279). The average of all computer systems only tied the line. NFELO went 65.8% (187-97), ESPN FPI 63.4% (180-104), and Massey and Sagarin each 62.7% (178-106). Adding up the 2023-2025 season pages (855 games): the line went 580-274 (67.9%). The best computer system, FF-Winners, was just one game better at 581-273. Donchess Inference went 577-277, ESPN FPI 557-296 (65.3%) and Massey 548-306 (64.2%). The top system changed every year: Daniel Curry Index was 51st of 52 in 2023 (58.6%) and 1st in 2025, and FF-Winners fell from 1st in 2023 to 24th in 2025. FiveThirtyEight and prediction markets are not tracked on the page.
   - Source: https://www.thepredictiontracker.com/nflresults.php?type=1&orderby=wpct%20desc&year=25
   - Quote: "Column order: Rank System Pct. Correct Against Spread Absolute Error Bias Mean Square Error games suw sul atsw atsl. From the year=25 page: 1 Daniel Curry Index 0.66906 0.48897 10.6615 1.06320 179.44800 279 186 92 133 139 2 System Average 0.66549 0.50542 10.0502 0.01510 161.11000 285 189 95 140 137 3 Line (updated) 0.66549 0.50376 9.6947 -0.64210 151.45500 285 189 95 67 66. From the year=23 page: 1 FF-Winners 0.68421 0.48148 10.1298 -1.19650 176.63000 285 195 90 104 112 2 Line (updated) 0.66316 0.49419 10.0035 -1.16840 175.40200 285 189 96 85 87. From the year=24 page: 7 Line (updated) 0.70877 0.47692 9.7754 -0.67720 162.25300 285 202 83 62 68"
   - Vote: 3-0

6. Current 2026 season (the same page with year=26, data through 2026-10-26, 107 games, the same sample size as the owner's): the updated line has picked 64.2% straight up (68-38). None of the 55 entries has a higher rate; NFELO and the midweek line tie it. The average of all systems is at 60.4% (64-42), the opening line 60.4% (64-42), Massey 61.3% (65-41) and ESPN FPI 57.5% (61-45). Seven entries tie at 60.4% in ranks 17-23. So a model at about 60% SU this season is in the middle of the public systems and about 4 wins behind the betting favorite on these 107 games.
   - Source: https://www.thepredictiontracker.com/nflresults.php?type=1&orderby=wpct%20desc&year=25
   - Quote: "From the year=26 page: 2026 Season Totals Through 2026-10-26 ... 1 NFELO 0.64151 0.60345 9.4347 2.15430 144.25900 107 68 38 35 23 2 Line (Midweek) 0.64151 9.5047 2.11210 146.02800 107 68 38 3 Line (updated) 0.64151 0.62745 9.3832 2.15890 143.62000 107 68 38 32 19 ... 17 System Average 0.60377 0.49020 9.8135 2.63120 157.85000 107 64 42 50 52 ... 36 ESPN FPI 0.57547 0.50000 9.8716 2.06240 157.13800 107 61 45 51 51"
   - Vote: 3-0

7. Error on the predicted point margin: in 2025 the updated line was the most accurate of all 52 entries, with the lowest mean absolute error (9.6947) and the lowest mean squared error (MSE, 151.455). The all-systems average had the same 189-95 SU record but an MSE of 161.11. In 2026 so far the line again has the lowest MSE (143.62) among entries that cover all 107 games. One system did beat the line for a single season but not over three: in 2024 Donchess Inference beat it on all 285 games (MAE 9.7330 vs 9.7754; MSE 158.418 vs 162.253). It then trailed in 2023 (181.625 vs 175.402) and 2025 (155.914 vs 151.455), for a 3-season average MSE of 165.3 against the line's 163.0. FF-Winners matched the line's SU record over 2023-25 but had a much worse 3-season average MSE (170.5 vs 163.0). In other words, its win-loss record overstates its real accuracy. (The 3-season averages are computed from the season rows.)
   - Source: https://www.thepredictiontracker.com/nflresults.php?type=1&orderby=wpct%20desc&year=25
   - Quote: "From the year=25 page: 2 System Average 0.66549 0.50542 10.0502 0.01510 161.11000 285 189 95 140 137 3 Line (updated) 0.66549 0.50376 9.6947 -0.64210 151.45500 285 189 95 67 66 ... 24 FF-Winners 0.64085 0.50936 10.0333 0.15400 162.48400 285 182 102 136 131. From the year=24 page: 1 Donchess Inference 0.72632 0.50189 9.7330 -0.42420 158.41800 285 207 78 133 132 ... 7 Line (updated) 0.70877 0.47692 9.7754 -0.67720 162.25300 285 202 83 62 68"
   - Vote: 3-0

## Unverified claims (leads; check before relying on them)

1. Line timing: the line gets much more accurate between the opening number and midweek, and barely changes after that. In 2025 the opening line went 62.3% SU (177-107, 41st of 52, MSE 159.814), against 65.8% for the midweek line (MSE 151.800) and 66.5% for the updated line (MSE 151.455). In 2023 the opening line went 58.6% (167-118, 50th of 52, MSE 185.755), against 65.3% midweek (MSE 175.002) and 66.3% updated (MSE 175.402). In 2024 it went 67.7% (MSE 170.087), against 71.2% and 70.9% (MSE 162.137 and 162.253). Over 2023-25 combined: opening 537-317, midweek 576-278, updated 580-274. In 2026 so far: opening 64-42, midweek and updated both 68-38. The midweek line had a slightly lower MSE than the updated line in 2023 and 2024. The side the line moved toward after midweek went 214-221 against the midweek number over 2023-25, but 32-19 so far in 2026.
   - Source: https://www.thepredictiontracker.com/nflresults.php?type=1&orderby=wpct%20desc&year=25

2. The study took betting lines from the day before the game or the day of the game. Using those lines, the betting-market favorite picked the straight-up winner in 65.8% of 1,195 NFL games (weeks 5/6/7-17 of the 1994-2000 seasons, with 17 pick'em games left out). It was the most accurate method in each of the seven seasons, with yearly figures of 62.9% to 68.3%. Over 1,212 games (Table 3), the alternatives scored lower: 60.8% for 'the team ranked higher by the NYT power score wins', 61.1% for 'the home team wins', and 59.7% for the NYT sports editor.
   - Source: https://brendanwhit.github.io/ds1-final-project/lit-review/boulier2003.pdf

3. The paper also ran a real-time test: recursive, out-of-sample probit regressions on the power-score difference plus home field, with the probabilities turned into win/loss picks. That model had a Brier score of 0.382 (about 61.8% correct). The betting-market favorite had 0.351 (about 64.9% correct) over 1994-2000 (Table 6, roughly 1,106 to 1,122 games). The market had the lowest error in every season except 1996, and the authors conclude that the recursive probit predictions 'were inferior to forecasts based on the betting market.'
   - Source: https://brendanwhit.github.io/ds1-final-project/lit-review/boulier2003.pdf

4. Across 5,679 NFL regular-season games from 2002 to 2023, a Bayesian state-space model of point differential that controls for team strength and home advantage finds that the regular-season bye-week edge has no statistically detectable effect after the 2011 CBA: +0.31 points per game (95% CrI -1.01 to 1.64), with a 67.9% probability of being positive. Before 2011 it was +2.21 points (95% CrI 0.61 to 3.80), and the posterior probability that the effect declined is 96.6%. The paper attributes the old effect to extra practice, which the 2011 CBA removed, rather than to rest.
   - Source: https://arxiv.org/abs/2408.10867

5. Point spreads already price the bye edge, and the market moved the opposite way from actual results: the implied spread value of a bye rose from +0.39 points pre-2011 (95% CrI 0.00 to 0.78) to +0.97 points after (95% CrI 0.65 to 1.28). The authors say the market now overvalues the bye by about half a point. That overvaluation is not statistically established, though: it sits inside the wide post-2011 outcome interval. The paper also notes that +0.97 matches its pooled 2002-2023 outcome estimate of +1.11 (95% CrI 0.07 to 2.15). So a separate rest or bye factor on top of the spread is unlikely to add information.
   - Source: https://arxiv.org/abs/2408.10867

6. The return predictability (mispricing) found in sports betting contracts is small, only a fraction of comparable anomaly returns in financial markets, and it does not cover transaction costs (in betting, mainly the bookmaker's vig). That is why arbitrage does not remove it: these systematic signals do not make money after costs.
   - Source: https://econpapers.repec.org/RePEc:bla:jfinan:v:76:y:2021:i:6:p:3153-3209

7. The gap between a strong public model and the closing market was very small and took a very large sample to resolve. After 25,165 games, the 95% empirical-Bernstein confidence sequence for the average Brier-score differential (538 minus vegas) was (-0.00265, -0.00062). The confidence sequence placed the differential below zero only from about game 10,000 onward. Samples of about 100 games are orders of magnitude too small to separate forecasters that differ by this much.
   - Source: https://arxiv.org/abs/2110.00115

8. Re-checking classical fixed-sample forecast-comparison tests as results come in inflates false positives. In the paper's simulation the two forecasters have no true Brier-score difference. Even so, the cumulative type I error of the Diebold-Mariano test passed 0.05 after about 100 steps, and the Giacomini-White test's after about 1,000 steps. Both kept rising, and fixed-time confidence intervals showed the same problem. The paper's confidence sequences kept the error rate at or below alpha at any data-dependent stopping time.
   - Source: https://arxiv.org/abs/2110.00115

9. NFL lines (1985-2013, 7,035 games) overreact between open and close. The return from the closing line to the game result is significantly negatively related to the open-to-close line move. Table III gives beta1 = -0.34 (t = -6.32) for spreads, -0.46 (t = -8.31) for totals and -0.58 (t = -2.55) for moneylines. So roughly a third to a half of each move is reversed by the outcome, which rejects the efficient-close hypothesis (beta1 = 0). The moves are only partly reversed (beta1 is well above -1), so they still carry some information. The data come from Vegas and offshore market-setting books (Pinnacle, 5Dimes, BetCRIS), before legal US sports betting.
   - Source: https://conference.nber.org/conf_papers/f92072/f92072.pdf

10. The predictable patterns in line moves are too small to beat the vig. Pooled across NBA, NFL, MLB and NHL (Nov 1998-Mar 2013), every momentum, value and size betting strategy has a negative net return. The combined multi-strategy bet at the close earns +2.61% gross but -0.58% net (annualized). Traded from open to close it earns +0.47% gross and -4.45% net, because the vig is paid twice. These costs leave out price impact from moving the line, which would make the results worse.
   - Source: https://conference.nber.org/conf_papers/f92072/f92072.pdf

11. Straight-up benchmark: in 2,560 NFL games from 2002 to 2011 (closing lines mostly from The GoldSheet), the closing-line favorite covered 1,194 times, won without covering 412 times, lost outright 853 times and pushed 101 times. So the closing favorite won straight up about 65-67% of the time (derived from the 853 outright losses; the exact figure depends on how pushes are counted). It lost against the spread in 51.5% of non-push games. The authors conclude the line is 'a good predictor of the team that will win the game straight up but historically less than 50% accurate' against the spread. This long-run 'pick the closing favorite' rate is slightly above the ~63-64% favorite rate in the owner's current season.
   - Source: https://arxiv.org/abs/1211.4000

12. Opening and closing lines predicted equally well. The authors re-ran every calculation with both lines and found no statistically significant difference in predictive value. They cite Gandar et al. (1988), who found the opening line's mean squared error slightly smaller, but not significantly. Lines rarely moved much: of 2,560 games, over 2,000 moved 1 point or less and 1,548 moved 0.5 points or less, so only ~20% moved more than 1 point. The ~10% of games that moved 2+ points showed no consistent, exploitable pattern. Caveat: this is a coarse test based on game outcomes, using only opening and closing numbers. It has no intra-week, game-day or per-book data and no closing-line-value analysis, so it says nothing direct about betting near kickoff at a single book.
   - Source: https://arxiv.org/abs/1211.4000

13. In Data Golf's 2019-2020 golf matchup/3-ball betting sample (45,866 flat 1-unit bets across 11 books), the model's realized ROI landed slightly under halfway between the blind-betting return and the model's own expected ROI. That implies the best fair price is roughly a 45% model / 55% market blend. At that weight, a raw model edge of about 7-8% is needed before a bet is truly positive-EV (0.55 x -6% + 0.45 x 8% = +0.3%). A 2020 PGA Tour-only subset implied a 60-65% model weight, enough to flip ROI from about -1% to +1%, but the author flags that subset as selectively shown.
   - Source: https://datagolf.com/how-sharp-are-bookmakers

14. Betting every positive edge from the golf model lost money: -0.92% realized ROI against +5.16% expected on 45,866 bets. That beat the -5.9% blind-betting benchmark but did not overcome the vig. A profit required a model-EV threshold of 5% or more, and total profit peaked at the 8% threshold (+4.43% realized vs +14.12% expected, 9,103 bets). Realized ROI generally rose with the size of the model-market disagreement, reaching about +9.0% at a 16% threshold (2,241 bets) before tailing off (+6.73% at 20%). It stayed far below the model's expected ROI at every threshold (9.00% vs 23.81% at 16%).
   - Source: https://datagolf.com/how-sharp-are-bookmakers

15. In 2,000 simulations of random betting into Pinnacle's no-vig, roughly 50/50 golf matchup prices (expected ROI about -3.7%), 36.4% of 100-bet samples and 11.6% of 1,000-bet samples still finished in profit. The 100-bet 5th-95th percentile ROI range was -19.83% to +12.55%. The author concludes that chance remains a meaningful driver below about 5,000 bets, that 2-3% ROI swings are possible even at 10,000 bets, and that thousands of bets are needed to show a statistically meaningful difference between two similar models.
   - Source: https://datagolf.com/how-sharp-are-bookmakers

16. For NFL games from 2007 through 2016, both the opening and the closing money lines were inefficient, and the closing line did not fully remove the inefficiencies present at the open. So the NFL closing money line was not perfectly efficient in this period. Caveat: only the abstract is free. The full text (pp. 87-117) costs USD 10, so the effect sizes, the sample size, the sportsbook used and whether the inefficiency is bigger than the vig cannot be seen. The sample also ends in 2016, before the US legal market expanded in 2018.
   - Source: https://journalofeconomicinsight.com/index.php/joei/article/view/1335

17. NFL money lines from 2007 to 2016 show a REVERSE favorite-longshot bias: bettors overbet favorites and underbet underdogs. In the authors' reading, favorites are priced too high relative to underdogs, which is the opposite of the classic favorite-longshot bias where longshots are overbet. For moneyline bet selection, this means favorite moneylines are the side bettors overpay for.
   - Source: https://journalofeconomicinsight.com/index.php/joei/article/view/1335

18. The money line inefficiencies found for 2007-2016 are not stable or predictable. They vary from season to season, so the bias the authors found cannot be counted on as a repeatable edge in any given season.
   - Source: https://journalofeconomicinsight.com/index.php/joei/article/view/1335

## Sources

| # | URL | Quality | Claims |
|---|---|---|---|
| 1 | https://nfeloapp.com/games/nfl-model-performance/ | primary | 5 |
| 2 | https://www.thepredictiontracker.com/nflresults.php?type=1&orderby=wpct%20desc&year=25 | primary | 5 |
| 3 | https://brendanwhit.github.io/ds1-final-project/lit-review/boulier2003.pdf | primary | 5 |
| 4 | https://johanntin.github.io/nfl2025-analysis | blog | 5 |
| 5 | https://arxiv.org/abs/2408.10867 | primary | 3 |
| 6 | https://econpapers.repec.org/RePEc:bla:jfinan:v:76:y:2021:i:6:p:3153-3209 | primary | 4 |
| 7 | https://www.nfeloapp.com/analysis/team-and-scheme-nfl-qbs/ | blog | 5 |
| 8 | https://www.pinnacleoddsdropper.com/blog/closing-line-value--clv-demystified-by-expert-joseph-buchdahl | blog | 5 |
| 9 | https://www.football-data.co.uk/blog/luck_skill_sports_betting.php | blog | 5 |
| 10 | https://www.football-data.co.uk/blog/closing_odds.php | blog | 5 |
| 11 | https://www.karlwhelan.com/?p=2595 | blog | 5 |
| 12 | https://www.nfeloapp.com/analysis/using-market-regression-to-improve-prediction-accuracy-in-the-nfl/ | blog | 5 |
| 13 | https://arxiv.org/abs/2110.00115 | primary | 5 |
| 14 | https://www.pff.com/news/bet-why-betting-early-critical-beating-nfl-markets | blog | 5 |
| 15 | https://conference.nber.org/conf_papers/f92072/f92072.pdf | primary | 5 |
| 16 | https://arxiv.org/abs/1211.4000 | primary | 5 |
| 17 | https://www.rotowire.com/football/article.php?id=40172 | blog | 5 |
| 18 | https://datagolf.com/how-sharp-are-bookmakers | primary | 5 |
| 19 | https://journalofeconomicinsight.com/index.php/joei/article/view/1335 | primary | 5 |
| 20 | https://www.aqr.com/insights/research/working-paper/what-can-betting-markets-tell-us-about-investor-preferences-and-beliefs-implications-for-low-risk-anomalies | primary | 4 |
| 21 | https://www.gwern.net/doc/statistics/decision/1994-benter.pdf | primary | 5 |
