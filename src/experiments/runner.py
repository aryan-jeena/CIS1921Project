"""Batch experiment runner.

Given a list of instances and a list of solver classes, produces a long-format
pandas DataFrame where each row is ``(instance, solver, metric)``. The
function also optionally writes:

  - ``reports/tables/<name>.csv``      : long-format results
  - ``reports/tables/<name>_wide.csv`` : pivot for human inspection

The runner *never raises* on solver failure; a crashed solver is recorded
as status="ERROR" and the sweep continues. This is crucial for scalability
experiments where the joint solver sometimes times out.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd

from src.config.settings import TABLES_DIR
from src.data_ingestion.food_catalog import build_food_catalog
from src.data_ingestion.workouts import load_sample_workouts
from src.evaluation.metrics import compute_metrics
from src.evaluation.validator import validate_plan
from src.models.domain import FoodItem, UserProfile, WorkoutTemplate
from src.solvers import ALL_SOLVERS
from src.solvers.base import BaseSolver
from src.utils.io import ensure_dir
from src.utils.logging import get_logger

_logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Single-run helper
# ---------------------------------------------------------------------------
def run_single(
    solver: BaseSolver | type[BaseSolver] | str,
    user: UserProfile,
    foods: list[FoodItem] | None = None,
    workouts: list[WorkoutTemplate] | None = None,
) -> dict:
    """Run one solver on one instance and return a metrics row dict."""
    if isinstance(solver, str):
        solver = ALL_SOLVERS[solver]()
    elif isinstance(solver, type):
        solver = solver()

    if foods is None:
        foods = build_food_catalog(exclusions=user.dietary_exclusions)
    if workouts is None:
        workouts = load_sample_workouts()

    try:
        result = solver.solve(user, foods, workouts)
    except Exception as exc:  # noqa: BLE001 - defensive for batch runs
        _logger.exception("Solver %s crashed: %s", solver.name, exc)
        row = {
            "instance": user.name,
            "solver": solver.name,
            "status": "ERROR",
            "runtime_s": 0.0,
            "feasible": False,
            "objective_value": None,
            "error": str(exc),
        }
        return row

    metrics = compute_metrics(result, user)
    row = metrics.as_dict()
    row["instance"] = user.name
    row["solver"] = solver.name
    row["error"] = ""
    # Record problem size so scaling figures don't have to fall back to a
    # row index for the x-axis.
    row["n_foods"] = len(foods)
    row["n_workouts"] = len(workouts)
    row["pantry_mode"] = bool(user.enforce_pantry and user.pantry_food_ids)
    row["hydration_target"] = (
        user.hydration.target_reminders_per_day
        if user.hydration.enabled else 0
    )
    if result.extras:
        if "warm_started" in result.extras:
            row["warm_started"] = bool(result.extras["warm_started"])
        if "hydration_shortfall" in result.extras:
            row["hydration_shortfall"] = int(result.extras["hydration_shortfall"])

    # Cross-check hard constraints
    if result.plan is not None:
        report = validate_plan(result.plan, user)
        row["validated_ok"] = report.ok
        row["n_hard_violations"] = len(report.violations)
    else:
        row["validated_ok"] = False
        row["n_hard_violations"] = 0

    return row


# ---------------------------------------------------------------------------
# Batch sweep
# ---------------------------------------------------------------------------
def run_experiment_suite(
    instances: Iterable[UserProfile],
    solver_names: Iterable[str] = ("nutrition_only", "two_stage", "joint_cpsat"),
    foods: list[FoodItem] | None = None,
    workouts: list[WorkoutTemplate] | None = None,
    *,
    output_prefix: str = "experiment",
    save_csv: bool = True,
    time_limit_s: int | None = None,
) -> pd.DataFrame:
    """Run each solver on each instance, accumulate metrics.

    Returns a long-format :class:`pandas.DataFrame`; also writes CSV under
    ``reports/tables/`` when ``save_csv=True``.
    """
    instances = list(instances)
    solver_names = list(solver_names)

    if foods is None:
        foods = build_food_catalog()
    if workouts is None:
        workouts = load_sample_workouts()

    rows: list[dict] = []
    for user in instances:
        for name in solver_names:
            cls = ALL_SOLVERS[name]
            kwargs = {}
            if time_limit_s is not None:
                kwargs["time_limit_s"] = time_limit_s
            solver = cls(**kwargs)
            _logger.info("Running %s on %s ...", name, user.name)
            row = run_single(solver, user, foods=foods, workouts=workouts)
            rows.append(row)

    df = pd.DataFrame(rows)
    if save_csv and not df.empty:
        ensure_dir(TABLES_DIR)
        long_path = TABLES_DIR / f"{output_prefix}_long.csv"
        df.to_csv(long_path, index=False)
        # Narrow pivot for common metrics
        try:
            pivot_cols = ["feasible", "runtime_s", "objective_value",
                          "calorie_deviation_abs", "total_cost_cents",
                          "workouts_scheduled", "preferred_day_hits",
                          "peri_workout_meal_hits"]
            wide_rows = []
            for (inst, solver), sub in df.groupby(["instance", "solver"]):
                r = {"instance": inst, "solver": solver}
                for c in pivot_cols:
                    if c in sub.columns:
                        r[c] = sub[c].iloc[0]
                wide_rows.append(r)
            wide = pd.DataFrame(wide_rows)
            wide.to_csv(TABLES_DIR / f"{output_prefix}_summary.csv", index=False)
        except Exception:
            # Never fail the sweep just because the pivot failed.
            _logger.warning("Could not write wide summary CSV.")

    return df
