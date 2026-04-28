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
      - ``pantry_dining_hall``    realistic Penn-dining pantry restriction
      - ``mixed_split``           larger workout pool, push/pull/legs preference
      - ``high_volume_athlete``   8+ sessions/week, large search space
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

    if scenario == "pantry_dining_hall":
        # Realistic "what does this Penn student have access to this week" lens.
        # The pantry list is filled in by the caller (``apply_pantry``) because
        # it depends on the loaded food catalog. Here we just configure the
        # *constraints* that make pantry mode interesting: tighter macro fit,
        # de-emphasised cost, slightly smaller meal count.
        profile.goal = Goal.MAINTENANCE
        profile.calorie_target = 2400
        profile.calorie_tolerance = 120
        profile.protein_min_g = 130
        profile.protein_target_g = 160
        profile.weekly_budget_cents = 14_000      # generous; not the binding term
        profile.max_meals_per_day = 3
        profile.enforce_pantry = True             # caller fills pantry_food_ids
        profile.preferences.preferred_split = PreferredSplit.UPPER_LOWER
        return profile

    if scenario == "mixed_split":
        # Larger workout pool with preference signals -- exercises the
        # preferred-split objective term and produces less-uniform schedules.
        profile.goal = Goal.PERFORMANCE
        profile.calorie_target = 2700
        profile.calorie_tolerance = 150
        profile.protein_min_g = 150
        profile.protein_target_g = 180
        profile.workout_count_min = 5
        profile.workout_count_max = 6
        profile.preferences.preferred_split = PreferredSplit.PUSH_PULL_LEGS
        profile.preferences.preferred_workout_days = [0, 1, 3, 4, 5]
        profile.preferences.avoid_workout_days = [6]
        return profile

    if scenario == "high_volume_athlete":
        # Pushes solver: high workout count, tight protein, dense availability.
        profile.goal = Goal.PERFORMANCE
        profile.calorie_target = 3200
        profile.calorie_tolerance = 200
        profile.protein_min_g = 180
        profile.protein_target_g = 220
        profile.carb_target_g = 400
        profile.fat_target_g = 95
        profile.weekly_budget_cents = 22_000
        profile.workout_count_min = 7
        profile.workout_count_max = 9
        profile.max_meals_per_day = 4
        profile.min_protein_per_meal_g = 35
        # Full daytime availability so the solver actually has to schedule
        # 7+ sessions in a meaningful way.
        wins: list[TimeWindow] = []
        for d in range(DAYS_PER_WEEK):
            wins.append(_contiguous_window(d, 12, 8))    # 06:00-10:00
            wins.append(_contiguous_window(d, 22, 10))   # 11:00-16:00
            wins.append(_contiguous_window(d, 34, 8))    # 17:00-21:00
        profile.available_windows = wins
        profile.preferences.preferred_split = PreferredSplit.PUSH_PULL_LEGS
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
        "mixed_split",
        "high_volume_athlete",
        "pantry_dining_hall",
        "impossible_case",
    ]
    return [
        generate_user(s, InstanceParams(seed=seed + i))
        for i, s in enumerate(scenarios)
    ]


def apply_pantry_to_user(
    user: UserProfile,
    foods: list,
    *,
    pantry_size: int = 18,
    seed: int | None = None,
) -> UserProfile:
    """Pin a realistic pantry/dining-hall subset onto an existing profile.

    Useful for instances flagged with ``enforce_pantry=True``: we keep the
    profile's macro-/budget-/availability constraints intact and just sample
    a varied subset of foods that satisfies the dietary exclusions and covers
    breakfast/lunch/dinner. The selection is deterministic given ``seed``.

    The function returns a *copy* of the profile with ``pantry_food_ids`` set;
    no in-place mutation. Callers that want to disable pantry mode can simply
    not call this helper.
    """
    rng = random.Random(seed if seed is not None else hash(user.name) & 0xFFFF)
    eligible = [f for f in foods if f.allowed_for(user.dietary_exclusions)]
    # Sort foods by protein density so the seed always picks high-utility items
    # first, then add randomised lower-tier items for variety.
    eligible.sort(key=lambda f: (-f.protein_g, f.cost_cents))
    head = eligible[: max(8, pantry_size // 2)]
    tail = eligible[max(8, pantry_size // 2):]
    rng.shuffle(tail)
    chosen = head + tail[: max(0, pantry_size - len(head))]
    pantry_ids = [f.id for f in chosen[:pantry_size]]
    return user.model_copy(update={"pantry_food_ids": pantry_ids,
                                   "enforce_pantry": True})


# ---------------------------------------------------------------------------
# Continuous-scaling generator (per check-in feedback)
# ---------------------------------------------------------------------------
def generate_scaling_instances(
    sizes: list[int] | None = None,
    *,
    seed: int = DEFAULT_SEED,
) -> list[tuple[UserProfile, int]]:
    """Yield (user, n_foods_target) pairs for the scaling study.

    The check-in feedback noted the original scaling study used coarse fixed
    sizes (8/16/24/...) that all solved in well under a second. We replace it
    with a denser sweep (10..200 foods, 3..15 workouts) that stresses the
    joint solver. Each user has slightly perturbed targets so the runs are
    not duplicates.

    Returns a list of (UserProfile, target_food_count) tuples; the caller is
    responsible for trimming the actual catalog to ``target_food_count``
    items before solving.
    """
    if sizes is None:
        sizes = [10, 20, 30, 40, 60, 80, 100, 130, 160, 200]
    out: list[tuple[UserProfile, int]] = []
    for i, n in enumerate(sizes):
        user = generate_user(
            "high_volume_athlete" if n >= 100 else "balanced",
            InstanceParams(
                seed=seed + i,
                n_foods=n,
                n_workout_templates=min(15, max(3, n // 8)),
                availability_density=0.55,
                constraint_tightness=0.4,
            ),
        )
        # Mark user.name with the size so the runner can identify it cheaply.
        user.name = f"scale_{n:03d}_{seed + i}"
        out.append((user, n))
    return out
