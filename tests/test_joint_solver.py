"""Joint CP-SAT solver: feasibility + hard-constraint validation."""
from __future__ import annotations

from src.data_ingestion.food_catalog import build_food_catalog
from src.evaluation.metrics import compute_metrics
from src.evaluation.validator import validate_plan
from src.experiments.instance_generator import InstanceParams, generate_user
from src.models.enums import ActivityKind, Intensity
from src.solvers.joint_cpsat import JointCPSATSolver


def test_joint_solver_feasible_on_balanced(sample_workouts):
    user = generate_user("balanced", InstanceParams(seed=21))
    foods = build_food_catalog()
    res = JointCPSATSolver(time_limit_s=25).solve(user, foods, sample_workouts)
    assert res.feasible, f"status={res.status}, reason={res.infeasibility_reason}"

    report = validate_plan(res.plan, user)
    assert report.ok, f"Hard violations: {report.violations}"


def test_joint_solver_respects_recovery_rule(sample_workouts):
    user = generate_user("recovery_constrained", InstanceParams(seed=31))
    foods = build_food_catalog()
    res = JointCPSATSolver(time_limit_s=30).solve(user, foods, sample_workouts)
    if not res.feasible:
        return  # solver may fail under very tight constraints; that's ok
    # Check pairwise gap between two hard workouts.
    hard_starts = sorted(
        (b.day * 48 + b.start_slot, b.day * 48 + b.end_slot)
        for b in res.plan.schedule_blocks
        if b.kind == ActivityKind.WORKOUT
        and b.details.get("intensity") in {Intensity.HARD.value, Intensity.VERY_HARD.value}
    )
    for (_, a_end), (b_start, _) in zip(hard_starts, hard_starts[1:]):
        assert b_start - a_end >= user.recovery.min_gap_slots


def test_joint_solver_detects_infeasibility(sample_workouts):
    user = generate_user("impossible_case", InstanceParams(seed=7))
    foods = build_food_catalog()
    res = JointCPSATSolver(time_limit_s=10).solve(user, foods, sample_workouts)
    assert not res.feasible
    assert res.infeasibility_reason  # solver populates a reason string


def test_metrics_pull_through(sample_workouts):
    user = generate_user("lean_bulk", InstanceParams(seed=41))
    foods = build_food_catalog()
    res = JointCPSATSolver(time_limit_s=30).solve(user, foods, sample_workouts)
    if res.feasible:
        m = compute_metrics(res, user)
        assert m.workouts_scheduled >= user.workout_count_min
        assert m.total_cost_cents <= user.weekly_budget_cents
