"""Results graphics generator for experiment sweeps.

This module is an *additive* companion to :mod:`src.visualization.plots`. The
existing ``plots.py`` focuses on the small set of figures that the experiment
runner produces automatically. ``results_graphics`` layers on richer,
report-oriented charts that we want to assemble after a sweep has already been
written to ``reports/tables``.

Design goals
------------

* **Pure functions.** Every public builder takes a long-format ``pandas``
  DataFrame (the same schema produced by
  :func:`src.experiments.runner.run_experiment_suite`) plus an optional output
  path, and returns the saved ``Path``. This mirrors the contract of
  ``plots.py`` so the two modules feel interchangeable.
* **Matplotlib only.** No seaborn / plotly dependency so the module works with
  the exact requirements already pinned in ``requirements.txt``.
* **Deterministic layout.** Charts sort solvers and instances alphabetically
  so repeated generation yields byte-identical PNGs when the inputs match.
* **No side effects beyond the output file.** The module does not mutate its
  input DataFrame.

Nothing here is wired into the default experiment pipeline - the accompanying
``scripts/generate_results_graphics.py`` CLI is what stitches everything
together. This file is intentionally read-only from the perspective of the
existing solver and experiment code.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Columns the report-oriented charts expect to find in the long-format
#: experiment DataFrame. Missing columns are tolerated - any chart whose
#: required columns are absent will raise a descriptive ``KeyError``.
EXPECTED_COLUMNS: tuple[str, ...] = (
    "solver",
    "instance",
    "runtime_s",
    "feasible",
    "objective_value",
    "calorie_deviation_abs",
    "protein_gap_to_target_g",
    "total_cost_cents",
    "avg_protein_g",
    "n_foods",
)

#: Default output directory, relative to the repository root. Resolved lazily
#: so the module can be imported without side effects.
DEFAULT_FIGURES_SUBDIR = "reports/figures/results_graphics"

#: A small, colour-blind friendly palette. Ordered deterministically so that
#: repeated runs produce the same legend colours.
SOLVER_PALETTE: tuple[str, ...] = (
    "#1f77b4",  # blue
    "#ff7f0e",  # orange
    "#2ca02c",  # green
    "#d62728",  # red
    "#9467bd",  # purple
    "#8c564b",  # brown
    "#17becf",  # cyan
)


# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class GraphicsConfig:
    """Bundle of optional rendering knobs.

    The CLI reads a JSON file into this dataclass so non-Python users can tune
    the output without editing code.
    """

    dpi: int = 150
    figsize_small: tuple[float, float] = (7.0, 4.0)
    figsize_wide: tuple[float, float] = (10.0, 4.5)
    figsize_square: tuple[float, float] = (6.5, 6.0)
    title_fontsize: int = 12
    label_fontsize: int = 10
    palette: tuple[str, ...] = SOLVER_PALETTE
    annotate_bars: bool = True
    grid: bool = True
    style: str = "default"
    prefix: str = "results"
    include_scaling: bool = True
    include_pareto: bool = True
    include_heatmap: bool = True
    include_stacked: bool = True
    include_summary_table: bool = True
    solver_order: tuple[str, ...] = field(default_factory=tuple)
    instance_order: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_mapping(cls, data: Mapping[str, object] | None) -> "GraphicsConfig":
        """Build a :class:`GraphicsConfig` from a plain ``dict`` (e.g. JSON)."""
        if not data:
            return cls()
        allowed = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        cleaned: dict[str, object] = {}
        for key, value in data.items():
            if key not in allowed:
                continue
            if key in {"figsize_small", "figsize_wide", "figsize_square"} and isinstance(value, list):
                cleaned[key] = tuple(float(v) for v in value)  # type: ignore[assignment]
            elif key in {"palette", "solver_order", "instance_order"} and isinstance(value, list):
                cleaned[key] = tuple(str(v) for v in value)  # type: ignore[assignment]
            else:
                cleaned[key] = value
        return cls(**cleaned)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _resolve_path(name: str, out_dir: Path | None, prefix: str) -> Path:
    base = Path(out_dir) if out_dir is not None else Path.cwd() / DEFAULT_FIGURES_SUBDIR
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{prefix}_{name}.png"


def _ensure_columns(df: pd.DataFrame, required: Sequence[str]) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(
            "Results DataFrame is missing required columns: "
            + ", ".join(missing)
        )


def _order_categorical(
    values: Iterable[str], preferred: Sequence[str]
) -> list[str]:
    seen = list(dict.fromkeys(values))  # stable de-dup preserving insertion
    head = [v for v in preferred if v in seen]
    tail = sorted(v for v in seen if v not in head)
    return head + tail


def _palette_for(labels: Sequence[str], palette: Sequence[str]) -> dict[str, str]:
    colors = list(palette) * (len(labels) // len(palette) + 1)
    return {label: colors[i] for i, label in enumerate(labels)}


def _annotate(ax: plt.Axes, fmt: str = "{:.2f}") -> None:
    for bar in ax.patches:
        height = bar.get_height()
        if np.isnan(height):
            continue
        ax.annotate(
            fmt.format(height),
            xy=(bar.get_x() + bar.get_width() / 2, height),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=8,
        )


def _finalise(fig: plt.Figure, ax: plt.Axes, title: str, cfg: GraphicsConfig) -> None:
    ax.set_title(title, fontsize=cfg.title_fontsize)
    ax.tick_params(labelsize=cfg.label_fontsize)
    if cfg.grid:
        ax.grid(True, linestyle=":", alpha=0.4)
    fig.tight_layout()


# ---------------------------------------------------------------------------
# Chart builders
# ---------------------------------------------------------------------------
def build_runtime_scaling_figure(
    df: pd.DataFrame,
    cfg: GraphicsConfig = GraphicsConfig(),
    out_dir: Path | None = None,
) -> Path:
    """Log-log runtime vs. ``n_foods`` with per-solver power-law fits.

    A rough power-law fit (``log t = a log n + b``) is drawn as a dashed line so
    readers can eyeball scaling exponents across formulations.
    """
    _ensure_columns(df, ["solver", "n_foods", "runtime_s"])
    feas = df[(df["runtime_s"] > 0) & df["n_foods"].notna()]
    solvers = _order_categorical(feas["solver"].unique(), cfg.solver_order)
    colors = _palette_for(solvers, cfg.palette)

    fig, ax = plt.subplots(figsize=cfg.figsize_wide)
    for solver in solvers:
        sub = feas[feas["solver"] == solver].sort_values("n_foods")
        if sub.empty:
            continue
        ax.scatter(
            sub["n_foods"], sub["runtime_s"],
            color=colors[solver], label=solver, s=45, alpha=0.75,
        )
        if len(sub) >= 3:
            logs_x = np.log(sub["n_foods"].to_numpy(dtype=float))
            logs_y = np.log(sub["runtime_s"].to_numpy(dtype=float))
            slope, intercept = np.polyfit(logs_x, logs_y, 1)
            fit_x = np.linspace(logs_x.min(), logs_x.max(), 50)
            fit_y = slope * fit_x + intercept
            ax.plot(
                np.exp(fit_x), np.exp(fit_y),
                color=colors[solver], linestyle="--", alpha=0.6,
                label=f"{solver} fit (slope={slope:.2f})",
            )

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("n_foods (log scale)", fontsize=cfg.label_fontsize)
    ax.set_ylabel("runtime seconds (log scale)", fontsize=cfg.label_fontsize)
    ax.legend(fontsize=8, loc="best")
    _finalise(fig, ax, "Scaling: runtime vs. catalogue size", cfg)
    out = _resolve_path("runtime_scaling", out_dir, cfg.prefix)
    fig.savefig(out, dpi=cfg.dpi)
    plt.close(fig)
    return out


def build_pareto_cost_protein_figure(
    df: pd.DataFrame,
    cfg: GraphicsConfig = GraphicsConfig(),
    out_dir: Path | None = None,
) -> Path:
    """Pareto-style scatter of weekly cost vs. average protein per solver.

    Dominated points (worse on both axes than some other feasible run) are
    greyed out so the non-dominated frontier stands out.
    """
    _ensure_columns(df, ["solver", "feasible", "total_cost_cents", "avg_protein_g"])
    feas = df[df["feasible"]].copy()
    if feas.empty:
        fig, ax = plt.subplots(figsize=cfg.figsize_square)
        ax.text(0.5, 0.5, "No feasible runs to plot", ha="center", va="center")
        ax.set_axis_off()
        out = _resolve_path("pareto_cost_protein", out_dir, cfg.prefix)
        fig.savefig(out, dpi=cfg.dpi)
        plt.close(fig)
        return out

    # Identify non-dominated points: lower cost is better, higher protein is better.
    costs = feas["total_cost_cents"].to_numpy(dtype=float)
    proteins = feas["avg_protein_g"].to_numpy(dtype=float)
    dominated = np.zeros(len(feas), dtype=bool)
    for i in range(len(feas)):
        for j in range(len(feas)):
            if i == j:
                continue
            if costs[j] <= costs[i] and proteins[j] >= proteins[i] and (
                costs[j] < costs[i] or proteins[j] > proteins[i]
            ):
                dominated[i] = True
                break
    feas = feas.assign(dominated=dominated)

    solvers = _order_categorical(feas["solver"].unique(), cfg.solver_order)
    colors = _palette_for(solvers, cfg.palette)

    fig, ax = plt.subplots(figsize=cfg.figsize_square)
    for solver in solvers:
        sub = feas[feas["solver"] == solver]
        if sub.empty:
            continue
        nd = sub[~sub["dominated"]]
        dm = sub[sub["dominated"]]
        ax.scatter(
            dm["total_cost_cents"], dm["avg_protein_g"],
            color=colors[solver], alpha=0.25, s=40, marker="o",
        )
        ax.scatter(
            nd["total_cost_cents"], nd["avg_protein_g"],
            color=colors[solver], alpha=0.95, s=80, marker="*",
            label=f"{solver} (non-dominated)",
        )
    ax.set_xlabel("weekly cost (cents)")
    ax.set_ylabel("avg daily protein (g)")
    ax.legend(fontsize=8, loc="best")
    _finalise(fig, ax, "Cost vs. protein Pareto view", cfg)
    out = _resolve_path("pareto_cost_protein", out_dir, cfg.prefix)
    fig.savefig(out, dpi=cfg.dpi)
    plt.close(fig)
    return out


def build_feasibility_heatmap_figure(
    df: pd.DataFrame,
    cfg: GraphicsConfig = GraphicsConfig(),
    out_dir: Path | None = None,
) -> Path:
    """Heatmap of feasibility rate per (instance, solver)."""
    _ensure_columns(df, ["solver", "instance", "feasible"])
    pivot = (
        df.assign(feasible=df["feasible"].astype(int))
        .groupby(["instance", "solver"])["feasible"]
        .mean()
        .unstack("solver")
    )
    instances = _order_categorical(pivot.index.tolist(), cfg.instance_order)
    solvers = _order_categorical(pivot.columns.tolist(), cfg.solver_order)
    pivot = pivot.reindex(index=instances, columns=solvers).fillna(0.0)

    fig, ax = plt.subplots(figsize=cfg.figsize_wide)
    im = ax.imshow(
        pivot.to_numpy(),
        cmap="viridis", vmin=0.0, vmax=1.0, aspect="auto",
    )
    ax.set_xticks(range(len(solvers)))
    ax.set_xticklabels(solvers, rotation=30, ha="right")
    ax.set_yticks(range(len(instances)))
    ax.set_yticklabels(instances)
    for i, row in enumerate(pivot.to_numpy()):
        for j, value in enumerate(row):
            ax.text(
                j, i, f"{value:.2f}",
                ha="center", va="center",
                color="white" if value < 0.55 else "black",
                fontsize=8,
            )
    fig.colorbar(im, ax=ax, fraction=0.04, pad=0.02, label="feasibility rate")
    _finalise(fig, ax, "Feasibility heatmap (rows: instance, cols: solver)", cfg)
    out = _resolve_path("feasibility_heatmap", out_dir, cfg.prefix)
    fig.savefig(out, dpi=cfg.dpi)
    plt.close(fig)
    return out


def build_objective_breakdown_figure(
    df: pd.DataFrame,
    cfg: GraphicsConfig = GraphicsConfig(),
    out_dir: Path | None = None,
) -> Path:
    """Stacked bars: mean calorie deviation + protein gap per solver."""
    _ensure_columns(
        df,
        ["solver", "feasible", "calorie_deviation_abs", "protein_gap_to_target_g"],
    )
    feas = df[df["feasible"]]
    grouped = feas.groupby("solver").agg(
        cal_dev=("calorie_deviation_abs", "mean"),
        pro_gap=("protein_gap_to_target_g", "mean"),
    )
    solvers = _order_categorical(grouped.index.tolist(), cfg.solver_order)
    grouped = grouped.reindex(solvers).fillna(0.0)

    fig, ax = plt.subplots(figsize=cfg.figsize_small)
    x = np.arange(len(solvers))
    bottom = np.zeros(len(solvers))
    for column, label, color in (
        ("cal_dev", "calorie deviation (|kcal|)", cfg.palette[0]),
        ("pro_gap", "protein gap (g)", cfg.palette[1]),
    ):
        values = grouped[column].to_numpy()
        ax.bar(x, values, bottom=bottom, label=label, color=color)
        bottom = bottom + values
    ax.set_xticks(x)
    ax.set_xticklabels(solvers, rotation=0)
    ax.set_ylabel("stacked deviation")
    ax.legend(fontsize=8)
    if cfg.annotate_bars:
        _annotate(ax, fmt="{:.1f}")
    _finalise(fig, ax, "Average objective breakdown per solver", cfg)
    out = _resolve_path("objective_breakdown", out_dir, cfg.prefix)
    fig.savefig(out, dpi=cfg.dpi)
    plt.close(fig)
    return out


def build_summary_table_figure(
    df: pd.DataFrame,
    cfg: GraphicsConfig = GraphicsConfig(),
    out_dir: Path | None = None,
) -> Path:
    """Render a per-solver summary table as a PNG for easy inclusion in slides."""
    _ensure_columns(df, ["solver", "feasible", "runtime_s", "objective_value"])
    summary = df.groupby("solver").agg(
        runs=("solver", "size"),
        feasibility=("feasible", "mean"),
        mean_runtime_s=("runtime_s", "mean"),
        mean_objective=("objective_value", "mean"),
    ).round(3)
    solvers = _order_categorical(summary.index.tolist(), cfg.solver_order)
    summary = summary.reindex(solvers)

    fig, ax = plt.subplots(figsize=cfg.figsize_wide)
    ax.axis("off")
    table = ax.table(
        cellText=summary.reset_index().to_numpy(),
        colLabels=["solver", "runs", "feasibility", "mean_runtime_s", "mean_objective"],
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(cfg.label_fontsize)
    table.scale(1.0, 1.4)
    ax.set_title("Per-solver summary", fontsize=cfg.title_fontsize)
    out = _resolve_path("summary_table", out_dir, cfg.prefix)
    fig.savefig(out, dpi=cfg.dpi, bbox_inches="tight")
    plt.close(fig)
    return out


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def generate_all(
    df: pd.DataFrame,
    cfg: GraphicsConfig = GraphicsConfig(),
    out_dir: Path | None = None,
) -> list[Path]:
    """Generate every enabled figure and return the list of written paths."""
    builders: list[tuple[bool, object]] = [
        (cfg.include_scaling, build_runtime_scaling_figure),
        (cfg.include_pareto, build_pareto_cost_protein_figure),
        (cfg.include_heatmap, build_feasibility_heatmap_figure),
        (cfg.include_stacked, build_objective_breakdown_figure),
        (cfg.include_summary_table, build_summary_table_figure),
    ]
    outputs: list[Path] = []
    for enabled, builder in builders:
        if not enabled:
            continue
        outputs.append(builder(df, cfg, out_dir))  # type: ignore[operator]
    return outputs


__all__ = [
    "DEFAULT_FIGURES_SUBDIR",
    "EXPECTED_COLUMNS",
    "GraphicsConfig",
    "SOLVER_PALETTE",
    "build_feasibility_heatmap_figure",
    "build_objective_breakdown_figure",
    "build_pareto_cost_protein_figure",
    "build_runtime_scaling_figure",
    "build_summary_table_figure",
    "generate_all",
]
