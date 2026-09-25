# Weekly operating procedure

> Context for a fresh Claude session lives in `CLAUDE.md` (auto-loaded).
> Technical detail and validation results are in `README.md`.

The model ships in advisory mode because the hold-out backtest found no edge
against closing lines. So the first several weeks are a **measurement
exercise**, not a betting operation. This document is the procedure.

## The weekly loop

### Step 0, before anything else — grade last week

```bash
.venv/bin/python -W ignore scripts/review_week.py
```

Do this first, every week, before you look at a new slate. It scores last
week's picks **exactly as they were published**, from the tracked `picks/`
archive — never from a rebuild. That distinction is the whole point: rebuilding
Week 3's picks in December scores them against lines the model never saw and a
ratings fit trained on the games being predicted. The rebuilt file would look
like a forecast and would actually be a memory.

The review prints four things:

| section | what it answers |
|---|---|
| Straight up | how many winners, against the number an unchanged model expects |
| Calibration by tier | does "60%" actually mean 60%? |
| Leans | the record of the picks that would have cost money |
| **Process check** | did the model have the wrong quarterback, or miss a game? |

Reading it takes a minute. Then it locks the week, so those picks can never be
rewritten.

### Step 0a — grade the model itself

```bash
.venv/bin/python -W ignore scripts/grade.py --save
```

`review_week.py` scores last week. This scores **every prediction the model
has made this season**, bet or no bet, against the only benchmark that
matters: the closing line's error on the same games. It tracks straight-up
record, average error in points, directional bias, calibration by tier, and
the value-pick record, accumulating into `data/scorecard.json`.

Once a month, or after any week that looks strange, run the error hunt:

```bash
.venv/bin/python -W ignore scripts/grade.py --diagnose --scope all
```

That searches 2010-2025 walk-forward predictions for segments where the model
is systematically biased, with a false-discovery-rate correction so it cannot
manufacture a finding. Anything it flags is a **candidate**, and the protocol
for promoting a candidate into an actual change is `IMPROVEMENT.md`. Read that
before touching a parameter.

### Step 0b — decide whether to change anything

Almost always the answer is no, and the script says so explicitly. This is the
part that protects the model from you:

> A 16-game slate is far too small to tell you anything. A good model goes
> 5-11 straight up regularly. Tuning after a bad week fits noise, and you will
> do it in the direction that felt worst — which is how a working model gets
> destroyed one reasonable-sounding adjustment at a time.

So every number is printed next to the range an unchanged model produces.
**Inside the band means change nothing.** That is a finding, not an evasion.

What *does* justify a change:

- **A process error.** The model assumed Geno Smith and Justin Fields started.
  A line was stale. A game was missing from the slate. These are defects
  whether or not the pick won, and they are worth fixing the same day. The
  process check hunts for them separately from the scoreboard for exactly this
  reason.
- **A result far outside the band, twice.** Once in twenty weeks a 95% band is
  breached by chance. Twice in a short span is worth investigating — and the
  first thing to suspect is a leak or a bad input, not the ratings.
- **Never a losing week on its own.** At a true 53% ATS rate it takes roughly
  1,100 bets for the win rate to separate from 50%. At ~9 leans a week that is
  over six seasons. Weekly records will never settle this. CLV will, in about
  six weeks.

If you want to change a rating, a threshold, or a weight, the honest route is
`scripts/run_backtest.py` on held-out seasons — not a reaction to Sunday.

### Then — build the slate

```bash
.venv/bin/python scripts/run_week.py            # next unplayed week
.venv/bin/python scripts/run_week.py --week 5   # a specific week
```

Tuesday/Wednesday is deliberate. Lines post Sunday night for the following
week and are softest early; that gap is where closing line value comes from.
Waiting until Sunday morning means betting into a number the market has
already sharpened.

The run now pulls **live prices from six books** and uses their median as the
market number, instead of nflverse's single stored DraftKings line. Two things
come out of that:

* a **WHERE TO BET IT** table naming the book with the best number on each
  recommended bet. This is worth more than the ratings are — the model has been
  measured at zero incremental signal, the price you get filled at has not.
* a warning when the stored line and the live consensus disagree. On the first
  live run (2026 Week 3) they disagreed on 3 of 16 games, one by 1.5 points.

`--no-live-odds` falls back to the stored line, and so does a dead feed.

Also read the **QB RISK** table before betting. It lists only the teams whose
starter is genuinely in doubt, priced in points, so the one or two worth
checking by hand are obvious. Atlanta in Week 2 — projected +0.2, actual −31 —
was a quarterback error, not a ratings error, and it is the largest single
miss of the season.

Starters resolve automatically now, from nflverse's daily depth-chart pull.
The run prints which snapshot it used and warns whenever the depth chart and
the game file name different quarterbacks. To see all 32 and where each came
from:

```bash
.venv/bin/python scripts/run_week.py --starters
```

Override anything that is wrong — a Sunday-morning report beats every feed:

```bash
.venv/bin/python scripts/run_week.py --qb LV="Kenny Pickett" --qb NYJ="..."
```

Check this every week. The quarterback is worth up to ~6 points of margin,
more than home field, and it is the one input most likely to be stale.

### Same day — log what you would take

The workbook's **Picks** tab lists every game as a straight-up winner ranked
by confidence, with the assumed starting quarterbacks underneath. Read it as
predictions, not as bets — the most confident pick on the board is usually the
worst bet on it, because the market has priced it too. Where the model
disagrees with the *price* is the **Weekly Slate** tab, and **Model Picks %**
puts the model's number next to the de-vigged market number side by side.

Two tabs are worth a minute before you log anything:

