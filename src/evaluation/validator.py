"""Hard-constraint validator run on a returned plan.

Purpose: even if a solver *claims* feasibility, we re-check the plan against
the user's hard constraints. This catches model bugs and is cheap to run,
so the experiment runner invokes it on every result.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.config.settings import DAYS_PER_WEEK
from src.models.domain import Plan, UserProfile
from src.models.enums import ActivityKind


@dataclass
class ValidationReport:
    ok: bool
    violations: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.ok


def validate_plan(plan: Plan, user: UserProfile) -> ValidationReport:
    """Check a plan against the user's *hard* constraints.

    Returns an :class:`ValidationReport` with ``ok=True`` iff every hard
    constraint passes.
    """
    violations: list[str] = []

    # -- daily calorie band
    for dp in plan.daily_plans:
        if dp.calories_total == 0:
            continue  # nutrition-only solver may leave this unfilled
        lo = user.calorie_target - user.calorie_tolerance
        hi = user.calorie_target + user.calorie_tolerance
        if not (lo <= dp.calories_total <= hi):
            violations.append(
                f"Day {dp.day}: calories {dp.calories_total} outside band [{lo}, {hi}]."
            )
        if dp.protein_total_g < user.protein_min_g and dp.calories_total > 0:
            violations.append(
                f"Day {dp.day}: protein {dp.protein_total_g}g below floor {user.protein_min_g}g."
            )

    # -- weekly budget
    if plan.weekly_cost_cents > user.weekly_budget_cents:
        violations.append(
            f"Weekly cost {plan.weekly_cost_cents}c exceeds budget "
            f"{user.weekly_budget_cents}c."
        )

    # -- workout count
    flat_wks = [w for dp in plan.daily_plans for w in dp.workouts]
    if flat_wks:
        if len(flat_wks) < user.workout_count_min:
            violations.append(
                f"Only {len(flat_wks)} workouts scheduled; minimum is "
                f"{user.workout_count_min}."
            )
        if len(flat_wks) > user.workout_count_max:
            violations.append(
                f"{len(flat_wks)} workouts scheduled; maximum is "
                f"{user.workout_count_max}."
            )

    # -- non-overlap per day
    for dp in plan.daily_plans:
        intervals: list[tuple[int, int, str]] = []
        for m in dp.meals:
            if m.start_slot is not None:
                intervals.append((m.start_slot, m.end_slot or m.start_slot + 1, "meal"))
        for w in dp.workouts:
            intervals.append((w.start_slot, w.end_slot, "workout"))
        if dp.sleep_start_slot is not None:
            intervals.append((dp.sleep_start_slot, dp.sleep_end_slot or dp.sleep_start_slot + 1, "sleep"))
        intervals.sort()
        for (a_s, a_e, a_k), (b_s, b_e, b_k) in zip(intervals, intervals[1:]):
            if a_e > b_s:
                violations.append(
                    f"Day {dp.day}: overlap between {a_k} [{a_s},{a_e}) and "
                    f"{b_k} [{b_s},{b_e})."
                )

    return ValidationReport(ok=not violations, violations=violations)
