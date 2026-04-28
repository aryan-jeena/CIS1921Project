"""Paths, time granularity, and scoring weights.

Design notes
------------
The whole project uses a fixed temporal discretization:

    1 day  = 48 half-hour slots
    1 week = 7 * 48 = 336 slots

Slot 0 of each day is midnight. Slot 47 ends at 23:30. This granularity is
coarse enough to keep CP-SAT tractable on a course-sized laptop while still
expressing realistic schedules (meals, 30- to 90-min lifts, multi-hour sleep
blocks, recovery spacing, etc.). All durations declared elsewhere in the
project are expressed in *slots*.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Filesystem layout
# ---------------------------------------------------------------------------
ROOT: Path = Path(__file__).resolve().parents[2]
DATA_DIR: Path = ROOT / "data"
SAMPLE_DIR: Path = DATA_DIR / "sample"
PROCESSED_DIR: Path = DATA_DIR / "processed"
RAW_DIR: Path = DATA_DIR / "raw"
PRESETS_DIR: Path = ROOT / "configs" / "presets"
REPORTS_DIR: Path = ROOT / "reports"
FIGURES_DIR: Path = REPORTS_DIR / "figures"
TABLES_DIR: Path = REPORTS_DIR / "tables"

# ---------------------------------------------------------------------------
# Time grid
# ---------------------------------------------------------------------------
MINUTES_PER_SLOT: int = 30
SLOTS_PER_DAY: int = 24 * 60 // MINUTES_PER_SLOT          # 48
DAYS_PER_WEEK: int = 7
SLOTS_PER_WEEK: int = SLOTS_PER_DAY * DAYS_PER_WEEK       # 336

# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------
DEFAULT_SEED: int = 1921


# ---------------------------------------------------------------------------
# Objective weights
# ---------------------------------------------------------------------------
@dataclass
class ScoringWeights:
    """Weights for terms that appear in every solver's objective.

    CP-SAT works over integers, so these values are stored as ints and all
    deviations are converted to integers (grams, cents, slots) upstream.

    Attributes
    ----------
    calorie_deviation : int
        Penalty per kcal away from the target (both directions).
    protein_deviation : int
        Penalty per gram of protein *below* minimum (we do not penalize
        going *over* protein).
    macro_deviation : int
        Penalty per gram of carb/fat absolute deviation from target.
    cost_weight : int
        Penalty per cent of food cost.
    preference_violation : int
        Penalty for ignoring a preferred workout day / split.
    meal_timing_violation : int
        Penalty for failing to place a meal near a workout when requested.
    fragmentation : int
        Penalty per pair of adjacent activity/idle boundaries.
    protein_per_meal_shortfall : int
        Penalty per gram below a minimum-protein-per-meal threshold.
    hydration_shortfall : int
        Penalty per missed hydration reminder.
    """

    calorie_deviation: int = 1
    protein_deviation: int = 20
    macro_deviation: int = 2
    cost_weight: int = 1
    preference_violation: int = 100
    meal_timing_violation: int = 50
    fragmentation: int = 5
    protein_per_meal_shortfall: int = 10
    hydration_shortfall: int = 5

    def as_dict(self) -> dict[str, int]:
        return {
            "calorie_deviation": self.calorie_deviation,
            "protein_deviation": self.protein_deviation,
            "macro_deviation": self.macro_deviation,
            "cost_weight": self.cost_weight,
            "preference_violation": self.preference_violation,
            "meal_timing_violation": self.meal_timing_violation,
            "fragmentation": self.fragmentation,
            "protein_per_meal_shortfall": self.protein_per_meal_shortfall,
            "hydration_shortfall": self.hydration_shortfall,
        }


DEFAULT_WEIGHTS: ScoringWeights = ScoringWeights()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def slot_to_time(slot: int) -> str:
    """Format a slot index (0..47) as ``HH:MM``."""
    minutes = slot * MINUTES_PER_SLOT
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def time_to_slot(hour: int, minute: int = 0) -> int:
    """Convert a wall-clock time to a slot index (floor)."""
    return (hour * 60 + minute) // MINUTES_PER_SLOT


DAY_NAMES: tuple[str, ...] = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
