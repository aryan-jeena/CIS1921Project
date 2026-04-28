#!/usr/bin/env python3
"""One-command Streamlit UI launcher.

Usage::

    python scripts/launch_ui.py

Equivalent to ``streamlit run src/app/streamlit_app.py``; this wrapper just
adds the project root to ``sys.path`` first so imports resolve when running
from any directory.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    os.environ["PYTHONPATH"] = f"{root}{os.pathsep}{os.environ.get('PYTHONPATH', '')}"
    try:
        from streamlit.web import cli as stcli  # type: ignore
    except ImportError:
        print("Streamlit not installed. `pip install -r requirements.txt`.",
              file=sys.stderr)
        return 1
    sys.argv = ["streamlit", "run", "src/app/streamlit_app.py"]
    return stcli.main()


if __name__ == "__main__":
    raise SystemExit(main())
