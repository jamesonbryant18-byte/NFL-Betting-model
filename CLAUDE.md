# CLAUDE.md — context for a fresh session

Read this before touching anything. It is the accumulated result of a long
build-and-audit cycle (2026-08-28 to 08-31, including a 54-agent adversarial
audit) and it exists so you do not re-derive, re-measure, or re-break what is
already settled.

Owner: Jameson. Repo: `jamesonbryant18-byte/NFL-Betting-model` (private).
Working copy: `~/Desktop/NFL-Betting-model`. Python: `.venv/bin/python`
(always pass `-W ignore`).

---

## 0. Where things stand (keep this section current)

**Last updated 2026-10-29 (Thu, expert review round 1 shipped; Week 8 built
before TNF).**
Everything on `main` and pushed.

What changed 2026-09-25/26, all at Jameson's request:

1. **FanDuel only.** `config.MY_BOOK = "fanduel"`: every line, spread juice and
   moneyline pair comes from FanDuel (`shop._attach_single_book`). No
   consensus, no best-of-six shopping table — he bets at one book and asked
   not to be shown others.
2. **Weekly self-tune, EPA version** (OFF since 2026-10-29) (`selftune.py`, `config.SELFTUNE`): each
   team is nudged by how well it actually PLAYED (EPA margin) vs what the
   model projected, never by the final score (the weekly ratings refit
   already uses scores, so a score nudge counts them twice). Max 0.5 pt per
   game. Small, measured at +0.012 pt MAE on the hold-out.
3. **Miss-trend checker** (`trends.py`, `scripts/miss_report.py`,
   `data/trends.json`): the main "learn from mistakes" loop. Fixes a REASON
   the model keeps missing on only if it holds in 2013-2020 AND 2021+ AND
   earns its place alongside the other fixes (per-reason gate, audited).
   As of 2026-09-26 exactly ONE margin fix is live: when the model disagrees
   with the line by 3+ pts, pull it 1.5 toward the line (2021+ MAE
   10.13 → 10.02, t = 6.0). Big/mid favorites, home dogs, night favorites
   and new QB are real but COVERED by it (same cause: compressed spreads).
   Full table, gate and audit in IMPROVEMENT.md.
4. **Longshot fix.** Symmetric win-% recalibration (dogs +151 and longer are
   overrated in both periods, z 6.9 / 5.1; +401 dogs said 25%, won 12-13%)
   and Jameson's hand-set rule: no moneyline dogs longer than +250
   (`THRESHOLDS.ml_max_underdog`). Underdog share of bets 88% → 68%.
5. **Weather** (`weather.py`): Open-Meteo kickoff forecast for every outdoor
   game, shown in the run output, the Weekly Slate and the archive; gamebook
   rain/snow history 2016+ feeds the trend checker. Weather × team style (his
   hypothesis: pass-heavy team in rain) was tested and REJECTED — sign
   opposite in 2013-20, gone in 2021+. Wind and rain/snow favorites are on the
   trend WATCH list; a watch reason is promoted only prospectively (40+ games
   predicted live since 2026, same sign as history, one-sided p < 0.05) and
   must still pass the 2021+ prune. Realistically that takes a season or more.
6. **Workbook**: Weekly Slate gained Weather + Trend fixes columns; new
   **Miss Report** sheet.
7. Mid-week re-runs re-price only unstarted games; Thursday's published pick
   is carried forward untouched.

2026 season so far: Week 1 11-5 SU, Week 2 10-6 SU (locked), Week 3 TNF
ATL 35-14 over GB (model picked GB). Week 3 Sunday/MNF overrides:
`--qb WAS="Marcus Mariota" --qb CHI="Case Keenum"` (Bagent concussion,
Williams doubtful; SEA back to Darnold from the depth chart). Week 3 bets as
of Saturday after the audit fixes: CHI +4.5 $25, MIA +10.5 $25, NYG −138
$25, IND +108 $16, BAL −178 $9. Tuesday's original Week 3 picks are in
`picks/2026/superseded/`. An 11-agent adversarial audit of the new code ran
2026-09-26; every finding is fixed or documented (IMPROVEMENT.md).

**2026-09-28 (Mon, before MNF): factor lab.** Jameson clarified that "adjust
the model" means ADD FACTORS to the core model (what it's missing), NOT
re-rank teams/QBs off results. He cut early-season uncertainty and turnover
luck; asked to test efficiency, matchups, weather, rest/travel, non-QB
injuries, coaching/situation, optimized for BOTH straight-up winners and
betting value. Built `src/nflmodel/factors.py` (pregame, no-leak features;
detailed pbp cached in `data/cache/pbp_wide/`) and `scripts/factor_lab.py`
(ridge fit 2013-20, scored 2021-25). Result on 2021-25: efficiency, matchup,
weather, rest/travel, situation = NO HELP (CV picked max penalty; error
slightly worse). **Non-QB injuries = only candidate**: ~0.62 pts per
full-time-starter-equivalent out, hold-out error -0.09 (t 2.7), SU up in
4/5 hold-out seasons, same coefficient for IR vs weekly report and fresh vs
stale. Vs the LINE it is not significant (fixed-coef t 1.1): helps picking
winners, not proven for betting. NOT wired into run_week — awaiting his call.
Batch 2 same day (`factors.FAMILIES2`, `factors2_2013_2025.parquet`): schedule
spots (letdown/lookahead/after OT/after London/3rd road game), interim coach,
last-3 form vs line, team-specific home field + altitude + surface, referee
crew home bias, 2+ starters out at one unit, total-aware win-% conversion.
ALL no help on 2021-25, alone or on top of injuries (referee "passes" by
0.0004 pts = nothing). Injuries remain the only keeper.

