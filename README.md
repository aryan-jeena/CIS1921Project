# Constraint-Based Training, Nutrition, and Health Schedule Optimizer

CIS 1921 final project (Aryan Jeena, Aadithya Srinivasan). A personalized
weekly fitness + nutrition scheduler driven by **four** directly comparable
optimization formulations:

1. **Nutrition-only MIP** (baseline): choose foods to satisfy macros, budget,
   and dietary exclusions.
2. **Two-stage** baseline: the nutrition MIP picks foods, then a CP-SAT
   scheduler places the chosen meals + workouts + sleep on the week's time
   grid with no-overlap and recovery-spacing constraints.
3. **Joint CP-SAT** optimizer: a single model decides food servings *and*
   scheduling simultaneously, letting the solver trade macro deviation for
   better timing around workouts.
4. **Joint CP-SAT with LNS warm-start** (added in response to proposal
   feedback): runs two-stage first and then seeds the joint model with the
   resulting plan via `model.AddHint(...)`, so CP-SAT prunes large parts of
   the tree on its first probe while still being free to swap.

The repo is structured to support a report: experiment scripts write
machine-readable CSVs and PNGs, and the instance generator lets you sweep
across scaling, constraint-tightness, *and* the new pantry-mode axes. See
`reports/final_report.md` for the full write-up.

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

Python **3.11 or 3.12** is recommended. Python 3.13 also works. Python 3.10
and 3.14 are *not* recommended (3.10 lacks several pydantic-2 typing forms,
3.14 tightens dataclass mutable-default rules).

```bash
git clone git@github.com:aryan-jeena/CIS1921Project.git
cd CIS1921Project
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Belt-and-suspenders: make sure pyarrow is NOT in the venv (see note below).
pip uninstall -y pyarrow 2>/dev/null || true
```

OR-Tools ships prebuilt wheels for macOS, Linux, and Windows, so no
compilation is required.

> **Important — macOS users: do not install pyarrow alongside this project.**
> PyArrow vendors its own copy of the abseil C++ library, whose symbols
> shadow the abseil that OR-Tools links against. The result is a silent
> deadlock inside CP-SAT — the solver appears to "just be slow" but
> `max_time_in_seconds` is never honoured. We pin `pandas<2.3` in
> `requirements.txt` because pandas 3.x makes pyarrow a hard dependency.
> If you ever see CP-SAT hang past its time limit on macOS, check that
> pyarrow is uninstalled first. Linux installs are unaffected.

### Verify your install

```bash
python scripts/run_demo.py    # → all four solvers reach OPTIMAL in <2 s
pytest -q                     # → 37 tests, all green
```

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

### Pantry / dining-hall mode

Per check-in feedback we model what foods the user actually has access to
(fridge / pantry / dining hall) instead of treating the catalog as a
universal grocery store. Pass `--pantry-size N` (or use a scenario whose
profile sets `enforce_pantry=True`) to restrict the solver to a
deterministic N-food subset:

```bash
python -m src.app.cli solve --scenario pantry_dining_hall \
    --solver joint_cpsat --pantry-size 14 --figure
```

In pantry mode the cost weight is zeroed out -- once the food is in the
fridge / paid for via a meal swipe, cost is no longer the dominant
tradeoff. Macro fit and schedule pleasantness become the binding objective
terms.

## Experiments

Run the full sweep and regenerate the figures under `reports/figures/`:

```bash
python scripts/run_experiments.py --time-limit 30
# or, equivalently, the unified CLI with custom prefix:
python -m src.app.cli experiments --time-limit 25 --prefix final
```

Scaling study (runtime vs. food-catalog size, denser sweep up to n=200):

```bash
python scripts/run_scaling_study.py --max-foods 100 --time-limit 30
```

Generate the report-oriented figures (log-log scaling fits, cost/protein
Pareto, feasibility heatmap, objective breakdown, summary table):

```bash
python scripts/generate_results_graphics.py \
    --input reports/tables/final_long.csv \
    --out-dir reports/figures/results_graphics --prefix final
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

| Aspect                              | nutrition_only | two_stage | joint_cpsat | joint_warmstart |
| ----------------------------------- | :------------: | :-------: | :---------: | :-------------: |
| Macros + budget                     |       ✓        |     ✓     |      ✓      |        ✓        |
| Workout scheduling                  |       ✗        |     ✓     |      ✓      |        ✓        |
| Sleep + recovery spacing            |       ✗        |     ✓     |      ✓      |        ✓        |
| Peri-workout meal timing            |       ✗        |  partial  |      ✓      |        ✓        |
| Hydration reminders (soft)          |       ✗        |     ✗     |      ✓      |        ✓        |
| Pantry / dining-hall restriction    |       ✓        |     ✓     |      ✓      |        ✓        |
| Can trade macro slack for schedule  |       ✗        |     ✗     |      ✓      |        ✓        |
| Warm-started from two-stage plan    |       ✗        |     ✗     |      ✗      |        ✓        |
| Typical runtime (curated catalog)   |    < 0.5 s     |  < 0.5 s  |    1–15 s   |     2–15 s      |

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

- Column-generation / Benders-style decomposition to scale past 200 foods.
  Joint CP-SAT is well-behaved up to ~100; beyond that the
  `(food × meal_type × day)` combinatorics start to bite.
- Real Penn Dining scraping behind a feature flag (the current sample is
  semantically identical to what the page would yield, but updating it
  requires hand-curation; a cookie-aware Playwright fetcher is the next
  natural step).
- Online re-optimization as the week progresses (a missed workout triggers
  a partial re-solve over the remaining days).
- Per-meal protein floor as a hard constraint in pantry mode.

## Project identity

`reports/final_report.md` is the final write-up. `reports/draft_outline.md`
captures the original section structure used to plan the writeup.
