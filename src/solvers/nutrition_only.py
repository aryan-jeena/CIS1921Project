"""Solver A: nutrition-only baseline (LP/MIP).

This solver ignores time completely. It answers: "given the user's macro
targets, budget, and dietary exclusions, what food servings across the week
best satisfy the nutrition objectives?" No workouts, no schedule, no sleep.

It's useful as
  (1) a lower bound / sanity check on cost and macro deviation, and
  (2) stage 1 of the :class:`TwoStageSolver`.
"""
from __future__ import annotations

import time
from typing import Iterable

from src.config.settings import DAYS_PER_WEEK
from src.models.domain import (
    DailyPlan,
    FoodItem,
    Plan,
    SolverResult,
    UserProfile,
    WorkoutTemplate,
)
from src.nutrition.mip_model import NutritionMIP
from src.solvers.base import BaseSolver


class NutritionOnlySolver(BaseSolver):
    name = "nutrition_only"

    def solve(
        self,
        user: UserProfile,
        foods: Iterable[FoodItem],
        workouts: Iterable[WorkoutTemplate],
    ) -> SolverResult:
        # Workouts are accepted for API symmetry but ignored.
        _ = list(workouts)
        foods = list(foods)

        t0 = time.perf_counter()
        mip = NutritionMIP(
            weights=self.weights,
            time_limit_s=self.time_limit_s or user.time_limit_s,
            log_search=self.log_search,
        )
        sol = mip.solve(user, foods)
        runtime = time.perf_counter() - t0

        if not sol.feasible:
            return SolverResult(
                solver_name=self.name,
                status=sol.status,
                runtime_s=runtime,
                infeasibility_reason=(
                    "Nutrition MIP could not satisfy calorie/protein/budget "
                    "constraints given the food catalog."
                ),
            )

        # Build a thin Plan (no schedule) so downstream code still works.
        food_by_id = {f.id: f for f in foods}
        daily_plans: list[DailyPlan] = []
        weekly_cost = 0
        for d in range(DAYS_PER_WEEK):
            day_map = sol.servings_per_day[d]
            cost = sum(
                food_by_id[fid].cost_cents * n
                for fid, n in day_map.items()
                if fid in food_by_id
            )
            weekly_cost += cost
            daily_plans.append(
                DailyPlan(
                    day=d,
                    calories_total=sol.daily_calories[d],
                    protein_total_g=sol.daily_protein_g[d],
                    carbs_total_g=sol.daily_carbs_g[d],
                    fat_total_g=sol.daily_fat_g[d],
                    cost_cents=cost,
                )
            )
            # Attach the raw food-serving map as a coarse "meal" for display.
            from src.models.domain import MealPlacement
            from src.models.enums import MealType
            if day_map:
                daily_plans[-1].meals.append(
                    MealPlacement(day=d, meal_type=MealType.LUNCH, food_servings=day_map)
                )

        plan = Plan(
            user_name=user.name,
            daily_plans=daily_plans,
            schedule_blocks=[],    # nutrition-only produces no schedule
            weekly_cost_cents=int(weekly_cost),
        )

        return SolverResult(
            solver_name=self.name,
            status=sol.status,
            objective_value=sol.objective_value,
            runtime_s=runtime,
            plan=plan,
            extras={"formulation": "MIP", "days": DAYS_PER_WEEK},
        )