**GAME FACTORS ARE LIVE from 2026 Week 4** (Jameson: "consider more than 3
things", pick favorites, adjust any that perform poorly). `config.FACTORS`:
non-QB injuries 0.703 pt/starter-equivalent out, opponent-adjusted net EPA/play
x1.191, rest-day diff x0.087 (weights = ridge fit 2013-2025). Clean hold-out
(weights fit 2013-20 only, with the live trend pull): SU 65.6% -> 65.8%, error
9.966 -> 9.901, ATS 50.1% -> 52.1%, ML ROI -7.8% -> -1.8%, 3/5 seasons.
Injuries alone is the best BETTING version; EPA was added for winners at a
small betting cost; wind was rejected (sign backwards). Wiring:
`factors.live_factor_shifts` -> `model.factor_adjust` -> `Prediction.factor_adj`;
archived per game (factor_inj/epa/rest/notes); `raw_margin` excludes it so the
trend checker still learns on the frozen model. `--no-factors` opts out. Live
injuries = latest roster status (IR etc.) + this week's Out/Doubtful report,
so a Tuesday run undercounts -- re-run late week. Weekly report card:
`scripts/factor_check.py` (flags a factor at 48+ games and t <= -2; a flag
means re-fit/replace via factor_lab.py, never auto re-weight).
**2026-10-29: EPA/play dropped, weights re-fit** (injuries 0.637, rest 0.048;
see the 10-29 entry below).

**2026-09-30 (Wed): Week 3 locked, stale-QB data fix, Week 4 built.**
Week 3 final 8-8 SU (expected 10.4, inside the band), leans 4-1. His
tracker: 2-2 +$1.74 (the TEN @ NY row is TEN @ NYG, a win the review can't
match -- he was told to fix the matchup text).

The review's "WAS/SEA starter wrong" flags were FALSE. nflverse pre-fills
home/away_qb with the probable starter and does not always correct it:
Week 3 listed Jayden Daniels (sat; Mariota threw all 31) and Drew Lock
(Darnold threw 45). Same in history: 4 games 2022, 32 in 2024, 7 in 2025, and
2026 Week 2 ATL (listed Tua, 0 attempts; Cooper Rush -- the model's override
-- did start, so that -31 miss was NOT an input error). `data.load_games` now
runs `correct_stale_qbs`: a listed QB with ZERO pass attempts for that team
that week is replaced by the attempts leader (nflverse `stats_player_week`,
cached as `qb_attempts_{season}.parquet`). Early in-game injuries (threw >= 1
pass) keep nflverse's listing. Measured 2021-25 hold-out, same code both ways:
MAE 10.090 -> 10.085 (t -0.6), SU 64.08% -> 63.87% (3 games), ATS@1.5
50.46% -> 50.26% -- neutral; shipped as a process-defect fix. Test:
`tests/test_qb_correction.py`.

Week 4 run with `--qb TB="Jalon Daniels" --qb CHI="Tyson Bagent" --qb
WAS="Marcus Mariota"` (Mayfield out 3+ wks; Williams out 3-4 wks, Johnson says
Bagent starts if healthy; Daniels "may sit", market prices Mariota). SEA =
Darnold (depth chart, correct). Bets: JAX +2.5 $25, TB +3.5 $25, CHI -176 $25,
CAR +168 $13, BUF -330 $12. TB +3.5 rests on the rookie being only
replacement level (-2.29); the <8-starts watch item says such QBs run ~1 pt
worse than the model. The model rates Mariota = Daniels (-0.15/-0.16), so the
WAS QB call moves nothing in the model but will move the market line.

**2026-10-04 (Sun):** Week 4 re-run at 12:20 ET, flat $5 stake
(`STAKING.flat_stake`). Bets JAX +2.5, ATL +2.5, CHI -3.5, TB +3, BUF -350,
NYG +118.

**2026-10-07 (Wed): Week 4 locked, Week 5 built.** Week 4 final 11-5 SU
(expected 10.5), leans 4-1-1. The review used to print a push as "loss"
(TB +3, lost 17-14); `review_week.py` now grades leans with
`history.grade_lean`, same as the workbook's Bet Log. Season: 40-24 SU, model
error 9.78 vs closing line 9.63. Factor report card: 16 games, nothing to judge
yet. Trend fixes unchanged.

Week 5 run with `--qb TB="Jalon Daniels" --qb CHI="Tyson Bagent" --qb
BAL="Tyler Huntley"` (Mayfield thumb, out 3+ wks; Ben Johnson named Bagent;
Lamar ankle "unlikely"). WAS = Jayden Daniels from the depth chart (Glazer:
WAS plans to start him; Mariota MCL, out about a month). First build had 10
bets; Jameson: "10 bets seems absurd", wants only the most confident, 4 to 7-8
a week, no forced primetime bet. **Weekly card** (`STAKING.card_max = 7`,
`card_min = 4`, `model._weekly_card`): qualifying bets ranked by the model's
chance the BET wins (pushes left out), top 7 kept, slots already used by bets
on started games count, a thin week is topped up only with positive-EV near
misses labeled FILLER. 2021-25 hold-out: all qualifying 52.2% / ROI -3.9% ->
top 7 by chance 55.4% / -0.7% (se ~3.5%, not an edge); top 7 by biggest edge
was worse (50.8% / -4.4%), so "big edge" is NOT the ranking. Tests:
`tests/test_card.py`. Week 5 card: CIN -310, SEA -162, MIN -1.5, TEN +7.5,
TB +8.5, BAL +3.5, NYG +3.5 (cut: CLE +1.5, ARI +5.5, BUF +138).
His actual Week 4 bets (from his tracker, AutoRecover copy): 4-1, season 6-3
+$16.11; he bet TB +3.5 at -148 (a win), not the model's +3. He types
sportsbook codes ('JAC @ CIN'); `history.TEAM_ALIASES` now matches them.
**BAL +3.5 rests on the QB fit valuing Huntley at +0.36 vs
Lamar +0.71** (0.35 pt apart; the market moved about 6). That is the
ridge-shrunk joint QB fit working as tuned, not a bug. Do not hand-adjust it;
flag it. Re-verify BAL and WAS before Sunday and re-pass all three overrides
on any re-run.

**Closing lines + CLV live from 2026-10-07** (`closing.py`, wired into
`review_week.py` and the Bet Log): the Wednesday review records every game's
close (FanDuel via Action Network, then DraftKings, then nflverse) to
`picks/2026/weekNN_closing.csv` and prints the model's CLV from its
FIRST-published number (`weekNN_first_leans.csv`, kept by `archive_week`) plus
his bets' CLV from the line he typed. Weeks 1-4 backfilled (61 FanDuel, 2 DK,
1 nflverse) but scored from the final card. Season through Week 4: model
spreads +0.35 pts avg on 10 (beat 4, matched 6, worse 0); moneylines +0.1% on
14. Week 5 first-published card seeded 10/7 from the 3:21 PM build. Jameson
now does a **Sunday morning roster run** (OPERATING.md). He saved his Week 4
workbook 10/7 3:48 PM; Week 5 rebuilt after to carry his 9 tracker rows.