- **Team Stats** — check the starting quarterback the model assumed, and the
  injured list. A wrong quarterback is the single most expensive input error
  in this system, worth up to ~6 points of margin. If it is wrong, re-run with
  `--qb TEAM="Name"` before doing anything else.
- **Game Detail** — pick the game from the dropdown and read what is actually
  driving the number. Early in the season most of a rating is the market's own
  preseason opinion (the sheet shows the weight), which means the model is
  largely agreeing with the price in an expensive way.

Open `output/NFL_Model_<season>_Week<NN>.xlsx`, go to **Bet Tracker**, and
fill columns A-H for each lean you would act on:

| column | what goes in it |
|---|---|
| Date, Week, Matchup | the game |
| Market | `SPREAD` or `MONEYLINE` (dropdown) |
| Bet Side | e.g. `MIA +3.5` |
| **Line Taken** | the spread number *you* saw, from your side |
| Odds | the price you saw, e.g. `-108` |
| Stake | what you would have risked |

Log these **even when betting nothing**. That is the entire point — the record
is what answers the open question.

### Sunday morning — capture the close

Re-run the same command. It rebuilds the workbook, preserves everything you
entered, and refreshes the slate against current numbers. Fill in **Closing
Line** and **Closing Odds** for each logged bet. CLV computes itself.

### Monday — settle

Enter W/L/Push in the Result column. P&L, running bankroll, ROI and CLV all
update from formulas.

Your entries survive the next run. The tracker is merged across every weekly
workbook in `output/` and the CSV mirror, most recently edited file winning
per bet, so settling Week 3 on Monday and building Week 4 on Tuesday keeps
everything. (It did not always: the first version only read the *current*
week's file and fell back to a CSV written at the end of the previous run,
which silently dropped anything typed in between.)

### The Bet Log tab

Every pick and lean the model has ever published, graded from the `picks/`
archive exactly as published. The top of the tab shows just two numbers, at
Jameson's request (2026-09-16): how often the model's pick won the game, and
how often its value picks (bets against its own pick) won. Calibration by
confidence tier is still printed by `review_week.py`. A rebuilt week never enters this history; `run_week.py` refuses
to archive a week that has already kicked off, because picks generated after
the fact were never published and never risked anything.

## What we are actually measuring

The backtest compared the model against **closing** lines and it lost. But you
would be betting **Tuesday** numbers, and whether the model beats those is
untested — free historical opening lines only run through 2021, and the
open-to-close accuracy gap is just 0.14 points against a 0.39 point deficit,
so it is unlikely to rescue anything.

CLV settles it cheaply and in weeks rather than seasons.

## The decision gate

After roughly **40-50 logged picks** (about six weeks), look at Avg CLV on the
tracker:

- **Consistently positive** → the model finds something at the numbers you can
  actually get. Consider real money, starting small. Set `ADVISORY_MODE = False`
  in `src/nflmodel/config.py`; staking is half-Kelly, capped at 2.5% per bet and
  10% per week.
- **Flat or negative** → it does not, the hold-out was right, and the honest
  move is to stop or rebuild the approach rather than keep paying the vig.

Judge by CLV first and P&L much later. A 53% model needs several hundred bets
before its win rate separates from noise.

## The picks archive

`picks/<season>/week<NN>_*.csv` is written automatically by `run_week.py` and
is **tracked in git**. Three files per week:

| file | contents |
|---|---|
| `week<NN>_picks.csv` | the straight-up ranking, as published |
| `week<NN>_leans.csv` | where the model disagreed with a price |
| `week<NN>_meta.json` | when it ran, which quarterbacks it assumed, lock state |

Re-running a week before kickoff updates the archive — lines move and starters
change, and that is still a forecast. Two things stop it being rewritten after
the fact: once `review_week.py` has graded a week it sets `locked: true`, and
`run_week.py` refuses to archive any week whose first game has already kicked
off unless it was archived beforehand. Replaying an old week to look at it is
fine and writes nothing; `--archive-anyway` overrides, and is only for
backfilling a week that genuinely was published.

Commit it every week along with the bet log:

```bash
git add picks/ data/bet_log.csv
git commit -m "week N picks and results"
git push
```

This archive and the bet log are the only two things in the repo that cannot
be regenerated. Everything else rebuilds from nflverse.

## Maintenance

```bash
.venv/bin/python -m pytest tests/ -q            # 24 invariant tests
.venv/bin/python scripts/run_backtest.py        # revalidate, refreeze params
.venv/bin/python scripts/measure_situational.py # re-test rest/weather/travel
```

Rerun the backtest and the situational measurement each offseason. Neither
should change much, but a factor the market prices correctly today could
become mispriced later.

## What is safe if this machine dies

Everything in git. `.venv/`, `data/cache/` and `output/` are all regenerable —
the virtualenv from `requirements.txt`, the cache from nflverse, the workbook
from the script.

The one exception is the bet log, which is hand-entered and irreplaceable. It
mirrors to `data/bet_log.csv`, which **is** tracked. Commit it periodically:

```bash
git add data/bet_log.csv && git commit -m "bet log through week N" && git push
```

If `output/` is ever lost, the next run rebuilds the workbook and restores the
tracker from that CSV.

## Book and self-tune (2026-09-25)

- All lines and prices come from **FanDuel only** (`config.MY_BOOK`). No
  consensus, no shopping table. A game FanDuel is not carrying falls back to
  the stored line with a WARNING — check FanDuel by hand for that one.
- Weekly self-tune is ON (`config.SELFTUNE`, max 1 pt per game). The SELF-TUNE
  block in the run output shows every nudge. See IMPROVEMENT.md for what it
  is and is not worth.
- Re-running mid-week (after TNF) re-prices only games not yet started; the
  published rows for played games are carried forward unchanged.
