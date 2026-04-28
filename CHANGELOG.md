# Changelog

All notable changes to this project are recorded here. The format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). This
project is a CIS 1921 final submission rather than a released package, so
versions are tagged by milestone rather than SemVer.

## [Unreleased]

### Added
- `src/visualization/results_graphics.py` — standalone module of pure
  functions that build report-oriented figures (log-log runtime scaling
  with per-solver power-law fits, cost/protein Pareto view, feasibility
  heatmap, stacked objective breakdown, per-solver summary table). The
  module is intentionally decoupled from the experiment runner so figures
  can be regenerated without touching solver state.
- `scripts/generate_results_graphics.py` — CLI entrypoint that loads a
  long-format results CSV, optionally applies a JSON config, and writes
  PNGs to a chosen output directory. Supports `--dry-run` for plan
  inspection.
- `configs/results_graphics.json` — default rendering knobs and
  deterministic solver/instance ordering.

### Changed
- _(none — existing solver, experiment, ingestion, and evaluation code is
  unchanged in this batch of commits.)_

### Removed
- _(none.)_

## [checkin-2026-04] — 2026-04-16

### Added
- Initial project snapshot committed to version control: solver variants
  (nutrition LP/MIP, two-stage scheduler, joint CP-SAT), data ingestion
  helpers, evaluation metrics, experiment runner, visualization helpers,
  Streamlit app, unit tests, preset scenario configs, and the check-in
  report assets under `reports/`.
