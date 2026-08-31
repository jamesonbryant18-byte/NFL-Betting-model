# Weekly operating procedure

> Context for a fresh Claude session lives in `CLAUDE.md` (auto-loaded).
> Technical detail and validation results are in `README.md`.

The model ships in advisory mode because the hold-out backtest found no edge
against closing lines. So the first several weeks are a **measurement
exercise**, not a betting operation. This document is the procedure.

## The weekly loop

### Tuesday or Wednesday — build the slate

```bash
.venv/bin/python scripts/run_week.py            # next unplayed week
.venv/bin/python scripts/run_week.py --week 5   # a specific week
```

Tuesday/Wednesday is deliberate. Lines post Sunday night for the following
week and are softest early; that gap is where closing line value comes from.
Waiting until Sunday morning means betting into a number the market has
already sharpened.

If a starting quarterback is not who the model assumes — an offseason move, a
trade, an injury — override it. The model carries forward the previous
season's starter and cannot know anything that happened since:

```bash
.venv/bin/python scripts/run_week.py --qb LV="Kenny Pickett" --qb NYJ="..."
```

The run prints a WARNING listing any team whose starter it could not resolve.

### Same day — log what you would take

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
