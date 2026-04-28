# Constraint-Based Training, Nutrition, and Health Schedule Optimizer

CIS 1921 final project. A personalized weekly fitness + nutrition scheduler
driven by three increasingly expressive optimization formulations:

1. **Nutrition-only MIP** (baseline): choose foods to satisfy macros, budget,
   and dietary exclusions.
2. **Two-stage** baseline: the nutrition MIP picks foods, then a CP-SAT
   scheduler places the chosen meals + workouts + sleep on the week's time
   grid with no-overlap and recovery-spacing constraints.
3. **Joint CP-SAT** optimizer: a single model decides food servings *and*
   scheduling simultaneously, letting the solver trade macro deviation for
   better timing around workouts.

The repo is structured to support a report: experiment scripts write
machine-readable CSVs and PNGs, and the instance generator lets you sweep
across scaling and constraint-tightness axes.

## Motivation

Training adherence depends on much more than macros. When you lift, when you
eat, and when you sleep all matter. Real students are juggling class
schedules, dining-hall windows, and budgets simultaneously. Solving each
dimension independently (the standard "meal planner + calendar app" split)
produces plans that are technically compliant but practically useless:
e.g. the meal prep finishes 15 minutes before a squat PR. The joint
formulation is the whole point.

## How this relates to LP / MIP / CP-SAT

- **LP / MIP** — the nutrition sub-problem is a classical diet-problem
  variant: integer servings, linear macro/calorie/cost constraints, linear
  soft-penalty objective. Implemented as an integer program on CP-SAT
  (`src/nutrition/mip_model.py`).
- **CP-SAT scheduling** — the stage-2 scheduler models activities as
  optional intervals on a 7×48 slot grid with `AddNoOverlap`
  (`src/scheduling/stage2_scheduler.py`).
- **Joint CP-SAT** — combines the two, adding peri-workout meal timing and
  max-consecutive-hard-days reasoning that neither baseline can express
  cleanly (`src/solvers/joint_cpsat.py`).

Hard constraints are encoded as model constraints; soft constraints are
weighted terms in `ScoringWeights` (`src/config/settings.py`). The
distinction is preserved in both code and output so experiments can quantify
the trade-offs.

## Architecture

```
src/
├── config/           paths, time granularity, scoring weights
├── models/           pydantic domain types (UserProfile, FoodItem, …)
├── data_ingestion/   food catalog (sample CSV + Penn Dining + USDA stub)
├── nutrition/        pure MIP helpers
├── scheduling/       time-grid + stage-2 scheduler
├── solvers/          nutrition_only, two_stage, joint_cpsat (shared interface)
├── evaluation/       metrics + hard-constraint validator
├── experiments/      instance generator + batch runner
├── visualization/    matplotlib plots + schedule renderer
├── utils/            small io/logging helpers
└── app/              CLI (argparse) + Streamlit UI
```

Each solver accepts `(UserProfile, list[FoodItem], list[WorkoutTemplate])`
and returns a `SolverResult`. Experiments can substitute one solver for
another without touching the runner.

## Installation

Python 3.11+ recommended.

```bash
cd "CIS 1921 Project"
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

OR-Tools ships prebuilt wheels for macOS/Linux/Windows, so no compilation
is required.

## Quick demo

Run all three solvers on a balanced scenario and dump a per-solver summary:

```bash
python scripts/run_demo.py
```

Solve a single preset with the joint solver and render a schedule PNG:

```bash
python -m src.app.cli solve --preset lean_bulk --solver joint_cpsat --figure
```

List bundled presets:

```bash
python -m src.app.cli presets
```

## Experiments

Run the full sweep and regenerate the figures under `reports/figures/`:

```bash
python scripts/run_experiments.py --time-limit 30
```

Scaling study (runtime vs. food-catalog size):

```bash
python scripts/run_scaling_study.py
```

Both commands write long-format CSVs to `reports/tables/` and PNGs to
`reports/figures/`. The CLI wrappers reuse the runner module so all results
are exactly reproducible from a fixed seed.

## UI

```bash
python scripts/launch_ui.py
# or equivalently:
streamlit run src/app/streamlit_app.py
```

The Streamlit app exposes the instance form (scenario or preset, plus macro
/ budget / workout-count overrides), solver choice, and time limit. It shows
the weekly schedule, per-day nutrition rollups, and the hard-constraint
validator's report. Intentionally lightweight: it is an interface to the
optimizer, not a product.

## Tests

```bash
pytest
```

Coverage: config/model validators, food-catalog loaders, instance generator
determinism, nutrition MIP feasibility + budget respect, stage-2 scheduler
non-overlap, joint solver recovery-rule enforcement, validator + metrics.

## Solver comparison at a glance

| Aspect                              | nutrition_only | two_stage | joint_cpsat |
| ----------------------------------- | :------------: | :-------: | :---------: |
| Macros + budget                     |       ✓        |     ✓     |      ✓      |
| Workout scheduling                  |       ✗        |     ✓     |      ✓      |
| Sleep + recovery spacing            |       ✗        |     ✓     |      ✓      |
| Peri-workout meal timing            |       ✗        |  partial  |      ✓      |
| Can trade macro slack for schedule  |       ✗        |     ✗     |      ✓      |
| Typical runtime (curated catalog)   |    < 0.5 s     |  1–5 s    |    2–15 s   |

## Known limitations

- Meal placement granularity is 30 minutes — fine enough for realistic
  schedules but coarser than literal minute-by-minute planning.
- Penn Dining live scraping is best-effort. Their HTML layout changes; the
  project always has a bundled JSON fallback so nothing depends on an
  internet connection at grade time.
- The joint CP-SAT model is practical on catalogs up to ~80 foods and ~10
  workout templates. Larger catalogs warrant a column-generation or
  decomposition approach, which is outside the scope of this project.
- Hydration reminders are currently soft-scored only; a future version could
  materialize them as scheduled blocks.

## Future work

- Column-generation style pre-filtering (seed each meal bucket with a
  small shortlist of foods) to scale past 100 foods.
- Infeasibility explanations via CP-SAT assumption tracking (OR-Tools
  `assumption` variables) to tell users *which* constraint forced the
  problem to be infeasible.
- Better Penn Dining scraper with cookie-aware fetching.
- USDA FoodData Central ingestion end-to-end (currently loader exists but
  expects a pre-joined summary CSV).

## Project identity

See `CLAUDE.md` for the design brief this project is built against.
`reports/draft_outline.md` gives the section structure for the final report.
