#!/usr/bin/env python3
"""Scaling study: plot solver runtime vs. problem size.

For each solver and each point on the size axis, we generate a ``balanced``
user, cap the food catalog + workout library at that size, solve, and record
runtime. The result is a runtime-vs-n_foods plot under ``reports/figures/``.

Usage::

    python scripts/run_scaling_study.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from src.config.settings import FIGURES_DIR, TABLES_DIR  # noqa: E402
from src.data_ingestion.food_catalog import build_food_catalog  # noqa: E402
from src.data_ingestion.workouts import load_sample_workouts  # noqa: E402
from src.experiments.instance_generator import (  # noqa: E402
    InstanceParams,
    generate_user,
)
from src.experiments.runner import run_single  # noqa: E402
from src.solvers import ALL_SOLVERS  # noqa: E402
from src.utils.io import ensure_dir  # noqa: E402
from src.visualization.plots import plot_runtime_vs_size  # noqa: E402


def main() -> int:
    sizes = [8, 16, 24, 32, 40, 48]
    base_foods = build_food_catalog()
    base_workouts = load_sample_workouts()

    rows = []
    for n in sizes:
        foods = base_foods[:n]
        workouts = base_workouts[:min(len(base_workouts), max(3, n // 5))]
        user = generate_user("balanced", InstanceParams(seed=1921 + n))
        for name, cls in ALL_SOLVERS.items():
            solver = cls(time_limit_s=20)
            row = run_single(solver, user, foods=foods, workouts=workouts)
            row["n_foods"] = n
            rows.append(row)

    df = pd.DataFrame(rows)
    ensure_dir(TABLES_DIR)
    df.to_csv(TABLES_DIR / "scaling_study.csv", index=False)
    plot_runtime_vs_size(df, FIGURES_DIR / "scaling_runtime.png")
    print(f"Wrote {TABLES_DIR / 'scaling_study.csv'}")
    print(f"Wrote {FIGURES_DIR / 'scaling_runtime.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
