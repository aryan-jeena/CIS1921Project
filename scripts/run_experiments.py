#!/usr/bin/env python3
"""One-command batch sweep across scenarios and solvers.

Writes tables + figures under ``reports/``. Usage::

    python scripts/run_experiments.py                   # default suite
    python scripts/run_experiments.py --time-limit 30
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.app.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(["experiments"] + sys.argv[1:]))
