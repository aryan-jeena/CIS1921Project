#!/usr/bin/env bash
# Paced narration of the demo, sized for a ~75-second screen recording.
# Usage:
#   1. Resize your terminal to ~120x36 chars and clear it.
#   2. cmd+shift+5 → Record Selected Portion → drag over the terminal window.
#   3. Click Record.
#   4. Run:    bash scripts/record_demo.sh
#   5. When the script finishes, stop the recording (button in menu bar).
#
# Save the resulting .mov as: reports/presentation/demo_video.mov
set -euo pipefail

# Activate the venv if one exists in this repo
if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

CAPTION() { printf "\n\033[1;33m# %s\033[0m\n" "$*"; sleep 1.2; }
PROMPT()  { printf "\033[1;36m$\033[0m %s\n" "$*"; sleep 0.6; }

clear
printf "\033[1;37mCIS 1921 Final Project — Constraint-Based Schedule Optimizer\033[0m\n"
printf "\033[2;37mAryan Jeena · Aadithya Srinivasan\033[0m\n"
sleep 2

# 1 -----------------------------------------------------------------------
CAPTION "1. Run all four solvers on the balanced scenario."
PROMPT "python scripts/run_demo.py"
python scripts/run_demo.py
sleep 4

# 2 -----------------------------------------------------------------------
CAPTION "2. Solve the lean_bulk preset with the joint CP-SAT solver."
PROMPT "python -m src.app.cli solve --preset lean_bulk --solver joint_cpsat --time-limit 8 --figure"
python -m src.app.cli solve --preset lean_bulk --solver joint_cpsat --time-limit 8 --figure | tail -28
sleep 4

# 3 -----------------------------------------------------------------------
CAPTION "3. Confirm the test suite is green."
PROMPT "pytest -q"
pytest -q
sleep 3

# 4 -----------------------------------------------------------------------
CAPTION "4. Open the generated weekly schedule figure."
LAST_FIG="$(ls -t reports/figures/*.png 2>/dev/null | head -1 || true)"
if [ -n "${LAST_FIG:-}" ]; then
  PROMPT "open '${LAST_FIG}'"
  open "${LAST_FIG}"
else
  PROMPT "ls reports/figures/results_graphics/"
  ls reports/figures/results_graphics/ | head
fi
sleep 4

printf "\n\033[1;32m# Demo complete — stop the recording now.\033[0m\n"
