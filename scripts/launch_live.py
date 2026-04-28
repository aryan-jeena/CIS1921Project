#!/usr/bin/env python3
"""Launch the live optimization viewer.

Opens a browser tab at http://127.0.0.1:5050/ where you can pick a preset
and watch the joint CP-SAT solver search in real time. Each intermediate
solution is streamed to the page as a Server-Sent Event and the weekly
schedule grid animates as blocks are placed and rearranged.

Usage::

    python scripts/launch_live.py
    python scripts/launch_live.py --port 5051   # different port
    python scripts/launch_live.py --no-open     # don't auto-open browser
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.app.live_server import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