**2026-10-08 (Thu night): Game Detail shows BOTH teams.** He complained the
"What drives it" table filled only the Home column (every game-level term
was written there) and Away had just rating + QB. Now every row is points per
team with home − away = net, and a PROJECTED MARGIN row whose two column totals
net to the margin. Per-side inputs come from `factors.live_factor_shifts`
(home_/away_inj_out, _net_epa, _rest, factor_*_home/_away) and
`model.components()` (home_tune/away_tune). Capped terms (self-tune 0.5,
rest 7 days) are scaled so they still net; game-level terms (HFA, situational,
trend fixes) sit under the team they favor. `excel._side_shares` does the
split. Live Week 5 workbook NOT rebuilt (Excel had it open, saved 22:14);
the Sunday morning roster run picks it up. Pre-existing: 2 test_history CLV
failures from b3bc5bb, not yet fixed.

**2026-10-09 (Fri 10:35): Week 5 rebuilt for the both-teams Game Detail.** He
asked whether the old Home-only table meant away inputs were missing from the
math: they never were (every term was already home − away; all 15 Wednesday
margins rebuild exactly from both teams' inputs). Rebuilt with `--refresh`
and the same overrides (TB Jalon Daniels, CHI Tyson Bagent, BAL Tyler
Huntley). His 10:01 save is at `output/superseded/NFL_Model_2026_Week05_saved_2026-10-09_1001.xlsx`;
his 10 tracker rows carried (new: Wk5 TB +8.5 −107 $5 W). Card unchanged
except SEA ML −162 → −174. Depth chart now names Caleb Williams for CHI
(QB RISK 2.2 pt): verify Sunday morning. TB@DAL (played) is no longer in the
Game Detail dropdown, as with any carried-forward game.

**2026-10-11 (Sun 11:58 ET): Week 5 roster run.** Same three overrides, all
confirmed by news (Bagent: Williams ruled out; Huntley: Lamar ruled out Fri;
WAS = Jayden Daniels cleared, NYG = Winston, SEA = Darnold from the depth
chart). **Fixed the Week 4 London bug**: `archive.kicked_off` now counts
kickoff TIME (nflverse `gametime`, Eastern), so the in-progress 9:30 PHI@JAX
game was left as published instead of re-priced (`tests/test_kickoff.py`).
Card vs Friday: CIN ML dropped (-320 -> -360, no longer a price the model
likes), CHI -120 ML added (rests on Bagent at replacement level + GB's injury
count), TEN +7.5 -> +6.5, MIN -1.5 -> -2.5, NYG +3.5 now -110, SEA -172,
BAL +3.5 unchanged. Straight-up pick flipped in NYG@WAS (WAS -> NYG, 50.7%,
WAS injuries). Excel had the Week 5 workbook open; its only unsaved changes
were Game Detail dropdown flips (AutoRecover .xlsb decoded with pyxlsb and
diffed against disk), so his 13:07 save was backed up to
`output/superseded/NFL_Model_2026_Week05_saved_2026-10-09_1307.xlsx` and the
workbook rebuilt; 10 tracker rows carried. Weeks 1-4 checksums unchanged.

**2026-10-12 (Mon, before MNF): Bet Tracker charts; his K6 is pinned.** He
added cells of his own above the tracker table (J5:K6, a Kalshi price ->
sportsbook odds converter with the formula in K6; M4:M5, total staked) and
asked that K6 be kept, plus charts beside the table ("I can always delete what
I want"). The tracker is carried as the sheet itself, so his cells already
survive every build; `tests/test_tracker_carry.py` now pins K6, and
`_sheet_tracker` (the rebuild-from-CSV fallback) writes the same cells.

Four charts sit at R12 on the Bet Tracker, below the frozen rows: profit bet by
bet (title is a cell, so it shows the live bankroll), profit by week, win % vs
the break-even his odds needed, profit by bet type. They read a new hidden
model sheet, **Chart Data** (formulas over tracker rows 12-500, so they move as
he logs bets; a row that is not a graded bet repeats the point before it, so
nothing is ever blank). `excel._tracker_charts`: a tracker that has never had
them gets all four; after that only the ones still on his sheet are redrawn,
where and at the size he left them, so **a chart he deleted stays deleted**.
The model's charts are redrawn every build, never carried: openpyxl does not
read a chart back whole.

Learned by rendering in real Excel (it can be scripted: `osascript`, a scratch
copy opened with `open -g`, "save as PDF", then `close ... saving no`; put the
scratch file under `~/Library/Containers/com.microsoft.Excel/Data/` so Excel
can write beside it, and never touch a workbook he has open):
a legend needs `overlay = False` or it sits on the axis labels; `varyColors =
False` on a scatter chart puts the dots off the line in a PDF/print; a balance
axis would start at $0 and flatten the line, hence profit; openpyxl drops
`roundedCorners` on a second load/save.

The Week 5 workbook was NOT re-run (the unstarted MNF game would have been
re-priced). The charts were added to his 10:28 save in place with one openpyxl
pass. **A plain openpyxl load/save of a workbook Excel has saved drops the Game
Detail dropdown** (Excel moves a cross-sheet list into its x14 block); it was
read from the raw XML and put back, and a cell-for-cell diff (44,287 cells,
styles, formats, dropdowns) came out clean. His save is at
`output/superseded/NFL_Model_2026_Week05_saved_2026-10-12_1028.xlsx`. A dry run
of Week 6 in a scratch copy of the repo carried K6 and all four charts.
His tracker through Sunday: 16 bets, 11-5, +$25.02. His `MIN @ NO` row has the
line typed as 1.5 (at -121 it is almost certainly MIN -1.5), which files it
under spread underdogs; he was told.

**Same afternoon: the charts left on his sheet get updated every week** (his
ask, now a standing rule in §7). He deleted "profit by bet type" and kept three:
bankroll, profit by week, win % vs break-even. The run now prints what it did,
`bet tracker charts: 3 redrawn (...); deleted, left off: profit by bet type`.
When he asked, the deletion was only in the open Excel window (3 charts there,
4 on disk, `saved` false), so a build before he presses Cmd+S would put the
fourth back; he was told to save.

**2026-10-13 (Tue): his tracker cells and formulas, every week.** His ask:
"keep the items like K6 and M5 on the Bet Tracker sheet the same, copy over the
formulas I have added as well, and update the graphs if needed; that should be
part of the weekly run." The carry already did this (the sheet itself comes
through); the run now proves it. After saving, `build_workbook` reads his sheet
back from the new file and compares every cell with the sheet it loaded
(`betlog.tracker_changes`, `excel._tracker_carry_line`), printing
`bet tracker cells: 2140 carried exactly as saved (1968 formulas); formulas you
added: M5, K6`, or a `WARNING` naming each cell that differs. "Formulas you
added" is any formula outside the model's own (`_TRACKER_MODEL_SUMMARY` and
table columns J, K, N, O), so one he adds later is named without a code change.
Rule in section 7. Checked against real Excel: the 380 cells Excel showed in
A1:P60 of his open window matched both his saved file and a scratch Week 6 dry
run, formula for formula. He saved Week 5 at 11:04 with "profit by bet type"
deleted (3 charts on disk now).

