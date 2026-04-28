#!/usr/bin/env python3
"""Scaling study: plot solver runtime vs. problem size.

Per check-in feedback we replace the original 8/16/24/.../48 sweep -- which
all solved in well under a second -- with a denser, larger sweep that
actually pushes the joint CP-SAT solver. We sweep ``n_foods`` from 10 up to
200 with the workout pool growing alongside, and we run every solver under
a generous time limit so the figure shows where each formulation starts to
slow down.

The size axis records the actual ``n_foods`` value for every row so the
generated runtime plot uses a meaningful x-axis (no more "row" label that
was flagged in feedback).

Usage::

    python scripts/run_scaling_study.py
    python scripts/run_scaling_study.py --max-foods 120 --time-limit 30
    python scripts/run_scaling_study.py --solvers nutrition_only,joint_cpsat
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from src.config.settings import FIGURES_DIR, TABLES_DIR  # noqa: E402
from src.data_ingestion.food_catalog import build_food_catalog  # noqa: E402
from src.data_ingestion.workouts import load_sample_workouts  # noqa: E402
from src.experiments.instance_generator import (  # noqa: E402
    generate_scaling_instances,
)
from src.experiments.runner import run_single  # noqa: E402
from src.solvers import ALL_SOLVERS  # noqa: E402
from src.utils.io import ensure_dir  # noqa: E402
from src.visualization.plots import plot_runtime_vs_size  # noqa: E402


DEFAULT_SIZES = [10, 20, 30, 45, 60, 80, 100, 130, 160, 200]


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--max-foods", type=int, default=None,
        help="Cap the largest size in the sweep (defaults to 200).",
    )
    p.add_argument(
        "--solvers", type=str, default=",".join(ALL_SOLVERS.keys()),
        help="Comma-separated list of solver names to include.",
    )
    p.add_argument(
        "--time-limit", type=int, default=30,
        help="Per-solver per-instance time limit in seconds (default 30).",
    )
    p.add_argument(
        "--output-prefix", type=str, default="scaling",
        help="Prefix for output CSV/PNG files written to reports/.",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    sizes = DEFAULT_SIZES
    if args.max_foods is not None:
        sizes = [s for s in DEFAULT_SIZES if s <= args.max_foods]
    requested_solvers = [s.strip() for s in args.solvers.split(",") if s.strip()]
    bad = [s for s in requested_solvers if s not in ALL_SOLVERS]
    if bad:
        raise SystemExit(f"Unknown solver(s): {bad}. Choose from {list(ALL_SOLVERS)}")

    base_foods = build_food_catalog()
    base_workouts = load_sample_workouts()

    instance_pairs = generate_scaling_instances(sizes=sizes)
    rows: list[dict] = []
    for user, target_n in instance_pairs:
        foods = base_foods[:target_n]
        workouts = base_workouts[: max(3, min(len(base_workouts), target_n // 10))]
        for name in requested_solvers:
            cls = ALL_SOLVERS[name]
            solver = cls(time_limit_s=args.time_limit)
            row = run_single(solver, user, foods=foods, workouts=workouts)
            row["n_foods"] = target_n
            row["n_workouts"] = len(workouts)
            rows.append(row)

    df = pd.DataFrame(rows)
    ensure_dir(TABLES_DIR)
    csv_path = TABLES_DIR / f"{args.output_prefix}_long.csv"
    df.to_csv(csv_path, index=False)
    fig_path = FIGURES_DIR / f"{args.output_prefix}_runtime.png"
    plot_runtime_vs_size(df, fig_path)
    print(f"Wrote {csv_path}")
    print(f"Wrote {fig_path}")
    print(df.groupby(["solver"]).agg(
        runs=("n_foods", "size"),
        feas_rate=("feasible", "mean"),
        mean_runtime_s=("runtime_s", "mean"),
        max_runtime_s=("runtime_s", "max"),
    ).round(3).to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
