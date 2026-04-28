"""Derived metrics computed from a :class:`SolverResult`.

These are the numbers the experiment runner writes to CSV and the ones the
report compares across solvers. Keeping this function pure (no solver state,
no I/O) makes it trivial to test and to rerun on a saved plan.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

from src.config.settings import DAYS_PER_WEEK
from src.models.domain import FoodItem, Plan, SolverResult, UserProfile
from src.models.enums import ActivityKind, Intensity


@dataclass
class PlanMetrics:
    feasible: bool
    solver: str
    status: str
    runtime_s: float
    objective_value: float | None

    workouts_scheduled: int
    hard_workouts_scheduled: int
    avg_calories: float
    avg_protein_g: float
    avg_carbs_g: float
    avg_fat_g: float
    total_cost_cents: int
    calorie_deviation_abs: int
    protein_gap_to_target_g: int
    peri_workout_meal_hits: int
    preferred_day_hits: int
    avoid_day_violations: int

    def as_dict(self) -> dict:
        return asdict(self)


def compute_metrics(
    result: SolverResult,
    user: UserProfile,
    foods: list[FoodItem] | None = None,
) -> PlanMetrics:
    """Compute a :class:`PlanMetrics` for a single solver result."""
    base = PlanMetrics(
        feasible=result.feasible,
        solver=result.solver_name,
        status=result.status,
        runtime_s=round(result.runtime_s, 4),
        objective_value=(None if result.objective_value is None
                         else round(result.objective_value, 3)),
        workouts_scheduled=0,
        hard_workouts_scheduled=0,
        avg_calories=0.0,
        avg_protein_g=0.0,
        avg_carbs_g=0.0,
        avg_fat_g=0.0,
        total_cost_cents=0,
        calorie_deviation_abs=0,
        protein_gap_to_target_g=0,
        peri_workout_meal_hits=0,
        preferred_day_hits=0,
        avoid_day_violations=0,
    )
    if not result.feasible or result.plan is None:
        return base

    plan: Plan = result.plan

    # --- nutrition rollups ------------------------------------------------
    n_days = max(1, len(plan.daily_plans))
    base.avg_calories = sum(dp.calories_total for dp in plan.daily_plans) / n_days
    base.avg_protein_g = sum(dp.protein_total_g for dp in plan.daily_plans) / n_days
    base.avg_carbs_g = sum(dp.carbs_total_g for dp in plan.daily_plans) / n_days
    base.avg_fat_g = sum(dp.fat_total_g for dp in plan.daily_plans) / n_days
    base.total_cost_cents = plan.weekly_cost_cents

    # Calorie deviation summed over days, absolute.
    base.calorie_deviation_abs = sum(
        abs(dp.calories_total - user.calorie_target) for dp in plan.daily_plans
    )

    # Protein gap: average per-day shortfall against target.
    base.protein_gap_to_target_g = sum(
        max(0, user.protein_target_g - dp.protein_total_g)
        for dp in plan.daily_plans
    )

    # --- workouts --------------------------------------------------------
    all_workouts = [dp.workouts for dp in plan.daily_plans]
    flat_wks = [w for row in all_workouts for w in row]
    base.workouts_scheduled = len(flat_wks)

    # Count "hard" intensity via detail lookup on schedule blocks (since
    # WorkoutPlacement doesn't carry intensity).
    intensity_by_template = {
        b.details.get("template_id"): b.details.get("intensity")
        for b in plan.schedule_blocks
        if b.kind == ActivityKind.WORKOUT
    }
    base.hard_workouts_scheduled = sum(
        1 for w in flat_wks
        if intensity_by_template.get(w.template_id) in
        {Intensity.HARD.value, Intensity.VERY_HARD.value}
    )

    # --- preference metrics ---------------------------------------------
    pref_days = set(user.preferences.preferred_workout_days)
    avoid_days = set(user.preferences.avoid_workout_days)
    base.preferred_day_hits = sum(1 for w in flat_wks if w.day in pref_days)
    base.avoid_day_violations = sum(1 for w in flat_wks if w.day in avoid_days)

    # --- peri-workout meal hits -----------------------------------------
    pre_w = user.preferences.pre_workout_meal_window_slots
    post_w = user.preferences.post_workout_meal_window_slots
    hits = 0
    for d, dp in enumerate(plan.daily_plans):
        meal_slots = sorted(
            (m.start_slot for m in dp.meals if m.start_slot is not None)
        )
        for wk in dp.workouts:
            for ms in meal_slots:
                diff_pre = wk.start_slot - (ms + 1)   # meal end = ms + 1
                diff_post = ms - wk.end_slot
                if 0 < diff_pre <= pre_w or 0 <= diff_post <= post_w:
                    hits += 1
                    break
    base.peri_workout_meal_hits = hits

    return base
