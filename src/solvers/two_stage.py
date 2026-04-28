"""Solver B: two-stage baseline.

Stage 1: run the nutrition MIP (via :mod:`src.nutrition.mip_model`). This
         fixes the week's food servings.
Stage 2: run the CP-SAT :class:`Stage2Scheduler` to place meals, workouts,
         and sleep in the user's time windows.

This is a *classical* decomposition used in operations research: solve the
easier sub-problem first, then the harder one. Its weakness is that stage 1
can commit to food choices that stage 2 can't fit -- which makes it
interesting to compare against the joint formulation.
"""
from __future__ import annotations

import time
from typing import Iterable

from src.models.domain import (
    FoodItem,
    SolverResult,
    UserProfile,
    WorkoutTemplate,
)
from src.nutrition.mip_model import NutritionMIP
from src.scheduling.stage2_scheduler import Stage2Scheduler
from src.solvers.base import BaseSolver


class TwoStageSolver(BaseSolver):
    name = "two_stage"

    def solve(
        self,
        user: UserProfile,
        foods: Iterable[FoodItem],
        workouts: Iterable[WorkoutTemplate],
    ) -> SolverResult:
        foods = list(foods)
        workouts = list(workouts)

        t0 = time.perf_counter()

        # ---------------- stage 1: nutrition MIP
        mip = NutritionMIP(
            weights=self.weights,
            time_limit_s=max(5, (self.time_limit_s or user.time_limit_s) // 2),
            log_search=self.log_search,
        )
        nutrition = mip.solve(user, foods)
        if not nutrition.feasible:
            runtime = time.perf_counter() - t0
            return SolverResult(
                solver_name=self.name,
                status=nutrition.status,
                runtime_s=runtime,
                infeasibility_reason=(
                    "Stage 1 (nutrition MIP) produced no feasible food plan. "
                    "Check calorie band, protein floor, budget, and dietary exclusions."
                ),
                extras={"stage": 1},
            )

        meal_buckets = nutrition.to_meal_placements(user, foods=foods)

        # ---------------- stage 2: scheduler CP-SAT
        scheduler = Stage2Scheduler(
            weights=self.weights,
            time_limit_s=max(5, (self.time_limit_s or user.time_limit_s) // 2),
            log_search=self.log_search,
        )
        result = scheduler.schedule(user, meal_buckets, foods, workouts)
        result.runtime_s = time.perf_counter() - t0  # override with total
        result.solver_name = self.name
        extras = dict(result.extras or {})
        extras.update({
            "stage1_status": nutrition.status,
            "stage1_cost_cents": nutrition.total_cost_cents,
            "stage1_objective": nutrition.objective_value,
        })
        result.extras = extras
        return result
