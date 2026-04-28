"""Nutrition Mixed-Integer Program.

This module isolates the *pure* nutrition sub-problem so it can be reused
from (a) the nutrition-only solver and (b) stage 1 of the two-stage solver.
By pulling the MIP out of the solver class we can write tiny unit tests
against it directly.

Formulation
-----------
Decision variables:
    x[d, f] = integer number of servings of food ``f`` on day ``d``,
              0 <= x[d, f] <= food.max_servings_per_day

Hard constraints (per day d):
    calorie_target - calorie_tolerance  <= sum(calories[f] * x[d, f]) <= calorie_target + calorie_tolerance
    protein_min_g                       <= sum(protein_g[f] * x[d, f])

Weekly budget:
    sum(cost_cents[f] * x[d, f]) <= weekly_budget_cents

Dietary exclusions are enforced upstream by filtering the catalog.

Objective:
    minimize  w_protein_dev * protein_gap_sum                   (soft protein target)
            + w_carb_dev   * sum_d |carbs_g sum_d - carb_target|
            + w_fat_dev    * sum_d |fat_g sum_d - fat_target|
            + w_cost       * total_cost_cents
            - w_convenience * total_convenience_bonus           (break ties)

Because CP-SAT requires integer coefficients, everything is kept integer.
We use OR-Tools' ``CpModel`` rather than ``pywraplp`` so the whole project
has a single solver dependency -- CP-SAT handles MIPs just fine for problem
sizes of this class.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from ortools.sat.python import cp_model

from src.config.settings import DAYS_PER_WEEK, DEFAULT_WEIGHTS, ScoringWeights
from src.models.domain import FoodItem, MealPlacement, UserProfile
from src.models.enums import MealType


@dataclass
class NutritionSolution:
    """Output of the nutrition MIP: per-day food servings + summary totals."""

    status: str
    servings_per_day: list[dict[str, int]]        # [day -> {food_id: servings}]
    daily_calories: list[int]
    daily_protein_g: list[int]
    daily_carbs_g: list[int]
    daily_fat_g: list[int]
    total_cost_cents: int
    objective_value: float | None

    @property
    def feasible(self) -> bool:
        return self.status in {"OPTIMAL", "FEASIBLE"}

    def to_meal_placements(
        self,
        user: UserProfile,
        foods: list[FoodItem] | None = None,
    ) -> list[MealPlacement]:
        """Convert the per-day servings back into a *coarse* meal list.

        The MIP alone doesn't decide *which meal* each serving belongs to -- it
        only decides how many servings of each food per day. We do a greedy
        bucket-fill here, but availability-aware: for each day we only use meal
        types whose default time window overlaps at least one free slot in the
        user's availability. This prevents stage 1 from committing to a LUNCH
        bucket on a day where the user has no midday availability, which would
        render stage 2 infeasible.

        When ``foods`` is supplied, foods are preferentially placed in meal
        types their ``meal_types`` list includes.
        """
        food_by_id = {f.id: f for f in (foods or [])}
        # Default meal windows (must match stage2_scheduler._DEFAULT_MEAL_WINDOWS)
        default_windows: dict[MealType, tuple[int, int]] = {
            MealType.BREAKFAST: (12, 22),
            MealType.LUNCH: (22, 30),
            MealType.DINNER: (34, 44),
            MealType.SNACK: (16, 44),
        }
        mask = user.availability_mask()

        placements: list[MealPlacement] = []
        meal_cycle = [MealType.BREAKFAST, MealType.LUNCH, MealType.DINNER, MealType.SNACK]
        for d, day_map in enumerate(self.servings_per_day):
            remaining = {fid: n for fid, n in day_map.items() if n > 0}
            # Only use meal types that have at least one available slot today.
            usable = [
                mt for mt in meal_cycle
                if any(mask[d][s] for s in range(*default_windows[mt])
                       if s < len(mask[d]))
            ]
            if not usable:
                # No availability at all on this day; skip it.
                continue

            meals_today: list[MealPlacement] = []
            max_m = min(user.max_meals_per_day, len(usable))
            for mt in usable:
                if len(meals_today) >= max_m:
                    break
                bucket: dict[str, int] = {}
                # Pick foods that list this meal type, then fall back to any food.
                preferred = [
                    fid for fid in remaining
                    if fid in food_by_id and mt in food_by_id[fid].meal_types
                ]
                pool = preferred or list(remaining.keys())
                for fid in pool[:3]:
                    bucket[fid] = remaining.pop(fid)
                if bucket:
                    meals_today.append(MealPlacement(
                        day=d, meal_type=mt, food_servings=bucket,
                    ))
            # Anything left goes in a snack if SNACK is usable today.
            if remaining and MealType.SNACK in usable and len(meals_today) < user.max_meals_per_day:
                # Merge into existing snack bucket if present.
                snack = next((m for m in meals_today if m.meal_type == MealType.SNACK), None)
                if snack is None:
                    meals_today.append(MealPlacement(
                        day=d, meal_type=MealType.SNACK, food_servings=remaining,
                    ))
                else:
                    for fid, n in remaining.items():
                        snack.food_servings[fid] = snack.food_servings.get(fid, 0) + n
            placements.extend(meals_today)
        return placements


class NutritionMIP:
    """Builder for the nutrition MIP. Stateless; call :meth:`solve`."""

    def __init__(
        self,
        *,
        weights: ScoringWeights = DEFAULT_WEIGHTS,
        time_limit_s: int = 20,
        log_search: bool = False,
    ) -> None:
        self.weights = weights
        self.time_limit_s = time_limit_s
        self.log_search = log_search

    # ------------------------------------------------------------------
    def solve(self, user: UserProfile, foods: Iterable[FoodItem]) -> NutritionSolution:
        foods = list(foods)
        if not foods:
            return NutritionSolution(
                status="INFEASIBLE",
                servings_per_day=[{} for _ in range(DAYS_PER_WEEK)],
                daily_calories=[0] * DAYS_PER_WEEK,
                daily_protein_g=[0] * DAYS_PER_WEEK,
                daily_carbs_g=[0] * DAYS_PER_WEEK,
                daily_fat_g=[0] * DAYS_PER_WEEK,
                total_cost_cents=0,
                objective_value=None,
            )

        # Apply dietary exclusions upfront (idempotent if already filtered).
        foods = [f for f in foods if f.allowed_for(user.dietary_exclusions)]

        model = cp_model.CpModel()
        n_foods = len(foods)
        # x[d][i] = servings of foods[i] on day d
        x: list[list[cp_model.IntVar]] = []
        for d in range(DAYS_PER_WEEK):
            row = []
            for i, f in enumerate(foods):
                row.append(model.NewIntVar(0, f.max_servings_per_day, f"x_{d}_{i}"))
            x.append(row)

        # ------------ daily macro & calorie expressions
        cal_target = user.calorie_target
        cal_tol = user.calorie_tolerance

        daily_cal_exprs = []
        daily_pro_exprs = []
        daily_carb_exprs = []
        daily_fat_exprs = []

        for d in range(DAYS_PER_WEEK):
            cal_expr = sum(f.calories * x[d][i] for i, f in enumerate(foods))
            pro_expr = sum(f.protein_g * x[d][i] for i, f in enumerate(foods))
            carb_expr = sum(f.carbs_g * x[d][i] for i, f in enumerate(foods))
            fat_expr = sum(f.fat_g * x[d][i] for i, f in enumerate(foods))

            daily_cal_exprs.append(cal_expr)
            daily_pro_exprs.append(pro_expr)
            daily_carb_exprs.append(carb_expr)
            daily_fat_exprs.append(fat_expr)

            # Hard calorie band
            model.Add(cal_expr >= cal_target - cal_tol)
            model.Add(cal_expr <= cal_target + cal_tol)
            # Hard protein minimum
            model.Add(pro_expr >= user.protein_min_g)

        # ------------ weekly budget
        total_cost_expr = sum(
            foods[i].cost_cents * x[d][i]
            for d in range(DAYS_PER_WEEK)
            for i in range(n_foods)
        )
        model.Add(total_cost_expr <= user.weekly_budget_cents)

        # ------------ soft objective terms (integer deviations)
        # Protein gap = max(0, target - actual)
        protein_gap_vars: list[cp_model.IntVar] = []
        for d, pro_expr in enumerate(daily_pro_exprs):
            gap = model.NewIntVar(0, user.protein_target_g, f"pro_gap_{d}")
            model.Add(gap >= user.protein_target_g - pro_expr)
            protein_gap_vars.append(gap)

        # |carbs - target|  and  |fat - target|
        carb_dev_vars: list[cp_model.IntVar] = []
        fat_dev_vars: list[cp_model.IntVar] = []
        big_macro = 2_000   # generous upper bound on daily grams
        for d in range(DAYS_PER_WEEK):
            dev_c = model.NewIntVar(0, big_macro, f"carb_dev_{d}")
            model.Add(dev_c >= daily_carb_exprs[d] - user.carb_target_g)
            model.Add(dev_c >= user.carb_target_g - daily_carb_exprs[d])
            carb_dev_vars.append(dev_c)

            dev_f = model.NewIntVar(0, big_macro, f"fat_dev_{d}")
            model.Add(dev_f >= daily_fat_exprs[d] - user.fat_target_g)
            model.Add(dev_f >= user.fat_target_g - daily_fat_exprs[d])
            fat_dev_vars.append(dev_f)

        # ------------ convenience bonus (subtracted so larger is better)
        convenience_expr = sum(
            foods[i].convenience * x[d][i]
            for d in range(DAYS_PER_WEEK)
            for i in range(n_foods)
        )

        w = self.weights
        model.Minimize(
            w.protein_deviation * sum(protein_gap_vars)
            + w.macro_deviation * sum(carb_dev_vars)
            + w.macro_deviation * sum(fat_dev_vars)
            + w.cost_weight * total_cost_expr
            - 1 * convenience_expr
        )

        # ------------ solve
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(self.time_limit_s)
        solver.parameters.log_search_progress = self.log_search
        status = solver.Solve(model)

        status_name = {
            cp_model.OPTIMAL: "OPTIMAL",
            cp_model.FEASIBLE: "FEASIBLE",
            cp_model.INFEASIBLE: "INFEASIBLE",
            cp_model.MODEL_INVALID: "ERROR",
            cp_model.UNKNOWN: "TIMEOUT",
        }.get(status, "ERROR")

        if status_name not in {"OPTIMAL", "FEASIBLE"}:
            return NutritionSolution(
                status=status_name,
                servings_per_day=[{} for _ in range(DAYS_PER_WEEK)],
                daily_calories=[0] * DAYS_PER_WEEK,
                daily_protein_g=[0] * DAYS_PER_WEEK,
                daily_carbs_g=[0] * DAYS_PER_WEEK,
                daily_fat_g=[0] * DAYS_PER_WEEK,
                total_cost_cents=0,
                objective_value=None,
            )

        # Extract solution
        servings_per_day: list[dict[str, int]] = []
        daily_cal = []
        daily_pro = []
        daily_carb = []
        daily_fat = []
        total_cost = 0
        for d in range(DAYS_PER_WEEK):
            day_map: dict[str, int] = {}
            for i, f in enumerate(foods):
                v = solver.Value(x[d][i])
                if v > 0:
                    day_map[f.id] = v
                    total_cost += v * f.cost_cents
            servings_per_day.append(day_map)
            daily_cal.append(int(solver.Value(daily_cal_exprs[d])))
            daily_pro.append(int(solver.Value(daily_pro_exprs[d])))
            daily_carb.append(int(solver.Value(daily_carb_exprs[d])))
            daily_fat.append(int(solver.Value(daily_fat_exprs[d])))

        return NutritionSolution(
            status=status_name,
            servings_per_day=servings_per_day,
            daily_calories=daily_cal,
            daily_protein_g=daily_pro,
            daily_carbs_g=daily_carb,
            daily_fat_g=daily_fat,
            total_cost_cents=int(total_cost),
            objective_value=float(solver.ObjectiveValue()),
        )
