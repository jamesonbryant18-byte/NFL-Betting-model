# Expert review: start here

Everything from the expert reviews of the model (started 2026-10-27) lives in this
folder, so a new grading round reuses the research and the rubric instead of redoing
them. (The review skill's default folder name is `.expert-review`; this project uses
`expert-review` so it shows in Finder. CLAUDE.md points here.)

## What is here

| File | What it is |
|---|---|
| `rubric.md` | The locked 100-point rubric (v2, approved 2026-10-29). Reuse it as is so scores stay comparable. v1 is in `round-1/rubric-v1.md`. |
| `expert-brief.md` | The research, condensed for a grader: the domain standards, what good numbers look like, the pitfalls to hunt for in this project, and the sources. A grader reads this instead of researching. |
| `grader-prompt.md` | The exact prompt given to the fresh grader each round, with the blanks to fill in. |
| `research/deep-research-report.md` | The deep-research run behind the brief: 7 verified claims, 18 leads, 21 sources with links. Raw output: `research/deep-research-raw.json`. |
| `research/sources/` | Text and data pulled from the key sources (Benter, Boulier, Moskowitz, nfelo, Prediction Tracker, football-data closing odds, a CLV explainer). Kept on this Mac only, not in git; the links are in the report and the brief. |
| `round-1/` | Grade 40/100 (rubric v1), the fix list, what was changed, and the grader's scripts and outputs (`grader-work/`). |
| `round-2/` | Grade 55/100 (rubric v2), the fix list, what was changed, and the grader's scripts and outputs. |
| `report-card.md` | The score trajectory and what is still costing points. |

## Grading again without redoing the research

1. Reuse `rubric.md` and `expert-brief.md` as they are. New research is only worth doing
   if the model changes in kind (a different model, new markets, a new data source).
   Changing the rubric makes a new version, and its scores are not strictly comparable.
2. Make the grader a scratch copy of the repo WITHOUT this folder, so it never sees an
   earlier score or fix list:
   `rsync -a --exclude expert-review --exclude .expert-review --exclude .venv --exclude __pycache__ ~/Desktop/NFL-Betting-model/ <scratch>/NFL-Betting-model/`
   and copy `rubric.md` and `expert-brief.md` next to it.
3. Give it `grader-prompt.md` with the blanks filled in. Say nothing about earlier rounds,
   what changed, or the score you expect.
4. Save its report as `round-N/grade.md` here, and its scripts and outputs (not the
   workbook copies) as `round-N/grader-work/`.

The graders' scripts in `round-*/grader-work/` are worth a look before writing a new
check: most of the numbers (hold-out straight-up vs the favorite, calibration buckets,
value at the price taken, edge buckets, the structural ablation) already have a script.
They were written against a scratch copy, so paths at the top may need changing.

One known limit: the grades are committed to git, so a grader digging through old
commits could find an earlier score. Graders are told to grade the project as it stands.
