"""Unit tests for the validator and metrics helpers against hand-made plans."""
from __future__ import annotations

from src.config.settings import DAYS_PER_WEEK
from src.evaluation.metrics import compute_metrics
from src.evaluation.validator import validate_plan
from src.experiments.instance_generator import generate_user
from src.models.domain import (
    DailyPlan,
    MealPlacement,
    Plan,
    ScheduleBlock,
    SolverResult,
    WorkoutPlacement,
)
from src.models.enums import ActivityKind, Intensity, MealType


def _empty_plan(user):
    daily = []
    for d in range(DAYS_PER_WEEK):
        daily.append(DailyPlan(day=d, calories_total=user.calorie_target,
                               protein_total_g=user.protein_min_g,
                               carbs_total_g=user.carb_target_g,
                               fat_total_g=user.fat_target_g,
                               cost_cents=0))
    return Plan(user_name=user.name, daily_plans=daily, schedule_blocks=[],
                weekly_cost_cents=0)


def test_validator_accepts_compliant_plan():
    user = generate_user("balanced")
    plan = _empty_plan(user)
    report = validate_plan(plan, user)
    assert report.ok


def test_validator_detects_overlap():
    user = generate_user("balanced")
    plan = _empty_plan(user)
    # Add overlapping meal + workout on day 0
    plan.daily_plans[0].meals.append(MealPlacement(
        day=0, meal_type=MealType.LUNCH, food_servings={},
        start_slot=24, end_slot=26,
    ))
    plan.daily_plans[0].workouts.append(WorkoutPlacement(
        template_id="full_body_a", day=0, start_slot=25, end_slot=28,
    ))
    report = validate_plan(plan, user)
    assert not report.ok
    assert any("overlap" in v for v in report.violations)


def test_validator_detects_budget_bust():
    user = generate_user("budget_student")
    plan = _empty_plan(user)
    plan.weekly_cost_cents = user.weekly_budget_cents + 1000
    report = validate_plan(plan, user)
    assert not report.ok
    assert any("budget" in v for v in report.violations)


def test_metrics_handles_infeasible_result():
    user = generate_user("balanced")
    res = SolverResult(solver_name="x", status="INFEASIBLE")
    m = compute_metrics(res, user)
    assert not m.feasible
    assert m.workouts_scheduled == 0


def test_metrics_counts_hard_workouts():
    user = generate_user("balanced")
    plan = _empty_plan(user)
    plan.daily_plans[0].workouts.append(WorkoutPlacement(
        template_id="upper_heavy", day=0, start_slot=30, end_slot=33,
    ))
    plan.schedule_blocks.append(ScheduleBlock(
        day=0, start_slot=30, end_slot=33, kind=ActivityKind.WORKOUT,
        label="Heavy upper",
        details={"template_id": "upper_heavy",
                 "intensity": Intensity.VERY_HARD.value,
                 "type": "upper"},
    ))
    res = SolverResult(solver_name="joint_cpsat", status="OPTIMAL",
                       plan=plan, runtime_s=0.1)
    m = compute_metrics(res, user)
    assert m.workouts_scheduled == 1
    assert m.hard_workouts_scheduled == 1
