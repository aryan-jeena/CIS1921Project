#!/usr/bin/env python3
"""Render the outcome-metrics comparison (formerly "Table 2") as a figure.

The final-report graphic shows the six outcome metrics from
``reports/tables/final_long.csv`` across the four solvers as a 2x3 grid
of horizontal bar charts, with the differentiating metric (preferred-day
workout hits) highlighted. The figure is meant to substitute for a
markdown table so the values can be imported as an image into a Word /
PDF version of the report without losing the story.

Output: ``reports/figures/outcome_metrics.png``.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from src.config.settings import FIGURES_DIR, TABLES_DIR


SOLVER_ORDER = ["nutrition_only", "two_stage", "joint_cpsat", "joint_warmstart"]
SOLVER_COLORS = {
    "nutrition_only": "#2ca02c",
    "two_stage": "#d62728",
    "joint_cpsat": "#1f77b4",
    "joint_warmstart": "#ff7f0e",
}

METRICS = [
    ("calorie_deviation_abs", "Calorie deviation\n(weekly |kcal|)", "{:.0f}"),
    ("protein_gap_to_target_g", "Protein gap to target\n(weekly g)", "{:.2f}"),
    ("total_cost_cents", "Total cost\n(weekly cents)", "{:.0f}"),
    ("workouts_scheduled", "Workouts scheduled", "{:.2f}"),
    ("peri_workout_meal_hits", "Peri-workout meal hits", "{:.2f}"),
    ("preferred_day_hits", "Preferred-day workout hits", "{:.2f}"),
]
HIGHLIGHT_METRIC = "preferred_day_hits"


def main() -> int:
    csv_path = TABLES_DIR / "final_long.csv"
    if not csv_path.exists():
        raise SystemExit(
            f"missing {csv_path} -- run "
            "`python -m src.app.cli experiments --prefix final` first"
        )
    df = pd.read_csv(csv_path)
    feas = df[df["feasible"]]

    fig, axes = plt.subplots(2, 3, figsize=(13, 7), facecolor="white")
    axes = axes.flatten()

    for ax, (col, label, fmt) in zip(axes, METRICS):
        means = feas.groupby("solver")[col].mean().reindex(SOLVER_ORDER).fillna(0.0)
        is_highlight = (col == HIGHLIGHT_METRIC)

        if is_highlight:
            ax.set_facecolor("#fff3d6")
            for spine in ax.spines.values():
                spine.set_edgecolor("#b8860b")
                spine.set_linewidth(2.0)

        bars = ax.barh(
            range(len(means)),
            means.values,
            color=[SOLVER_COLORS[s] for s in means.index],
            edgecolor="black",
            linewidth=0.8,
        )
        for i, (bar, value) in enumerate(zip(bars, means.values)):
            ax.text(
                bar.get_width() + (means.values.max() * 0.02 if means.values.max() > 0 else 0.05),
                bar.get_y() + bar.get_height() / 2,
                fmt.format(value),
                va="center", ha="left",
                fontsize=10,
                fontweight="bold" if is_highlight else "normal",
            )

        ax.set_yticks(range(len(means)))
        ax.set_yticklabels(means.index, fontsize=9)
        ax.invert_yaxis()
        ax.set_title(label, fontsize=11, fontweight="bold" if is_highlight else "normal")
        ax.tick_params(axis="x", labelsize=8)
        ax.grid(axis="x", linestyle=":", alpha=0.4)
        ax.set_xlim(0, max(means.values.max() * 1.25, 1.0))

    fig.suptitle(
        "Outcome metrics across 11 feasible instances "
        "(highlighted panel = where joint optimization actually pays off)",
        fontsize=12, y=0.99,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    out = FIGURES_DIR / "outcome_metrics.png"
    fig.savefig(out, dpi=150, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
