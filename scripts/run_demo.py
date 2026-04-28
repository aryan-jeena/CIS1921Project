#!/usr/bin/env python3
"""One-command demo: run all three solvers on a balanced scenario.

Usage::

    python scripts/run_demo.py

Prints a comparison table and writes a schedule figure per solver under
``reports/figures/``.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow the script to be run from project root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.app.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(["demo"]))
