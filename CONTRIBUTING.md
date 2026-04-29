# Contributing notes

This repository is a CIS 1921 final project — it is not a production package
— but keeping a few conventions consistent makes the report and the
experiments easier to reproduce.

## Scope reminder

The project's centre of gravity is **optimization modelling**:

- LP / MIP for nutrition
- Two-stage meals → schedule baseline
- Joint CP-SAT weekly optimizer

Additions should sharpen one of these axes (better modelling, better
experiments, better evaluation, better figures). Flashy UI work is lower
priority than modelling, solver comparability, and experiment
reproducibility.

## Layout at a glance

```
src/
  config/         # settings + constants
  data_ingestion/ # food catalogues, workouts, Penn Dining, USDA
  evaluation/     # metrics + validators
  experiments/    # sweep runner + preset instances
  models/         # typed domain models
  nutrition/      # LP/MIP solvers
  scheduling/     # two-stage scheduler
  solvers/        # joint CP-SAT solver
  visualization/  # plots + schedule renderings + results_graphics
  app/            # Streamlit + CLI entrypoints
scripts/          # thin CLI wrappers
configs/          # JSON presets
data/             # sample / raw / processed
reports/          # figures, tables, writeups
tests/            # pytest suite
```

## Development workflow

1. Pick a change that fits one of the solver variants or evaluation axes.
2. Run the existing tests before starting: `pytest -q`.
3. Implement the change with typed code and small, composable functions.
4. Regenerate the relevant figures if the change affects solver output:
   ```bash
   python scripts/run_experiments.py
   python scripts/generate_results_graphics.py \
     --input reports/tables/checkin_long.csv \
     --out-dir reports/figures/results_graphics
   ```
5. Update `CHANGELOG.md` under `[Unreleased]`.

## Commit style

- Imperative subject (≤ 70 chars).
- Scope prefix where it helps: `feat(visualization)`, `chore(configs)`,
  `docs`, `test`, `refactor`.
- Explain **why** in the body, not just what — the diff already says what.

## Reproducibility

- Keep random seeds explicit when experiments involve generated instances.
- Prefer deterministic output ordering (solvers, instances) in tables and
  figures so diffs stay meaningful.
- Long-format experiment CSVs under `reports/tables/` are the source of
  truth for plotting; regenerate figures from them rather than by hand.

## Things to avoid

- Editing an existing solver to make a new chart work — add a new helper
  instead, then wire it in.
- Committing bulk data under `data/raw/` or `data/processed/` (they are
  already gitignored; keep it that way).
- Mixing multiple unrelated changes in a single commit.
