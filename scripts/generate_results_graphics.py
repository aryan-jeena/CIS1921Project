#!/usr/bin/env python3
"""Build report-oriented figures from an experiment results CSV.

Usage::

    python scripts/generate_results_graphics.py \
        --input reports/tables/checkin_long.csv \
        --out-dir reports/figures/results_graphics \
        --config configs/results_graphics.json

The script is deliberately decoupled from the default experiment runner so
you can regenerate publication-ready figures without re-running any solver.
It never mutates solver or experiment code; it only writes PNGs under the
chosen output directory.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make ``src.*`` importable when running this file directly, mirroring the
# convention already used by the other scripts in this folder.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd  # noqa: E402

from src.visualization.results_graphics import (  # noqa: E402
    GraphicsConfig,
    generate_all,
)


DEFAULT_INPUT = Path("reports/tables/checkin_long.csv")
DEFAULT_OUT_DIR = Path("reports/figures/results_graphics")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate report-ready figures from a long-format experiment "
            "results CSV (same schema produced by run_experiments.py)."
        ),
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Path to results CSV (default: {DEFAULT_INPUT}).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help=f"Directory to write PNGs into (default: {DEFAULT_OUT_DIR}).",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help=(
            "Optional JSON file matching GraphicsConfig fields "
            "(see configs/results_graphics.json for an example)."
        ),
    )
    parser.add_argument(
        "--prefix",
        type=str,
        default=None,
        help="Override the output filename prefix (default: 'results').",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved plan without writing any files.",
    )
    return parser.parse_args(argv)


def _load_config(path: Path | None) -> GraphicsConfig:
    if path is None:
        return GraphicsConfig()
    if not path.exists():
        raise SystemExit(f"Config file does not exist: {path}")
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    return GraphicsConfig.from_mapping(payload)


def _load_results(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise SystemExit(
            f"Results CSV not found at {path}. "
            "Run scripts/run_experiments.py first, or pass --input."
        )
    return pd.read_csv(path)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    cfg = _load_config(args.config)
    if args.prefix:
        # Dataclass is frozen; rebuild via from_mapping so the override sticks.
        cfg = GraphicsConfig.from_mapping({**cfg.__dict__, "prefix": args.prefix})

    if args.dry_run:
        print("== dry run ==")
        print(f"input    : {args.input}")
        print(f"out_dir  : {args.out_dir}")
        print(f"prefix   : {cfg.prefix}")
        print("enabled  :")
        for flag in (
            "include_scaling",
            "include_pareto",
            "include_heatmap",
            "include_stacked",
            "include_summary_table",
        ):
            print(f"  - {flag} = {getattr(cfg, flag)}")
        return 0

    df = _load_results(args.input)
    outputs = generate_all(df, cfg=cfg, out_dir=args.out_dir)
    print(f"Wrote {len(outputs)} figures to {args.out_dir}:")
    for path in outputs:
        print(f"  - {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
