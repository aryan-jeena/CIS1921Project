"""Pydantic domain model for the Health Schedule Optimizer.

Everything that crosses a module boundary is one of these types. Solvers
consume a :class:`UserProfile` + a :class:`FoodCatalog`-equivalent (list of
:class:`FoodItem`) + a list of :class:`WorkoutTemplate`, and produce a
:class:`SolverResult`.

We intentionally use integers (minutes, cents, grams, slots) rather than
floats for anything a solver sees: CP-SAT requires integer coefficients, and
it also makes test assertions robust to rounding.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from src.config.settings import DAYS_PER_WEEK, SLOTS_PER_DAY
from src.models.enums import (
    ActivityKind,
    DietaryTag,
    Goal,
    Intensity,
    MealType,
    PreferredSplit,
    WorkoutType,
)


# ---------------------------------------------------------------------------
# Time windows and calendar helpers
# ---------------------------------------------------------------------------
class TimeWindow(BaseModel):
    """A contiguous half-open slot window ``[start_slot, end_slot)`` on one day.

    ``day`` is 0=Monday..6=Sunday. ``start_slot`` and ``end_slot`` are in
    0..48 (the 48 marker represents end-of-day). Stage-2 and joint solvers
    use these to build availability masks.
    """

    day: int = Field(ge=0, le=DAYS_PER_WEEK - 1)
    start_slot: int = Field(ge=0, le=SLOTS_PER_DAY)
    end_slot: int = Field(ge=0, le=SLOTS_PER_DAY)

    @model_validator(mode="after")
    def _check_order(self) -> "TimeWindow":
        if self.end_slot <= self.start_slot:
            raise ValueError(
                f"TimeWindow end_slot ({self.end_slot}) must exceed start_slot "
                f"({self.start_slot}) on day {self.day}"
            )
        return self

    @property
    def duration(self) -> int:
        """Duration of this window in slots."""
        return self.end_slot - self.start_slot


# ---------------------------------------------------------------------------
# Food catalog
# ---------------------------------------------------------------------------
class FoodItem(BaseModel):
    """A single food line in the catalog.

    Macros are per *serving*, not per 100g. Cost is in integer cents so all
    objectives remain in integer arithmetic. ``max_servings_per_day`` caps how
    often the solver can pile on the same item.
    """

    id: str
    name: str
    calories: int = Field(ge=0)
    protein_g: int = Field(ge=0)
    carbs_g: int = Field(ge=0)
    fat_g: int = Field(ge=0)
    sodium_mg: int = Field(ge=0, default=0)
    cost_cents: int = Field(ge=0)
    meal_types: list[MealType] = Field(default_factory=list, validate_default=True)
    dietary_tags: list[DietaryTag] = Field(default_factory=list)
    source: str = "sample"              # "penn_dining" | "usda" | "sample"
    convenience: int = Field(ge=0, le=10, default=5)
    max_servings_per_day: int = Field(ge=1, default=3)

    @field_validator("meal_types", mode="before")
    @classmethod
    def _default_meal_types(cls, v):
        # If no meal_types provided, food is generic-purpose (any meal).
        if not v:
            return [MealType.BREAKFAST, MealType.LUNCH, MealType.DINNER, MealType.SNACK]
        return v

    def allowed_for(self, exclusions: list[DietaryTag]) -> bool:
        """Return True if this food satisfies a dietary-exclusion list."""
        tags = set(self.dietary_tags)
        return not tags.intersection(exclusions)


# ---------------------------------------------------------------------------
# Workouts
# ---------------------------------------------------------------------------
class WorkoutTemplate(BaseModel):
    """A reusable workout definition. The solver places copies of these in
    the week. ``duration_slots`` includes warm-up + main + cool-down."""

    id: str
    name: str
    workout_type: WorkoutType
    intensity: Intensity
    duration_slots: int = Field(ge=1, le=SLOTS_PER_DAY)
    min_recovery_slots: int = Field(ge=0, default=0)
    preferred_time_of_day: Optional[str] = None    # "morning"/"evening"/...
    description: str = ""

    @property
    def is_hard(self) -> bool:
        return self.intensity in {Intensity.HARD, Intensity.VERY_HARD}


# ---------------------------------------------------------------------------
# Preferences and rules
# ---------------------------------------------------------------------------
class SleepRule(BaseModel):
    """Sleep requirements. The solver reserves one contiguous sleep block per
    night. ``earliest_bedtime_slot`` and ``latest_wake_slot`` together define
    the window in which the block must lie (crossing midnight is allowed)."""

    min_hours: float = Field(ge=0, le=24, default=7.0)
    earliest_bedtime_slot: int = Field(ge=0, le=SLOTS_PER_DAY, default=42)   # 21:00
    latest_wake_slot: int = Field(ge=0, le=SLOTS_PER_DAY, default=16)        # 08:00


class RecoveryRule(BaseModel):
    """Minimum gap between two ``is_hard`` workouts."""

    min_gap_slots: int = Field(ge=0, default=24)    # 12h gap default
    max_consecutive_hard_days: int = Field(ge=1, default=2)


class HydrationRule(BaseModel):
    """Hydration reminders placed as single-slot events.

    The joint CP-SAT solver schedules these as integer events on the time
    grid with a min-spacing constraint between consecutive reminders on the
    same day. Missed reminders accrue a soft penalty rather than infeasibility.
    ``enabled`` lets the user turn the feature off entirely without editing
    presets, which is helpful when comparing solver variants.
    """

    enabled: bool = True
    target_reminders_per_day: int = Field(ge=0, default=6)
    min_spacing_slots: int = Field(ge=1, default=4)        # 2h apart at 30-min slots
    earliest_slot: int = Field(ge=0, le=SLOTS_PER_DAY, default=14)   # 07:00
    latest_slot: int = Field(ge=0, le=SLOTS_PER_DAY, default=42)     # 21:00


class UserPreferences(BaseModel):
    """Soft-objective preferences (violations cost penalty, never infeasible)."""

    preferred_workout_days: list[int] = Field(default_factory=list)
    avoid_workout_days: list[int] = Field(default_factory=list)
    preferred_split: Optional[PreferredSplit] = None
    preferred_meals_per_day: int = Field(ge=1, default=3)
    wants_pre_workout_meal: bool = True
    wants_post_workout_meal: bool = True
    pre_workout_meal_window_slots: int = 6        # within 3h before workout
    post_workout_meal_window_slots: int = 4       # within 2h after workout
    preferred_morning_slot: int = 14              # 07:00 - used by convenience checks


# ---------------------------------------------------------------------------
# User profile (main solver input)
# ---------------------------------------------------------------------------
class UserProfile(BaseModel):
    """Complete, solver-ready description of a single user for one week.

    Anything a solver needs lives here; everything the solver is free to
    decide lives in :class:`Plan`. The instance generator, the presets, and
    the Streamlit form all converge on this type.
    """

    name: str
    goal: Goal = Goal.MAINTENANCE

    # Macro targets -----------------------------------------------------------
    calorie_target: int = 2400
    calorie_tolerance: int = 150              # +/- allowed per day
    protein_min_g: int = 140                  # hard floor per day
    protein_target_g: int = 170               # soft target per day
    carb_target_g: int = 260
    fat_target_g: int = 80
    min_protein_per_meal_g: int = 25

    # Budget ------------------------------------------------------------------
    weekly_budget_cents: int = 12_000

    # Dietary -----------------------------------------------------------------
    dietary_exclusions: list[DietaryTag] = Field(default_factory=list)

    # Pantry / dining-hall access --------------------------------------------
    # When ``pantry_food_ids`` is non-empty the solver may only choose from
    # those food ids. This is the "what does the user actually have access to
    # this week" lens recommended in check-in feedback: planning around food
    # the user can't buy or cook is unrealistic, and once we restrict to a
    # known pantry the cost objective becomes secondary (you've already paid
    # for the dining-hall swipe / what's in the fridge).
    pantry_food_ids: list[str] = Field(default_factory=list)
    enforce_pantry: bool = False

    # Availability ------------------------------------------------------------
    available_windows: list[TimeWindow] = Field(default_factory=list)

    # Meals -------------------------------------------------------------------
    max_meals_per_day: int = 4
    meal_windows: dict[MealType, list[TimeWindow]] = Field(default_factory=dict)

    # Workouts ----------------------------------------------------------------
    workout_count_min: int = 3
    workout_count_max: int = 6
    candidate_workouts: list[str] = Field(default_factory=list)   # template ids

    # Rules -------------------------------------------------------------------
    sleep: SleepRule = Field(default_factory=SleepRule)
    recovery: RecoveryRule = Field(default_factory=RecoveryRule)
    hydration: HydrationRule = Field(default_factory=HydrationRule)
    preferences: UserPreferences = Field(default_factory=UserPreferences)

    # Solver hints ------------------------------------------------------------
    time_limit_s: int = 30
    log_search: bool = False

    def availability_mask(self) -> list[list[bool]]:
        """Return a 7×48 boolean matrix: True iff the user is available then."""
        mask = [[False] * SLOTS_PER_DAY for _ in range(DAYS_PER_WEEK)]
        for w in self.available_windows:
            for s in range(w.start_slot, w.end_slot):
                mask[w.day][s] = True
        return mask

    def filter_pantry(self, foods: list["FoodItem"]) -> list["FoodItem"]:
        """Restrict ``foods`` to the user's pantry/dining-hall access list.

        Returns ``foods`` unchanged when ``enforce_pantry`` is False or the id
        list is empty. Otherwise returns only the items the user has access to,
        preserving original order. Used by every solver before any modeling
        work so the formulations stay comparable.
        """
        if not self.enforce_pantry or not self.pantry_food_ids:
            return list(foods)
        wanted = set(self.pantry_food_ids)
        return [f for f in foods if f.id in wanted]


# ---------------------------------------------------------------------------
# Plan output
# ---------------------------------------------------------------------------
class ScheduleBlock(BaseModel):
    """A placed activity in the weekly grid. Produced by the scheduler /
    joint solver; consumed by the validator and the UI."""

    day: int
    start_slot: int
    end_slot: int
    kind: ActivityKind
    label: str
    details: dict = Field(default_factory=dict)

    @property
    def duration(self) -> int:
        return self.end_slot - self.start_slot


class MealPlacement(BaseModel):
    """A concrete meal on a given day, with food servings and placement.

    ``food_servings`` is ``{food_id: servings_int}``. The scheduler uses
    ``start_slot`` / ``end_slot`` (a single 30-min slot by default) to emit
    a matching :class:`ScheduleBlock`."""

    day: int
    meal_type: MealType
    food_servings: dict[str, int]
    start_slot: Optional[int] = None
    end_slot: Optional[int] = None


class WorkoutPlacement(BaseModel):
    template_id: str
    day: int
    start_slot: int
    end_slot: int


class DailyPlan(BaseModel):
    day: int
    meals: list[MealPlacement] = Field(default_factory=list)
    workouts: list[WorkoutPlacement] = Field(default_factory=list)
    sleep_start_slot: Optional[int] = None
    sleep_end_slot: Optional[int] = None
    calories_total: int = 0
    protein_total_g: int = 0
    carbs_total_g: int = 0
    fat_total_g: int = 0
    cost_cents: int = 0


class Plan(BaseModel):
    """A full weekly plan: 7 daily plans plus a flat list of schedule blocks
    ready to render. Shared by all three solvers."""

    user_name: str
    daily_plans: list[DailyPlan] = Field(default_factory=list)
    schedule_blocks: list[ScheduleBlock] = Field(default_factory=list)
    weekly_cost_cents: int = 0


class SolverResult(BaseModel):
    """Standard solver return object. One shape across all formulations so
    the experiment runner doesn't care which solver produced it."""

    solver_name: str
    status: str                  # "OPTIMAL" | "FEASIBLE" | "INFEASIBLE" | "TIMEOUT" | "ERROR"
    objective_value: Optional[float] = None
    runtime_s: float = 0.0
    plan: Optional[Plan] = None
    infeasibility_reason: Optional[str] = None
    extras: dict = Field(default_factory=dict)

    @property
    def feasible(self) -> bool:
        return self.status in {"OPTIMAL", "FEASIBLE"}
