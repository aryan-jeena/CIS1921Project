"""Solver D: joint CP-SAT with LNS warm-start from the two-stage solution.

Why have a fourth solver?
-------------------------
The proposal-feedback raised an interesting question about the joint
formulation's larger search space and suggested a "lazy" hybrid where the
nutrition solver passes candidate meal blocks to the scheduler. We do the
same idea in reverse: run the cheap two-stage solver to get a feasible
plan, then hand its workout placements and meal start slots to the joint
CP-SAT model as solver hints. CP-SAT prunes large parts of the tree on
the first probe and typically reaches OPTIMAL in much less wall-clock
time than the cold joint solve, while still being free to swap servings
or reposition meals if doing so reduces the objective.

This solver is a *strict* hybrid -- the underlying model and objective are
identical to :class:`JointCPSATSolver`, only the warm-start changes. So
the two formulations remain directly comparable in tables and figures.
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
from src.solvers.base import BaseSolver
from src.solvers.joint_cpsat import JointCPSATSolver
from src.solvers.two_stage import TwoStageSolver


class JointWarmStartSolver(BaseSolver):
    """Run two-stage, then warm-start joint CP-SAT with its plan."""

    name = "joint_warmstart"

    def solve(
        self,
        user: UserProfile,
        foods: Iterable[FoodItem],
        workouts: Iterable[WorkoutTemplate],
    ) -> SolverResult:
        foods = list(foods)
        workouts = list(workouts)

        t0 = time.perf_counter()
        # We give two-stage roughly 1/4 of the total budget. It's fast in
        # practice and any leftover time goes to the joint refinement.
        ts_limit = max(2, (self.time_limit_s or user.time_limit_s) // 4)
        ts = TwoStageSolver(
            weights=self.weights,
            time_limit_s=ts_limit,
            log_search=self.log_search,
        )
        ts_result = ts.solve(user, foods, workouts)

        joint_limit = max(
            2, (self.time_limit_s or user.time_limit_s) - int(ts_result.runtime_s)
        )
        joint = JointCPSATSolver(
            weights=self.weights,
            time_limit_s=joint_limit,
            log_search=self.log_search,
        )
        warm = ts_result if ts_result.feasible else None
        result = joint.solve(user, foods, workouts, warm_start=warm)
        # Total runtime is the sum of both passes.
        result.solver_name = self.name
        result.runtime_s = time.perf_counter() - t0
        extras = dict(result.extras or {})
        extras.update({
            "two_stage_status": ts_result.status,
            "two_stage_runtime_s": round(ts_result.runtime_s, 4),
            "two_stage_objective": ts_result.objective_value,
            "warm_started": warm is not None,
        })
        result.extras = extras
        return result