**Same day: Week 5 locked, Week 6 built.** Week 5: 8-6 straight up plus a tie
(NYG @ WAS 27-27), model bets 4-3, his own 5-2 (season 11-5, +$25.02). Season
48-31 SU; model error 9.86 vs closing line 9.78. CLV to date: spreads +0.30
pts on 15, moneylines +0.2% on 17, i.e. about zero. Trend fixes unchanged; no
factor near its 48-game verdict. Two review/run defects fixed: the process
check called the tie "a played game with no archived pick" (it now compares
against the archive), and QB RISK listed "Michael Penix Jr." as Penix's own
backup at a 4.0-pt swing (names are compared without suffixes now; the real
ATL alternative is Tua Tagovailoa, 1.0 pt). His `MIN @ NO` tracker row still
has the line typed as 1.5, which shows his CLV on it as +4.0 instead of +1.0.

Week 6 built Tuesday with `--qb TB="Jalon Daniels"` (Bowles 10/9: "we plan on
starting Jalon Daniels against the Steelers"; he is unrated, so replacement
level -2.39). **Re-pass it on every re-run.** Card, $5 each: PHI -1.5, JAX
-2.5, NYG -104, DEN +3 (TNF), IND -340, BAL -225, GB -110; TB +2.5 qualified
and was left off. Unconfirmed, left on the depth chart, check before Sunday:
CHI (Caleb Williams expected back at practice Wednesday; if Bagent starts the
line moves 2.8 pts and ATL +3.5 likely becomes a bet), BAL (Lamar "real chance"
to return; the model rates Huntley within 0.1 pt of him, the market does not),
ATL (Penix questionable, ribs). Tracker carried: 2,140 cells exact, K6 and M5
named, 3 charts redrawn. Weeks 1-5 workbooks' checksums unchanged.

