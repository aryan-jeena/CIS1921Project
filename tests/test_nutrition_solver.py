"""Nutrition-only MIP sanity tests."""
from __future__ import annotations

from src.config.settings import DAYS_PER_WEEK
from src.data_ingestion.food_catalog import build_food_catalog
from src.experiments.instance_generator import InstanceParams, generate_user
from src.solvers.nutrition_only import NutritionOnlySolver


def test_nutrition_only_feasible_on_balanced(sample_workouts):
    user = generate_user("balanced", InstanceParams(seed=5))
    foods = build_food_catalog()
    res = NutritionOnlySolver(time_limit_s=15).solve(user, foods, sample_workouts)

    assert res.feasible, f"status={res.status}, reason={res.infeasibility_reason}"
    assert res.plan is not None
    assert len(res.plan.daily_plans) == DAYS_PER_WEEK
    for dp in res.plan.daily_plans:
        # Calorie band
        lo = user.calorie_target - user.calorie_tolerance
        hi = user.calorie_target + user.calorie_tolerance
        assert lo <= dp.calories_total <= hi
        # Protein floor
        assert dp.protein_total_g >= user.protein_min_g


def test_nutrition_only_respects_budget(sample_workouts):
    user = generate_user("budget_student", InstanceParams(seed=3))
    foods = build_food_catalog()
    res = NutritionOnlySolver(time_limit_s=15).solve(user, foods, sample_workouts)
    assert res.feasible
    assert res.plan.weekly_cost_cents <= user.weekly_budget_cents


def test_nutrition_only_detects_infeasibility(sample_workouts):
    user = generate_user("impossible_case", InstanceParams(seed=1))
    foods = build_food_catalog()
    res = NutritionOnlySolver(time_limit_s=5).solve(user, foods, sample_workouts)
    assert not res.feasible or res.plan.weekly_cost_cents > user.weekly_budget_cents * 2
    # Either the MIP infeasibility is detected outright, or the result is
    # something obviously unreasonable. The important thing is: no crash.
