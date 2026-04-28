"""Parameterized synthetic instance generator.

The generator produces :class:`UserProfile` instances along a configurable
difficulty axis. It supports specific *scenarios* (budget_student,
lean_bulk, aggressive_cut, vegetarian_athlete, tight_class_schedule,
early_morning_lifter, recovery_constrained, impossible_case) as well as
parameterized scaling for the experiment sweep.

Determinism
-----------
Every public function takes a ``seed``. Same seed -> same instance. The
experiment runner uses this to make results reproducible across machines.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterable

from src.config.settings import DAYS_PER_WEEK, SLOTS_PER_DAY, DEFAULT_SEED
from src.models.domain import (
    RecoveryRule,
    SleepRule,
    TimeWindow,
    UserPreferences,
    UserProfile,
)
from src.models.enums import DietaryTag, Goal, MealType, PreferredSplit


# ---------------------------------------------------------------------------
# Parameter dataclass for sweeps
# ---------------------------------------------------------------------------
@dataclass
class InstanceParams:
    """Parameters for a single instance draw.

    Used by the experiment runner to sweep across difficulty:

    - ``n_foods``           how many foods to keep in the catalog
    - ``n_workout_templates`` how many workouts remain as candidates
    - ``availability_density`` 0..1 fraction of the week marked available
    - ``constraint_tightness`` 0..1 : tighter budget, smaller calorie
                                       tolerance, higher protein target
    - ``seed``              RNG seed
    """

    n_foods: int = 30
    n_workout_templates: int = 6
    availability_density: float = 0.45
    constraint_tightness: float = 0.5
    seed: int = DEFAULT_SEED


# ---------------------------------------------------------------------------
# Scenario recipes (named presets returned as UserProfile)
# ---------------------------------------------------------------------------
def _contiguous_window(day: int, start: int, length: int) -> TimeWindow:
    end = min(SLOTS_PER_DAY, start + length)
    return TimeWindow(day=day, start_slot=start, end_slot=end)


def _typical_student_availability(rng: random.Random, density: float = 0.5) -> list[TimeWindow]:
    """Roughly plausible student weekly availability.

    We always include the late-morning free block (post-breakfast) and the
    evening, and randomly carve out class times during the midday window.
    ``density`` scales how much free time we keep.
    """
    windows: list[TimeWindow] = []
    for d in range(DAYS_PER_WEEK):
        # Morning 07:00-09:00
        windows.append(_contiguous_window(d, 14, 4))
        # Midday 12:00-14:00 maybe
        if rng.random() < density + 0.3:
            windows.append(_contiguous_window(d, 24, 4))
        # Late afternoon 15:00-19:00
        if rng.random() < density + 0.4:
            windows.append(_contiguous_window(d, 30, 8))
        # Evening 19:30-21:00
        windows.append(_contiguous_window(d, 39, 3))
    return windows


def generate_user(
    scenario: str = "balanced",
    params: InstanceParams | None = None,
) -> UserProfile:
    """Produce a :class:`UserProfile` for a named scenario.

    ``scenario`` is one of:
      - ``balanced``             default; feasible with any solver
      - ``budget_student``        tight budget, lots of availability
      - ``lean_bulk``             high protein target
      - ``aggressive_cut``        low calorie, strict protein
      - ``vegetarian_athlete``    vegetarian + high protein
      - ``tight_class_schedule``  narrow availability windows
      - ``early_morning_lifter``  all workouts before 09:00
      - ``recovery_constrained``  long min recovery gap
      - ``impossible_case``       intentionally infeasible
    """
    params = params or InstanceParams()
    rng = random.Random(params.seed)

    profile = UserProfile(
        name=f"{scenario}_{params.seed}",
        goal=Goal.MAINTENANCE,
        calorie_target=2400,
        calorie_tolerance=int(200 * (1 - params.constraint_tightness) + 80),
        protein_min_g=120,
        protein_target_g=160,
        carb_target_g=260,
        fat_target_g=80,
        weekly_budget_cents=int(
            16_000 - 6_000 * params.constraint_tightness
        ),
        max_meals_per_day=4,
        workout_count_min=3,
        workout_count_max=6,
        available_windows=_typical_student_availability(rng, params.availability_density),
        preferences=UserPreferences(
            preferred_workout_days=[0, 2, 4],
            preferred_split=PreferredSplit.FULL_BODY,
        ),
    )

    if scenario == "balanced":
        return profile

    if scenario == "budget_student":
        profile.goal = Goal.MAINTENANCE
        profile.weekly_budget_cents = 4000
        profile.calorie_target = 2200
        profile.protein_min_g = 110
        profile.protein_target_g = 140
        return profile

    if scenario == "lean_bulk":
        profile.goal = Goal.LEAN_BULK
        profile.calorie_target = 3000
        profile.calorie_tolerance = 150
        profile.protein_min_g = 160
        profile.protein_target_g = 200
        profile.carb_target_g = 360
        profile.fat_target_g = 90
        profile.weekly_budget_cents = 16_000
        profile.workout_count_min = 4
        profile.workout_count_max = 6
        profile.preferences.preferred_split = PreferredSplit.UPPER_LOWER
        return profile

    if scenario == "aggressive_cut":
        profile.goal = Goal.CUT
        profile.calorie_target = 1800
        profile.calorie_tolerance = 100
        profile.protein_min_g = 160
        profile.protein_target_g = 180
        profile.carb_target_g = 160
        profile.fat_target_g = 55
        profile.weekly_budget_cents = 9000
        profile.max_meals_per_day = 4
        profile.min_protein_per_meal_g = 30
        return profile

    if scenario == "vegetarian_athlete":
        profile.dietary_exclusions = [
            DietaryTag.CONTAINS_BEEF,
            DietaryTag.CONTAINS_PORK,
            DietaryTag.CONTAINS_SHELLFISH,
        ]
        profile.goal = Goal.PERFORMANCE
        profile.protein_min_g = 140
        profile.protein_target_g = 170
        profile.min_protein_per_meal_g = 30
        profile.workout_count_min = 4
        profile.preferences.preferred_split = PreferredSplit.PUSH_PULL_LEGS
        return profile

    if scenario == "tight_class_schedule":
        # Replace availability with narrow 1-2h windows only.
        wins: list[TimeWindow] = []
        for d in range(DAYS_PER_WEEK):
            wins.append(_contiguous_window(d, 14, 3))        # 07:00-08:30
            wins.append(_contiguous_window(d, 36, 5))        # 18:00-20:30
        profile.available_windows = wins
        profile.workout_count_min = 3
        profile.workout_count_max = 4
        return profile

    if scenario == "early_morning_lifter":
        wins: list[TimeWindow] = []
        for d in range(DAYS_PER_WEEK):
            wins.append(_contiguous_window(d, 10, 8))        # 05:00-09:00
            wins.append(_contiguous_window(d, 36, 6))        # 18:00-21:00
        profile.available_windows = wins
        profile.preferences.preferred_morning_slot = 10
        profile.workout_count_min = 4
        profile.preferences.avoid_workout_days = [5, 6]
        return profile

    if scenario == "recovery_constrained":
        profile.recovery = RecoveryRule(min_gap_slots=48, max_consecutive_hard_days=1)
        profile.workout_count_min = 3
        profile.workout_count_max = 4
        return profile

    if scenario == "impossible_case":
        # Impossible macro combination + no budget + no availability.
        profile.calorie_target = 1800
        profile.calorie_tolerance = 30
        profile.protein_min_g = 260
        profile.protein_target_g = 300
        profile.weekly_budget_cents = 1500
        profile.workout_count_min = 7
        profile.workout_count_max = 7
        profile.available_windows = [_contiguous_window(0, 14, 2)]
        profile.sleep = SleepRule(min_hours=9, earliest_bedtime_slot=42, latest_wake_slot=18)
        return profile

    # Unknown scenario falls back to balanced with a warning in the name.
    profile.name = f"unknown_{scenario}_{params.seed}"
    return profile


def generate_scenario_suite(
    seed: int = DEFAULT_SEED,
) -> list[UserProfile]:
    """Return one instance of each named scenario. Used by the demo & report."""
    scenarios = [
        "balanced",
        "budget_student",
        "lean_bulk",
        "aggressive_cut",
        "vegetarian_athlete",
        "tight_class_schedule",
        "early_morning_lifter",
        "recovery_constrained",
        "impossible_case",
    ]
    return [
        generate_user(s, InstanceParams(seed=seed + i))
        for i, s in enumerate(scenarios)
    ]
