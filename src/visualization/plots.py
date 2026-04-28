"""Matplotlib chart helpers used by the experiment runner + the report.

Every function accepts a :class:`pandas.DataFrame` produced by
:func:`src.experiments.runner.run_experiment_suite` (long format) and an
output ``path``. The function saves a PNG and returns the path.

Keeping every plot as a pure function makes them trivial to regenerate after
changing weights or running a bigger sweep.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from src.config.settings import FIGURES_DIR
from src.utils.io import ensure_dir


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _fig_path(name: str, path: Path | None) -> Path:
    if path is None:
        ensure_dir(FIGURES_DIR)
        return FIGURES_DIR / f"{name}.png"
    return Path(path)


def _close(fig) -> None:
    plt.tight_layout()
    plt.close(fig)


# ---------------------------------------------------------------------------
# Plots
# ---------------------------------------------------------------------------
def plot_runtime_vs_size(df: pd.DataFrame, path: Path | None = None) -> Path:
    """Line plot: runtime vs instance size (``n_foods`` preferred).

    Expects columns ``solver``, ``runtime_s``, and either ``n_foods`` or a
    numeric ``instance_size`` column. Falls back to a labelled instance index
    if neither is present (the previous bare "row" label was flagged in
    check-in feedback).
    """
    fig, ax = plt.subplots(figsize=(8, 4.5))
    x_col = "n_foods" if "n_foods" in df.columns else (
        "instance_size" if "instance_size" in df.columns else None
    )
    x_label_lookup = {
        "n_foods": "n_foods (catalog size)",
        "instance_size": "instance size",
    }
    if x_col is None:
        df = df.copy()
        df["instance_index"] = range(len(df))
        x_col = "instance_index"
        x_label = "instance index"
    else:
        x_label = x_label_lookup.get(x_col, x_col)
    for solver, sub in df.groupby("solver"):
        sub_sorted = sub.sort_values(x_col)
        ax.plot(sub_sorted[x_col], sub_sorted["runtime_s"],
                marker="o", label=solver)
    ax.set_xlabel(x_label)
    ax.set_ylabel("runtime (s)")
    ax.set_title("Solver runtime vs. problem size")
    ax.grid(True, linestyle=":", alpha=0.5)
    ax.legend(title="solver")
    out = _fig_path("runtime_vs_size", path)
    fig.savefig(out, dpi=150)
    _close(fig)
    return out


def plot_feasibility_rate(df: pd.DataFrame, path: Path | None = None) -> Path:
    """Bar plot: feasibility rate per solver per scenario."""
    rates = (
        df.assign(feasible=df["feasible"].astype(int))
        .groupby(["solver", "instance"])["feasible"]
        .mean()
        .unstack("solver")
        .fillna(0)
    )
    fig, ax = plt.subplots(figsize=(9, 4))
    rates.plot.bar(ax=ax)
    ax.set_ylabel("feasibility rate")
    ax.set_ylim(0, 1.05)
    ax.set_title("Feasibility rate by scenario and solver")
    ax.legend(title="solver", loc="lower left")
    ax.tick_params(axis="x", rotation=30)
    for t in ax.get_xticklabels():
        t.set_ha("right")
    out = _fig_path("feasibility_rate", path)
    fig.savefig(out, dpi=150)
    _close(fig)
    return out


def plot_macro_achievement(df: pd.DataFrame, path: Path | None = None) -> Path:
    """Bar plot of daily calorie deviation and protein shortfall per solver."""
    metrics = df[df["feasible"]].groupby("solver").agg(
        cal_dev=("calorie_deviation_abs", "mean"),
        pro_gap=("protein_gap_to_target_g", "mean"),
    )
    fig, ax = plt.subplots(figsize=(7, 4))
    metrics.plot.bar(ax=ax)
    ax.set_ylabel("units (kcal / g)")
    ax.set_title("Average weekly calorie deviation and protein gap, per solver")
    ax.tick_params(axis="x", rotation=0)
    out = _fig_path("macro_achievement", path)
    fig.savefig(out, dpi=150)
    _close(fig)
    return out


def plot_formulation_comparison(df: pd.DataFrame, path: Path | None = None) -> Path:
    """Grouped bars: objective vs solver vs instance."""
    pivot = df.pivot_table(index="instance", columns="solver",
                           values="objective_value", aggfunc="first")
    fig, ax = plt.subplots(figsize=(9, 4))
    pivot.plot.bar(ax=ax)
    ax.set_ylabel("objective value")
    ax.set_title("Objective value by scenario and solver (lower is better)")
    ax.tick_params(axis="x", rotation=30)
    for t in ax.get_xticklabels():
        t.set_ha("right")
    out = _fig_path("formulation_comparison", path)
    fig.savefig(out, dpi=150)
    _close(fig)
    return out


def plot_cost_vs_protein(df: pd.DataFrame, path: Path | None = None) -> Path:
    """Scatter: cost vs protein achievement, colored by solver."""
    feas = df[df["feasible"]]
    fig, ax = plt.subplots(figsize=(7, 5))
    for solver, sub in feas.groupby("solver"):
        ax.scatter(sub["total_cost_cents"], sub["avg_protein_g"],
                   label=solver, s=60, alpha=0.75)
    ax.set_xlabel("weekly cost (cents)")
    ax.set_ylabel("avg daily protein (g)")
    ax.set_title("Cost vs. protein achievement across instances")
    ax.legend(title="solver")
    out = _fig_path("cost_vs_protein", path)
    fig.savefig(out, dpi=150)
    _close(fig)
    return out
