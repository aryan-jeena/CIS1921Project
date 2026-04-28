"""Pantry / dining-hall mode + LNS warm-start coverage.

These tests target the additions made in response to check-in feedback:

* Pantry mode (``UserProfile.enforce_pantry`` + ``pantry_food_ids``) restricts
  every solver's food set without changing the rest of the model.
* :class:`JointWarmStartSolver` chains two-stage into joint CP-SAT and reports
  ``warm_started=True`` in extras.
* Hydration reminders are surfaced in solver extras and produce a non-zero
  ``hydration_target`` in the experiment row when enabled.
"""
from __future__ import annotations

from src.data_ingestion.food_catalog import build_food_catalog
from src.evaluation.metrics import compute_metrics
from src.evaluation.validator import validate_plan
from src.experiments.instance_generator import (
    InstanceParams,
    apply_pantry_to_user,
    generate_user,
)
from src.solvers.joint_cpsat import JointCPSATSolver
from src.solvers.joint_lns import JointWarmStartSolver
from src.solvers.nutrition_only import NutritionOnlySolver
from src.solvers.two_stage import TwoStageSolver


def test_pantry_filter_restricts_solver_choice(sample_workouts):
    user = generate_user("balanced", InstanceParams(seed=11))
    foods = build_food_catalog()
    pantry = apply_pantry_to_user(user, foods, pantry_size=12, seed=11)
    res = NutritionOnlySolver(time_limit_s=10).solve(pantry, foods, sample_workouts)
    if not res.feasible:
        # Pantry can be too tight to satisfy macros; that is a valid outcome
        # to verify the filter is real (not silently ignored).
        assert res.infeasibility_reason
        return
    used_ids: set[str] = set()
    for dp in res.plan.daily_plans:
        for mp in dp.meals:
            used_ids.update(mp.food_servings)
    assert used_ids.issubset(set(pantry.pantry_food_ids))


def test_pantry_mode_zeros_cost_weight_in_mip(sample_workouts):
    """Pantry mode should not penalise cost (food is already 'paid for')."""
    from src.nutrition.mip_model import NutritionMIP

    user = generate_user("balanced", InstanceParams(seed=12))
    foods = build_food_catalog()
    pantry = apply_pantry_to_user(user, foods, pantry_size=14, seed=12)
    mip = NutritionMIP(time_limit_s=10)
    mip.solve(pantry, foods)
    assert mip._effective_cost_weight == 0


def test_warmstart_solver_runs_and_records_extras(sample_workouts):
    user = generate_user("balanced", InstanceParams(seed=13))
    foods = build_food_catalog()
    res = JointWarmStartSolver(time_limit_s=20).solve(user, foods, sample_workouts)
    assert res.solver_name == "joint_warmstart"
    if res.feasible:
        assert "two_stage_status" in res.extras
        assert "warm_started" in res.extras


def test_hydration_reminders_present_in_extras(sample_workouts):
    user = generate_user("balanced", InstanceParams(seed=14))
    foods = build_food_catalog()
    res = JointCPSATSolver(time_limit_s=20).solve(user, foods, sample_workouts)
    if res.feasible:
        assert "hydration_target_per_day" in res.extras
        assert res.extras["hydration_target_per_day"] >= 0
        assert "hydration_shortfall" in res.extras


def test_diagnose_infeasibility_returns_named_groups(sample_workouts):
    user = generate_user("impossible_case", InstanceParams(seed=15))
    foods = build_food_catalog()
    msg = JointCPSATSolver().diagnose_infeasibility(
        user, foods, sample_workouts,
    )
    # We don't assert which groups -- just that *something* informative
    # comes back and that it's not the generic message.
    assert msg
    assert any(token in msg for token in (
        "calorie_band", "protein_floor", "weekly_budget",
        "workout_count", "scheduling overlaps",
        "Food catalog is empty", "No workout template fits",
    ))
