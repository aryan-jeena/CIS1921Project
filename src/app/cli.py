"""Command-line interface.

Usage (from the project root)::

    python -m src.app.cli demo                        # canned demo run
    python -m src.app.cli solve --preset budget_student --solver joint_cpsat
    python -m src.app.cli experiments --scenarios balanced,lean_bulk

It intentionally uses argparse only: no extra dependency, no framework magic.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.config.settings import FIGURES_DIR, TABLES_DIR
from src.data_ingestion.food_catalog import build_food_catalog
from src.data_ingestion.workouts import load_sample_workouts
from src.evaluation.metrics import compute_metrics
from src.evaluation.validator import validate_plan
from src.experiments.instance_generator import (
    InstanceParams,
    generate_scenario_suite,
    generate_user,
)
from src.experiments.presets import list_presets, load_preset
from src.experiments.runner import run_experiment_suite, run_single
from src.solvers import ALL_SOLVERS
from src.utils.io import ensure_dir, save_json
from src.utils.logging import get_logger
from src.visualization.plots import (
    plot_cost_vs_protein,
    plot_feasibility_rate,
    plot_formulation_comparison,
    plot_macro_achievement,
    plot_runtime_vs_size,
)
from src.visualization.schedule_view import (
    render_schedule_to_figure,
    schedule_to_text,
)

_logger = get_logger("hso.cli")


# ---------------------------------------------------------------------------
# sub-commands
# ---------------------------------------------------------------------------
def _cmd_solve(args: argparse.Namespace) -> int:
    if args.preset:
        user = load_preset(args.preset)
    elif args.scenario:
        user = generate_user(args.scenario, InstanceParams(seed=args.seed))
    else:
        user = generate_user("balanced", InstanceParams(seed=args.seed))

    solver_cls = ALL_SOLVERS[args.solver]
    solver = solver_cls(time_limit_s=args.time_limit)
    foods = build_food_catalog(exclusions=user.dietary_exclusions,
                               include_penn=not args.no_penn)
    workouts = load_sample_workouts()

    print(f"Solving with {args.solver} on {user.name} "
          f"({len(foods)} foods, {len(workouts)} workouts)...")
    result = solver.solve(user, foods, workouts)
    print(f"Status: {result.status}  "
          f"runtime={result.runtime_s:.2f}s  objective={result.objective_value}")

    if result.plan is None:
        print(f"Infeasibility: {result.infeasibility_reason}")
        return 1

    # Validate
    report = validate_plan(result.plan, user)
    if not report.ok:
        print("WARNING -- plan failed hard-constraint validation:")
        for v in report.violations:
            print(f"  * {v}")

    # Metrics
    metrics = compute_metrics(result, user)
    print("\nMetrics:")
    for k, v in metrics.as_dict().items():
        print(f"  {k}: {v}")

    # Text schedule
    print("\n" + schedule_to_text(result.plan))

    # Optional figure
    if args.figure:
        ensure_dir(FIGURES_DIR)
        path = FIGURES_DIR / f"schedule_{user.name}_{args.solver}.png"
        render_schedule_to_figure(result.plan, path)
        print(f"\nSaved schedule figure: {path}")

    # Optional JSON dump
    if args.save_json:
        out = TABLES_DIR / f"solution_{user.name}_{args.solver}.json"
        save_json(result, out)
        print(f"Saved full result JSON: {out}")

    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    """Canned demo: run all three solvers on a balanced scenario."""
    user = generate_user("balanced", InstanceParams(seed=args.seed))
    foods = build_food_catalog(exclusions=user.dietary_exclusions)
    workouts = load_sample_workouts()

    print(f"Demo run on scenario='{user.name}' "
          f"({len(foods)} foods, {len(workouts)} workouts)\n")

    for name, cls in ALL_SOLVERS.items():
        solver = cls(time_limit_s=args.time_limit)
        print(f"--- {name} ---")
        result = solver.solve(user, foods, workouts)
        print(f"status={result.status} runtime={result.runtime_s:.2f}s "
              f"objective={result.objective_value}")
        if result.plan:
            metrics = compute_metrics(result, user)
            print(f"cal_dev_abs={metrics.calorie_deviation_abs}, "
                  f"cost={metrics.total_cost_cents}c, "
                  f"workouts={metrics.workouts_scheduled}, "
                  f"preferred_day_hits={metrics.preferred_day_hits}")
        print()
    return 0


def _cmd_experiments(args: argparse.Namespace) -> int:
    scenarios = args.scenarios.split(",") if args.scenarios else None
    if scenarios:
        instances = [generate_user(s.strip(), InstanceParams(seed=args.seed + i))
                     for i, s in enumerate(scenarios)]
    else:
        instances = generate_scenario_suite(seed=args.seed)
    solvers = args.solvers.split(",") if args.solvers else list(ALL_SOLVERS.keys())

    print(f"Running {len(instances)} instances × {len(solvers)} solvers "
          f"(time_limit={args.time_limit}s)...\n")
    df = run_experiment_suite(
        instances,
        solver_names=solvers,
        time_limit_s=args.time_limit,
        output_prefix=args.prefix,
    )
    if df.empty:
        print("No results.")
        return 1
    print(df[["instance", "solver", "status", "feasible", "runtime_s",
              "objective_value", "calorie_deviation_abs", "workouts_scheduled"]]
          .to_string(index=False))

    # Charts
    ensure_dir(FIGURES_DIR)
    plot_feasibility_rate(df, FIGURES_DIR / f"{args.prefix}_feasibility.png")
    plot_formulation_comparison(df, FIGURES_DIR / f"{args.prefix}_objective.png")
    plot_macro_achievement(df, FIGURES_DIR / f"{args.prefix}_macros.png")
    plot_cost_vs_protein(df, FIGURES_DIR / f"{args.prefix}_cost_vs_protein.png")
    # Scaling plot needs an 'n_foods' column; if absent, fall back.
    plot_runtime_vs_size(df, FIGURES_DIR / f"{args.prefix}_runtime.png")
    print(f"\nFigures written to {FIGURES_DIR}")
    print(f"Tables written to {TABLES_DIR}")
    return 0


def _cmd_presets(args: argparse.Namespace) -> int:
    names = list_presets()
    if not names:
        print("No presets found under configs/presets/.")
        return 1
    print("Available presets:")
    for n in names:
        print(f"  * {n}")
    return 0


# ---------------------------------------------------------------------------
# arg parsing + public entrypoints
# ---------------------------------------------------------------------------
def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hso",
        description="Constraint-Based Training, Nutrition, and Health Schedule Optimizer",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # ---- solve
    sp = sub.add_parser("solve", help="Solve one instance with one solver.")
    sp.add_argument("--preset", help="Preset name under configs/presets/")
    sp.add_argument("--scenario", help="Built-in generator scenario")
    sp.add_argument("--solver", default="joint_cpsat",
                    choices=list(ALL_SOLVERS.keys()))
    sp.add_argument("--time-limit", type=int, default=30,
                    dest="time_limit",
                    help="Max solve time per solver (s)")
    sp.add_argument("--seed", type=int, default=1921)
    sp.add_argument("--no-penn", action="store_true",
                    help="Skip Penn Dining sample (USDA/curated only)")
    sp.add_argument("--figure", action="store_true",
                    help="Save a weekly-schedule PNG under reports/figures/")
    sp.add_argument("--save-json", action="store_true", dest="save_json")
    sp.set_defaults(func=_cmd_solve)

    # ---- demo
    sp = sub.add_parser("demo", help="Run all three solvers on a balanced user.")
    sp.add_argument("--seed", type=int, default=1921)
    sp.add_argument("--time-limit", type=int, default=15, dest="time_limit")
    sp.set_defaults(func=_cmd_demo)

    # ---- experiments
    sp = sub.add_parser("experiments", help="Batch sweep + figures.")
    sp.add_argument("--scenarios", default="",
                    help="Comma-separated scenario names; default is full suite")
    sp.add_argument("--solvers", default="",
                    help="Comma-separated solver names; default is all three")
    sp.add_argument("--time-limit", type=int, default=20, dest="time_limit")
    sp.add_argument("--seed", type=int, default=1921)
    sp.add_argument("--prefix", default="experiment",
                    help="Output filename prefix under reports/")
    sp.set_defaults(func=_cmd_experiments)

    # ---- presets
    sp = sub.add_parser("presets", help="List bundled preset files.")
    sp.set_defaults(func=_cmd_presets)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


# Console-script shim entry points referenced in pyproject.toml
def demo() -> int:
    return main(["demo"])


def solve() -> int:  # pragma: no cover - thin wrapper
    return main(["solve"] + sys.argv[1:])


def experiments() -> int:  # pragma: no cover - thin wrapper
    return main(["experiments"] + sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