**2026-10-14 (Wed 10:20 ET): Week 6 re-priced ("confirm week 6 picks").**
Re-run with `--refresh --qb TB="Jalon Daniels"` (Garafolo Wed: odds are
Daniels one more week; nflverse's depth chart now lists Mayfield, ignore it).
Excel had nothing open and the Week 6 file was unsaved since Tuesday's build,
so it was rebuilt in place; tracker 2,140 cells exact, K6/M5 named, 3 charts
redrawn; Weeks 1-5 checksums unchanged. Card, $5 each: PHI -1.5, JAX -2.5,
IND -330, GB -116 (unchanged); DEN +3 -> **DEN +2.5 -104** (TNF); NYG -104 ML
-> **NYG +1.5 -122**; **BAL -225 dropped** (Lamar hope moved it to -250);
**ATL +3 -105 added**. TB +2.5 still qualified, left off. New bets were
appended to `week06_first_leans.csv` (Tuesday's rows kept).

**Flagged, not changed: the 3-pt trend-fix trigger is a cliff.** The
"far from the line" fix pulls 1.5 only when the FROZEN projection is 3+ off,
so a game at 3.1 off shows 1.6 of edge and one at 2.9 shows 2.9. Both of
today's new/stronger bets came from crossing it: ATL (line 3.5 -> 3 toward
the model, frozen gap 3.25 -> 2.66, pull switched off, final edge 1.4 -> 2.8)
and NYG (frozen view of NYG fell ~0.5, gap 3.35 -> 2.88, edge 2.4 -> 3.5).
A smooth pull has not been tested on the hold-out; his call whether to.
Still open for the Sunday roster run: CHI (Williams Q hamstring, model assumes
him; Bagent = 2.8 pt toward ATL), ATL (Penix Q ribs; Tua 1.0 pt), BAL (Lamar Q
ankle; Huntley 0.1 pt in the model).

**Same day: "Penix rated better than Williams?"** Yes in the QB column
(Penix +1.57, Williams +0.40), but that column is the QB's share of a JOINT
team+QB fit, not a QB ranking. ATL has many non-Penix games to compare
(Cousins 22 starts 2024-25 at +0.26, Cooper Rush 2026 at -2.15); Williams
started 38 of CHI's last 43, so ridge puts most of his value in CHI's team
rating (+1.34 vs ATL -1.72). Team+QB: CHI +1.74, ATL -0.15. **Found while
checking, untested:** the market prior (54% weight in Week 6) is backed out of
2026 spreads with no QB term, so it already contains each team's QBs, and the
model adds the QB on top. Backing the model's QB values out of those lines
first moves CHI@ATL 0.33 toward CHI (ATL +3 edge 2.8 -> ~2.5, still above 1.5)
and some teams up to 0.76 (ARI +0.76, MIA +0.73, TEN +0.70, TB +0.64 -- teams
that started backups). Needs a 2021-25 hold-out test before any change; his
call. Script: scratch only, logic is in this paragraph.

**2026-10-17 (Sat 13:10 ET): Week 6 roster run** (he asked Saturday, not
Sunday). News: Hurts OUT (calf blood clot, found moving on a Wed ultrasound),
Tanner McKee starts; Lamar OUT Fri, Huntley starts; Mayfield OUT, Jalon Daniels
starts (Bowles Fri); Winston starts for NYG; Penix cleared, no designation;
**Caleb Williams Questionable** (full practice all week, Bears decide by Sun
11:30 ET; if Bagent starts, 2.8 pts toward ATL, re-run with
`--qb CHI="Tyson Bagent"`). Run: `--refresh --qb TB="Jalon Daniels" --qb
PHI="Tanner McKee" --qb BAL="Tyler Huntley"`. **Re-pass all three.** McKee is
unrated (replacement level -2.39), same as Daniels. Excel had Week 6 open with
an unsaved tracker row (his TNF bet, SEA @ DEN DEN +3.5 -121 $5 W) and J6
0.53 -> 0.547; he saved at 13:06 and closed it, the save matched the open
window cell for cell, backed up to
`output/superseded/NFL_Model_2026_Week06_saved_2026-10-17_1306.xlsx`. Tracker
2,149 cells exact, K6/M5 named, 3 charts redrawn; Weeks 1-5 checksums
unchanged. Card vs Wednesday: **PHI -1.5 -> PHI +3.5 -122** (line moved 5,
CAR -3.5; straight-up pick flipped to CAR 53.5%; the bet rests on McKee at
replacement level and the <8-starts watch item says such QBs run about 1 pt
worse than the model), **ATL +3 dropped** (line now +1.5, still qualifies,
ranked 9th), **BUF -245 added**; NYG +1.5 -122, JAX -2.5 -110, IND -340,
GB -118 unchanged; DEN +2.5 carried (TNF). Straight-up flip: CHI -> ATL
(53.5%). CLV note: first_leans keys on game+market+team, so Wednesday's
PHI -1.5 stays the number CLV is measured from for PHI spread (about -5 pts
against the model from the Hurts news). Left off: KC -7.5, ATL +1.5, BAL -3.

**2026-10-19 (Mon, before MNF WAS @ SF): Week 6 graded, NOT locked.** The
review was run with `lock_week` stubbed out (meta.json unchanged), so **lock
it Wednesday with `review_week.py --week 6`**, which also records the closes.
Sunday: 6-7 SU (expected 8.7, band 5.4-11.9, noise); FanDuel's closing
favorites went 7-6. Card 3-4 (DEN +2.5, BUF, GB won; NYG +1.5, PHI +3.5,
JAX -2.5, IND -340 lost), -$8.91 at $5. No input errors (Williams, McKee,
Huntley, Daniels all correct). Provisional CLV of the Saturday card vs
FanDuel's close: spreads +0.5 PHI, 0 on the rest; moneylines IND -340 ->
-290 (-2.9%), GB -118 -> -104 (-3.1%), BUF even. Dropped bets closed worse
(BAL -225 -> -174, lost; ATL +3 -> +1.5, lost). Season: 54-38 SU, model
error 9.55 vs close 9.39, card 19-18-1. **He left the model's IND -340 out
of his tracker on purpose** (it lost); it stays in the archive/Bet Log as a
model bet. NYG +1.5 is not in his tracker either (unknown if he bet it).
His tracker: Week 6 3-2 +$0.63, season 14-7 +$25.66. His `HOU @ JAX` row has
Line Taken 2.5 for JAX (the favorite, so -2.5): result unaffected, but CLV
shows +5.0 instead of 0.0; with the `MIN @ NO` typo his season spread CLV
reads +1.05 on 11 when it is about +0.32. He was told.

**2026-10-21 (Wed): Week 6 locked, Week 7 built.** Week 6 final 7-7 SU
(MNF WAS @ SF right; expected 9.5, band 6.2-12.8, noise), card 3-4, no input
errors. Closes recorded (14 FanDuel). Season 55-38 SU, model error 9.49 vs
close 9.31. CLV from first-published numbers: spreads +0.10 pts on 20,
moneylines -0.3% on 22 -- the market is not being beaten. His tracker:
14-7 +$25.66 (no MNF bet logged). Trend fixes unchanged (statuses and the
one live pull identical; win-% calibration slope re-estimated 1.492 ->
1.485). Factor card at 45 games: **EPA/play t = -1.7 (helped 14, hurt 21)**;
the 48-game verdict lands after Week 7 -- if t <= -2 it is flagged for a
re-fit/replacement in factor_lab.py, never an auto re-weight.

Week 7 run with `--refresh --qb TB="Jalon Daniels" --qb BAL="Tyler Huntley"
--qb PHI="Tanner McKee"`. **Re-pass all three.** Hurts out for the season
(DVT/pulmonary emboli, IR). Mayfield Q: threw Mon, thumb swelled; Bowles
game-planning for Daniels (Mayfield = 2.4 pts to TB if he plays). Lamar Q:
no practice since 10/4 (Huntley = Lamar within 0.3 pt in the model; the
market will move more). SEA = Darnold (Macdonald rejected benching him for
Lock; nflverse game file still says Lock, ignore it). Replacement level is
now -2.86 (was -2.39). Byes: BUF, JAX, LAC, WAS. TNF NE @ CHI = no bet.
PIT @ NO is a 9:30 ET international game. Card, $5 each, exactly 7
qualified: DEN -4.5, PHI +4.5 (MNF; rests on McKee at replacement level),
CIN +2.5 -100, PIT -174, CLE -126, MIA +205, DET -172. Tracker 2,183 cells
exact, K6/M5 named, 3 charts redrawn; Weeks 1-6 checksums unchanged.
Sunday roster run: verify TB (Mayfield) and BAL (Lamar).

**2026-10-25 (Sun 12:50 ET): Week 7 roster run, SCRATCH COPY ONLY.** Lamar
OUT (Huntley), Mayfield PLAYED (depth chart had him; the TB="Jalon Daniels"
override was dropped). Re-pass only `--qb BAL="Tyler Huntley" --qb
PHI="Tanner McKee"`. Sunday card: DEN -4.5, PHI +4.5 (MNF), DET -190, CLE -130,
PIT (carried); CIN +2.5 and MIA +205 dropped. His open workbook had unsaved
tracker rows, so the real rebuild waited -- and never happened: the archive
(`week07_*.csv`) is still the WEDNESDAY build, and that is what Week 7 grades.

**2026-10-26 (Mon, before MNF DAL @ PHI): Week 7 graded, NOT locked** (review
run with `lock_week` stubbed; lock Wednesday with `review_week.py --week 7`,
which also records the closes). Straight up 8-5 (expected 8.4, noise); every
pick was the market favorite except CIN @ BAL (picked BAL, lost). Wednesday
card 6-0 with PHI +4.5 pending (DEN -4.5, CIN +2.5, PIT -174, CLE -126,
MIA +205, DET -172; +$29.55 at $5). Expected about 3.3 wins by its own
numbers; a sweep was ~2.5% (model) / ~1.5% (market). Model error 9.95 vs close
9.96 that week (Week 6: 7.37 vs 6.71); season 9.54 vs 9.41. Provisional CLV
from first-published numbers: DEN 0, CIN +5.5 pts (Lamar news; the model's own
number was more pro-BAL than the close), PIT -1.1%, CLE +0.8%, MIA +4.8%, DET
+4.0%; season spreads +0.34 pts on 22, moneylines +0.1% on 26. By EPA the
Week 7 card "deserved" 5-1 (DET out-played) and Week 6 4-3; three Week 7 wins
were by exactly 3. Nothing in the code or config changed between the Week 6
and Week 7 cards (only trends.json, statuses identical). Factor card at 58
games: EPA/play t -1.7 (46 games), not flagged. Process: NYG started J.J.
McCarthy (model used Winston from the depth chart; 0.1-pt swing, no bet
affected); TB Daniels->Mayfield was caught only in the scratch Sunday run.
The review flagged "Michael Penix" vs "Michael Penix Jr." as a wrong QB; fixed
(process check compares `teamstats.normalize_name`). His tracker: Week 7 6-0
+$25.46, season 20-7 +$51.13. His CIN +2.5 was bought at -199 on Sunday (alt
line; the market was CIN -3), so the tracker's +5.5 CLV on it overstates it;
the real value is about zero.
MNF re-priced in a scratch copy (`--refresh`, same two overrides): unchanged,
PHI +4.5 -112 at FanDuel, model DAL by 2.5, edge 2.0 (needs 1.5), cover 58.4%.
Injuries counted (PHI: D. Smith, Wicks, N. Smith, Carter out, Dickerson IR;
DAL: Winters, Turpin out, J. Thompson IR; net 0.2 to DAL). It stops qualifying
at +4 (edge 1.48) or if Barkley (Q, 0.74 starter-eq = 0.5 pt) is ruled out
(edge ~1.46). Rests on McKee at replacement level; the <8-starts watch item
(-0.86 if applied) would also drop it below 1.5. Real Week 7 workbook NOT
rebuilt (MNF pick unchanged); his 11:00 save is untouched.

**2026-10-27 (Tue 21:20 ET): Week 7 locked** (he asked to grade only, no Week 8
picks). MNF DAL 38-21 at PHI: straight-up pick DAL right, PHI +4.5 lost. Final
9-5 SU (expected 8.9, noise); card 6-1 (+$24.55 at $5). Closes recorded (14
FanDuel). Season 64-43 SU (59.8%), model error 9.59 vs close 9.41 (market
sharper by 0.19). CLV from first-published numbers: spreads +0.33 pts on 23,
moneylines +0.1% on 26 -- 49 bets, the 40-50 mark the plan set. The two big
spread moves were QB news (CIN +5.5 Lamar out, PHI -4.5 Hurts out) and
roughly cancel; the rest are mostly 0 or +1. Moneylines are flat: no edge
shown yet. His tracker (saved 21:16, Excel closed): Week 7 6-1, season 20-8
+$46.13. Process check: TB (Daniels assumed, Mayfield started; caught only in
the scratch Sunday run) and NYG (Winston vs McCarthy). Trend check: the one
live fix unchanged; divisional underdogs moved absorbed -> watching (2021+
MAE no longer improves; neither status is applied). Factor card at 59 games:
EPA/play t -1.7 on 47, not flagged. Weeks 1-7 workbook checksums unchanged.

**2026-10-29 (Thu): expert review round 1, fixes shipped.** He asked for a
grade on seven live weeks ("whats working and what hasnt and why, lets do more
of whats working and fix what isnt"). Goals, in order: straight-up accuracy,
then edge bets that are "great and not lucky". Locked, bug-checked only:
FanDuel, spreads + moneylines, $5 a bet, 4-7 bets a week. A fresh grader scored
round 1 at 40/100 (`.expert-review/`, untracked: rubric v2, brief, grades).
He approved every fix except "pick the favorite in close games" ("basic and
boring") and game-day QB guardrails (his own check). Branch
`expert-review/round-1`, merged to main:
- Replay = live: the market prior uses the week being predicted in both
  (`fit_market_ratings`). One canonical replay, `src/nflmodel/replay.py` (fit
  2013-20, score 2021-25), behind `scripts/replay_deployed.py`, `ablation.py`
  and `refit_factors.py`. Quote these numbers, never a lab's own rebuild.
- EPA/play factor DROPPED (Brier worse, t +2.0); `config.FACTORS` = injuries
  0.637, rest 0.048. Self-tune OFF (neutral once EPA was out).
- Win-% slope fit on the model as it runs (trends adds the factors): 1.483 ->
  1.402. Caches rebuilt with the live loader; trend gate still holds.
- `review_week.py`: VS THE FAVORITE and GOOD OR LUCKY? (`scorecard.py`), graded
  from the archive, never his tracker (his call). Moneyline CLV de-vigged at
  both ends; non-FanDuel closes flagged.
- Bug in a locked part: a spread price borrowed from the stored line was
  labeled FanDuel's; now labeled and warned.
- His Bet Tracker: blank Closing Line/Odds cells filled from FanDuel's recorded
  close (his ask), listed on their own line after `bet tracker cells:`.
- Workbook: 'Bet Wins %' is the bet's own chance (was the game's win %); Bet
  Log adds Favorite, Favorite Right?, Model Bet Value @ Close; Reference
  verdict rewritten. The 2 test_history failures fixed; 236 tests.
Deployed model on 2021-25: SU 65.99% vs taking the favorite 66.48%; error
9.876 vs line 9.762; card ROI +0.7% (SE 3.6%), model said 61.5%, won 55.6%.
Live Weeks 1-7: 64-42 vs favorite 67-39; card 25-19-1 but value at the price
taken -2.8% a bet (+/- 1.5%). The card-ranking blend he asked about was
tested and not switched (IMPROVEMENT.md).

**Past weeks' workbooks are his.** 2026-10-07 he asked that the Week 4
workbook be left exactly as he left it. Never delete, regenerate, re-save or
"redo" a past week's `output/NFL_Model_*_WeekNN.xlsx`. Reading it read-only
(review, tracker carry) is fine. That day Excel had it open with AutoRecover
copies from 10/5 and the disk copy was still the 10/4 12:18 build, so his
edits were unsaved. The Week 5 tracker carries whatever is ON DISK, so after he
saves, re-run Week 5 to carry his edits forward.

**Jameson's working preferences:** he wants picks presented as every game's
straight-up winner ranked by confidence, plus the bets. "Redo the week N
picks" = delete that week's three files in `output/` and regenerate (the
CURRENT week only, before kickoff; never a past week he has edited). He wants
everything committed AND pushed to GitHub so the next session has it. He does
NOT want the model to overreact to single games.

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

**2026-10-29, the model as it runs** (`scripts/replay_deployed.py`, one
canonical replay, fit 2013-20): straight up 65.99% vs taking the favorite
66.48% (t −0.7), MAE 9.876 vs 9.762, Brier 0.2156 vs 0.2115, weekly card 649
bets at closing prices ROI +0.7% (SE 3.6%). Still no edge; quote these.

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

The miss-trend checker (`trends.py`) is LIVE since 2026-09-26. The EPA
per-team nudge ran 2026-09-25 to 10-27 and is OFF since 2026-10-29 (neutral on
the canonical replay). Weekly loop:
`review_week.py --week N` → `miss_report.py` → `factor_check.py` → commit
`data/trends.json` → `run_week.py`. What follows is why the ORIGINAL design failed and must not be
brought back.

Jameson asked for continuous week-to-week self-improvement (2026-09-22). The
first version — nudge each team by its raw SCORE residual — was built,
measured, and **rejected**: hold-out MAE goes 10.079 frozen -> 11.065 at full
strength, degrading monotonically, and value picks get worse at every setting.
`alpha=0.1` is a no-op (paired t=-0.08, p=0.93). It fails on the tuning
seasons too. Six signals x 180 configs were then tested
(`scripts/adjust_lab.py`): only EPA margin helps, and only with a per-game
ceiling (0.5 pt: 27/27 variants improve; 2 pt: 1/27). The size of the move,
not the learning rate, is what hurts.

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
| Score-residual weekly self-tune | MAE 10.079 → 11.065 at full strength | rejected; replaced by EPA version (0.5 pt cap) |
| Weather × team style (pass-heavy offense in rain/wind) | 2016-20 slope +13 (opposite sign), 2021-25 −1.9 (t −0.3) | rejected 2026-09-25 |
| "Skip value bets in bad weather" | 53.6% (2016-20) vs 42.3% (2021-25) | does not replicate |
| Inexperienced QB (<8 career starts) as a fix | −1.0 / −0.9 once starts are counted correctly | watch list only |

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
.venv/bin/python -W ignore -m pytest tests/ -q                 # 236 tests
.venv/bin/python -W ignore scripts/replay_deployed.py          # the model as it runs, on 2021-25
.venv/bin/python -W ignore scripts/ablation.py                 # what each piece is worth
.venv/bin/python -W ignore scripts/refit_factors.py            # re-weight the game factors
.venv/bin/python -W ignore scripts/miss_report.py              # WEEKLY: trend check -> data/trends.json (commit it)
.venv/bin/python -W ignore scripts/miss_report.py --no-save    # look without changing the model
.venv/bin/python -W ignore scripts/build_base_projections.py   # rebuild cache the trend check reads (~1 min)
.venv/bin/python -W ignore scripts/adjust_lab.py               # which self-tune signals help (EPA only)
.venv/bin/python -W ignore scripts/weather_style_test.py       # weather x team style (rejected)
.venv/bin/python -W ignore scripts/run_week.py --no-weather    # skip the Open-Meteo forecast
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
  See the decision gate in `OPERATING.md`. (He moved to decision mode
  2026-09-14 anyway; he actually bets small, $5 a lean in Week 2.)
- **One book: FanDuel** (2026-09-25). Do not show other books.
- **Self-tune OFF** (2026-10-29, expert review; he approved). It ran on
  everything 09-25 to 10-27; neutral once the EPA factor was dropped.
- **Trend fixes ON**: change the model for consistent miss-reasons only —
  "don't make the Falcons #1 because they looked good once." Every new
  statistical rule gets tried to be broken before it ships (he approved an
  adversarial audit; it caught a fix-applied-twice bug and set-level
  confirmation).
- **Longshot cap +250** on moneyline underdogs and win-% recalibration.
- **Weekly card: at most 7 bets, at least 4** (2026-10-07), ranked by chance
  the bet wins. Grade his bets from HIS tracker lines (line taken), never the
  model's line. **Grade the MODEL from its own card** (archive / Bet Log),
  never his tracker (2026-10-29). The ranking stays "chance the bet wins": a
  model/market blend was tested and did not replicate (IMPROVEMENT.md).
- **Declined 2026-10-29:** picking the favorite in close games ("basic and
  boring") and game-day injury/QB guardrails (his own check before betting).
- **Bet Tracker closes** (2026-10-29): the build fills FanDuel's recorded close
  into Closing Line / Closing Odds cells he left BLANK, never one he typed,
  and lists them on their own line. Not a carry error.
- **Weather**: shown and fed to the trend checker; no hand-set adjustment.
- **Bet Tracker cells and formulas: carried exactly, every week**
  (2026-10-13). K6 (his Kalshi price -> sportsbook odds converter), M5 (total
  staked) and any formula or cell he adds to the sheet reach each new week's
  workbook as he left them: never retyped, "tidied", moved or re-ranged (his M5
  stops at row 300; leave it). Every week, read the run's `bet tracker cells:`
  line. It should say "carried exactly as saved" and list his formulas under
  "formulas you added". A `WARNING: the Bet Tracker did NOT carry cleanly` means
  the build changed his sheet: stop, do not hand him that workbook, fix the
  build. The run reads the SAVED file, so remind him to Cmd+S after adding
  anything.
- **Bet Tracker charts: every week, update the ones still on his sheet**
  (2026-10-12). Each weekly build redraws whichever of the model's charts he
  has kept, over all his logged bets, where and at the size he left them. Never
  put back one he deleted, never drop one he kept. Every week, read the run's
  `bet tracker charts:` line and check it against his last save; it should name
  exactly the charts he kept. If it does not (a count of 0, or one "left off"
  that he did not delete), fix that before handing him the workbook. Renaming
  a chart's first series orphans his copy of it (`excel._chart_identity`), so
  do not rename one without carrying the old name. He can ask for a deleted
  chart back, or a new one, at any time.

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

- **2026-09-25: FanDuel-only mode supersedes the paragraph below** for live
  runs (`MY_BOOK`). The shopping code is kept for `MY_BOOK = None`.
- "Model far from the line" is a discrete fix (applies at |model − line| ≥ 3,
  1.5-pt pull), so a 2.9-pt disagreement is untouched while 3.0 becomes 1.5.
  Tested in that form; a continuous version would converge on the line
  itself (the known no-edge result) and remove nearly every bet.
- Forecast wind is Open-Meteo 10 m open-field wind; historical wind is the
  gamebook's stadium reading. Same 15 mph threshold for both; forecast may
  run a little high. Retractable roofs never count as "outdoors" for flags.
- The trend check's history is the frozen walk-forward backtest plus the
  live game factors (since 2026-10-29, `replay.history_factor_points`).
  Rebuild base projections if the ratings engine itself changes.
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
- **Superseded:** the non-QB injuries factor is LIVE (`config.FACTORS`,
  0.637 pt per starter out; t −2.6 on error in the canonical replay). Older
  note: the **injury-burden term ships at zero** and the roster feed is reporting
  only. See `scripts/measure_injuries.py`: pooled it looks like the best factor
  in the repo, but it fails season-clustering, loses money in six of twelve
  seasons, and stale absences carry more signal than fresh ones — backwards for
  an injury story, and a sign it proxies team quality. Re-test it
  prospectively against CLV rather than re-running the pooled regression.
- `HFA_TEAM_DELTAS` and several config knobs are declared but unused.
- **DONE 2026-10-29** (rebuilt, 2021-25 base MAE 10.079 -> 10.026, trend
  gate re-checked). **Lab caches predate the live loader.** `data/cache/dataset_2010_2025.parquet`
  (and so `base_projections_2013_2025.parquet`, which the trend checker and
  factor lab read) was built before QB-name canonicalization and before the
  2026-09-30 stale-QB fix: 16 spelling-only rows + 42 wrong starters vs what
  `load_games()` now returns. Effect on hold-out MAE is ~0.01 pt. Rebuild both
  (`build_dataset` -> `build_base_projections.py`) in a quiet week, then re-run
  `miss_report.py` and check the trend gate still holds before committing.
