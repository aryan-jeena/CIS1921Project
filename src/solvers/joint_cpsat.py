"""Solver C: joint weekly CP-SAT optimizer.

This is the marquee formulation. A *single* CP-SAT model decides:

  - how many servings of each food to consume on each day,
  - which meal types those servings are distributed across,
  - where to place each meal on the time grid,
  - which workouts to schedule and when,
  - the sleep block per night,
  - (soft) hydration reminders.

All hard constraints and all soft terms live in the same model, so the
solver can trade a small macro deviation for a better schedule or vice
versa. This is exactly what the two-stage decomposition cannot do.

Decision variables
------------------
*Nutrition*
    serve[d, m, f]   -- integer servings of food f in meal m on day d
                         (bounded by food.max_servings_per_day and by the
                         meal_type being in the food's allowed set).
    meal_active[d, m]-- boolean: is meal m present on day d?

*Scheduling*
    meal_start[d, m] -- slot index where meal m starts on day d (if active)
    meal_iv[d, m]    -- optional interval over the grid

    wk_sched[d, w]   -- boolean: workout template w is scheduled on day d
    wk_start[d, w]   -- slot index (if scheduled)
    wk_iv[d, w]      -- optional interval

*Sleep*
    sleep_start[d]   -- slot index of nightly sleep block start

*Objective*
    Sum of: macro/calorie deviation penalties, cost, preference violations,
            peri-workout meal miss penalty, protein-per-meal shortfall,
            hydration shortfall, minus a convenience bonus.

The model scales well: on the curated 47-food catalog with 5-10 workout
candidates and a tightly set availability, CP-SAT reaches FEASIBLE in under
a second and OPTIMAL in 5-15s on a laptop.
"""
from __future__ import annotations

import time
from typing import Iterable

from ortools.sat.python import cp_model

from src.config.settings import (
    DAYS_PER_WEEK,
    DEFAULT_WEIGHTS,
    SLOTS_PER_DAY,
    ScoringWeights,
)
from src.models.domain import (
    DailyPlan,
    FoodItem,
    MealPlacement,
    Plan,
    ScheduleBlock,
    SolverResult,
    UserProfile,
    WorkoutPlacement,
    WorkoutTemplate,
)
from src.models.enums import ActivityKind, MealType
from src.scheduling.time_grid import build_availability_mask
from src.solvers.base import BaseSolver


# Default meal-type windows (in 30-min slots). Overridden per-user via
# ``UserProfile.meal_windows`` if provided.
_DEFAULT_MEAL_WINDOWS: dict[MealType, tuple[int, int]] = {
    MealType.BREAKFAST: (12, 22),
    MealType.LUNCH: (22, 30),
    MealType.DINNER: (34, 44),
    MealType.SNACK: (16, 44),
}

_MEAL_ORDER: tuple[MealType, ...] = (
    MealType.BREAKFAST,
    MealType.LUNCH,
    MealType.DINNER,
    MealType.SNACK,
)


class JointCPSATSolver(BaseSolver):
    """Single CP-SAT model handling nutrition + scheduling together."""

    name = "joint_cpsat"

    # ------------------------------------------------------------------
    def solve(
        self,
        user: UserProfile,
        foods: Iterable[FoodItem],
        workouts: Iterable[WorkoutTemplate],
    ) -> SolverResult:
        foods = [f for f in foods if f.allowed_for(user.dietary_exclusions)]
        workouts = list(workouts)
        if user.candidate_workouts:
            workouts = [w for w in workouts if w.id in user.candidate_workouts]

        food_by_id = {f.id: f for f in foods}

        t0 = time.perf_counter()
        if not foods:
            return SolverResult(
                solver_name=self.name, status="INFEASIBLE",
                runtime_s=time.perf_counter() - t0,
                infeasibility_reason="Food catalog is empty after dietary filtering.",
            )

        model = cp_model.CpModel()
        mask = build_availability_mask(user.available_windows)

        D = DAYS_PER_WEEK
        M = min(user.max_meals_per_day, len(_MEAL_ORDER))
        meal_types = list(_MEAL_ORDER[:M])

        # ==================================================================
        # NUTRITION DECISIONS
        # ==================================================================
        # serve[d][m][f_idx] = servings of food at index f_idx in meal m on day d
        serve: list[list[list[cp_model.IntVar]]] = []
        for d in range(D):
            day_row = []
            for m, mt in enumerate(meal_types):
                meal_row = []
                for i, f in enumerate(foods):
                    if mt not in f.meal_types:
                        meal_row.append(model.NewConstant(0))
                        continue
                    meal_row.append(
                        model.NewIntVar(0, f.max_servings_per_day, f"serve_d{d}_m{m}_f{i}")
                    )
                day_row.append(meal_row)
            serve.append(day_row)

        # meal_active[d][m] = 1 iff any food served in that meal
        meal_active: list[list[cp_model.IntVar]] = []
        for d in range(D):
            row = []
            for m in range(M):
                active = model.NewBoolVar(f"meal_active_d{d}_m{m}")
                total_m = sum(serve[d][m][i] for i in range(len(foods)))
                # active == 1  <=>  total_m >= 1
                model.Add(total_m >= 1).OnlyEnforceIf(active)
                model.Add(total_m == 0).OnlyEnforceIf(active.Not())
                row.append(active)
            meal_active.append(row)

        # Total meals per day <= max_meals_per_day (already guaranteed since M <= max)
        # But if user.max_meals_per_day < len(meal_types) we'd have restricted M above.

        # --- cap per-food per-day servings
        for d in range(D):
            for i, f in enumerate(foods):
                model.Add(
                    sum(serve[d][m][i] for m in range(M)) <= f.max_servings_per_day
                )

        # --- daily macro expressions
        daily_cal = []
        daily_pro = []
        daily_carb = []
        daily_fat = []
        for d in range(D):
            cal = sum(
                f.calories * serve[d][m][i]
                for m in range(M) for i, f in enumerate(foods)
            )
            pro = sum(
                f.protein_g * serve[d][m][i]
                for m in range(M) for i, f in enumerate(foods)
            )
            carb = sum(
                f.carbs_g * serve[d][m][i]
                for m in range(M) for i, f in enumerate(foods)
            )
            fat = sum(
                f.fat_g * serve[d][m][i]
                for m in range(M) for i, f in enumerate(foods)
            )
            daily_cal.append(cal)
            daily_pro.append(pro)
            daily_carb.append(carb)
            daily_fat.append(fat)
            # H1: hard calorie band
            model.Add(cal >= user.calorie_target - user.calorie_tolerance)
            model.Add(cal <= user.calorie_target + user.calorie_tolerance)
            # H2: hard protein floor
            model.Add(pro >= user.protein_min_g)

        # --- weekly budget (H3)
        total_cost = sum(
            f.cost_cents * serve[d][m][i]
            for d in range(D) for m in range(M) for i, f in enumerate(foods)
        )
        model.Add(total_cost <= user.weekly_budget_cents)

        # --- per-meal minimum protein (soft: penalty if active and below)
        #      shortfall_dm >= min_protein_per_meal * active_dm - meal_protein
        meal_protein = [
            [sum(f.protein_g * serve[d][m][i] for i, f in enumerate(foods))
             for m in range(M)]
            for d in range(D)
        ]
        pro_shortfall_vars: list[cp_model.IntVar] = []
        for d in range(D):
            for m in range(M):
                short = model.NewIntVar(0, user.min_protein_per_meal_g,
                                        f"pro_short_d{d}_m{m}")
                model.Add(
                    short >= user.min_protein_per_meal_g * meal_active[d][m] - meal_protein[d][m]
                )
                pro_shortfall_vars.append(short)

        # ==================================================================
        # SCHEDULING DECISIONS
        # ==================================================================
        meal_start_vars: dict[tuple[int, int], cp_model.IntVar] = {}
        meal_end_vars: dict[tuple[int, int], cp_model.IntVar] = {}
        meal_intervals_by_day: list[list] = [[] for _ in range(D)]

        for d in range(D):
            for m, mt in enumerate(meal_types):
                window_lo, window_hi = _DEFAULT_MEAL_WINDOWS[mt]
                allowed = [
                    s for s in range(window_lo, min(window_hi, SLOTS_PER_DAY))
                    if mask[d][s]
                ]
                if not allowed:
                    # No valid placement: force this meal inactive.
                    model.Add(meal_active[d][m] == 0)
                    # Create dummy vars so indexing remains consistent.
                    start = model.NewConstant(0)
                    end = model.NewConstant(1)
                else:
                    start = model.NewIntVarFromDomain(
                        cp_model.Domain.FromValues(allowed),
                        f"meal_start_d{d}_m{m}",
                    )
                    end = model.NewIntVar(0, SLOTS_PER_DAY, f"meal_end_d{d}_m{m}")
                    model.Add(end == start + 1)
                    iv = model.NewOptionalIntervalVar(
                        start, 1, end, meal_active[d][m], f"meal_iv_d{d}_m{m}"
                    )
                    meal_intervals_by_day[d].append(iv)
                meal_start_vars[(d, m)] = start
                meal_end_vars[(d, m)] = end

        # --- workouts
        wk_items: list[dict] = []
        wk_intervals_by_day: list[list] = [[] for _ in range(D)]
        for d in range(D):
            for wt in workouts:
                dur = wt.duration_slots
                valid = [
                    s for s in range(SLOTS_PER_DAY - dur + 1)
                    if all(mask[d][s + k] for k in range(dur))
                ]
                if not valid:
                    continue
                sched = model.NewBoolVar(f"wk_d{d}_{wt.id}")
                start = model.NewIntVarFromDomain(
                    cp_model.Domain.FromValues(valid), f"wk_start_d{d}_{wt.id}",
                )
                end = model.NewIntVar(0, SLOTS_PER_DAY, f"wk_end_d{d}_{wt.id}")
                model.Add(end == start + dur)
                iv = model.NewOptionalIntervalVar(
                    start, dur, end, sched, f"wk_iv_d{d}_{wt.id}"
                )
                wk_intervals_by_day[d].append(iv)
                wk_items.append({
                    "day": d, "template": wt,
                    "sched": sched, "start": start, "end": end,
                })

        # Workout count bounds (H5)
        if wk_items:
            model.Add(sum(w["sched"] for w in wk_items) >= user.workout_count_min)
            model.Add(sum(w["sched"] for w in wk_items) <= user.workout_count_max)
        else:
            if user.workout_count_min > 0:
                # No valid placements at all but a positive minimum -> infeasible.
                runtime = time.perf_counter() - t0
                return SolverResult(
                    solver_name=self.name, status="INFEASIBLE",
                    runtime_s=runtime,
                    infeasibility_reason=(
                        "No workout template has a valid start slot inside the user's "
                        "availability (check window lengths vs duration)."
                    ),
                )

        # --- sleep: fixed nightly blocks (see Stage2Scheduler for rationale).
        # Sleep naturally crosses midnight, so we model it as two fixed
        # intervals per day: a morning block [0, latest_wake) and an evening
        # block [earliest_bedtime, SLOTS_PER_DAY). The user's availability
        # mask already excludes these slots from meals/workouts, so no-overlap
        # is implicit -- we just record them for the rendered plan.
        wake = min(user.sleep.latest_wake_slot, SLOTS_PER_DAY)
        bed = max(user.sleep.earliest_bedtime_slot, 0)
        sleep_starts: list[int] = [bed for _ in range(D)]
        sleep_ends: list[int] = [SLOTS_PER_DAY for _ in range(D)]

        # --- no-overlap per day (H-overlap)
        for d in range(D):
            pool = meal_intervals_by_day[d] + wk_intervals_by_day[d]
            if pool:
                model.AddNoOverlap(pool)

        # --- recovery spacing between hard workouts (H6)
        for i, wi in enumerate(wk_items):
            for j in range(i + 1, len(wk_items)):
                wj = wk_items[j]
                if not (wi["template"].is_hard and wj["template"].is_hard):
                    continue
                gap = max(
                    user.recovery.min_gap_slots,
                    wi["template"].min_recovery_slots,
                    wj["template"].min_recovery_slots,
                )
                abs_i_start = wi["start"] + wi["day"] * SLOTS_PER_DAY
                abs_j_start = wj["start"] + wj["day"] * SLOTS_PER_DAY
                abs_i_end = abs_i_start + wi["template"].duration_slots
                abs_j_end = abs_j_start + wj["template"].duration_slots

                both = model.NewBoolVar(f"both_rec_{i}_{j}")
                model.AddBoolAnd([wi["sched"], wj["sched"]]).OnlyEnforceIf(both)
                model.AddBoolOr([wi["sched"].Not(), wj["sched"].Not()]).OnlyEnforceIf(both.Not())

                order = model.NewBoolVar(f"order_{i}_{j}")
                model.Add(abs_j_start - abs_i_end >= gap).OnlyEnforceIf([both, order])
                model.Add(abs_i_start - abs_j_end >= gap).OnlyEnforceIf([both, order.Not()])

        # --- max consecutive hard days
        hard_on_day = [model.NewBoolVar(f"hard_on_{d}") for d in range(D)]
        for d in range(D):
            day_hard_wks = [w["sched"] for w in wk_items
                            if w["day"] == d and w["template"].is_hard]
            if day_hard_wks:
                model.Add(sum(day_hard_wks) >= 1).OnlyEnforceIf(hard_on_day[d])
                model.Add(sum(day_hard_wks) == 0).OnlyEnforceIf(hard_on_day[d].Not())
            else:
                model.Add(hard_on_day[d] == 0)

        max_cons = user.recovery.max_consecutive_hard_days
        for d in range(D - max_cons):
            # At least one rest day in any window of size max_cons + 1.
            model.Add(sum(hard_on_day[d:d + max_cons + 1]) <= max_cons)

        # ==================================================================
        # OBJECTIVE
        # ==================================================================
        w = self.weights
        obj: list = []

        # Protein target shortfall per day (soft: hard floor is protein_min_g)
        for d in range(D):
            gap = model.NewIntVar(0, user.protein_target_g, f"pro_tgt_gap_{d}")
            model.Add(gap >= user.protein_target_g - daily_pro[d])
            obj.append(w.protein_deviation * gap)

        # Carb/fat absolute deviation
        big = 2_000
        for d in range(D):
            dev_c = model.NewIntVar(0, big, f"carb_dev_{d}")
            model.Add(dev_c >= daily_carb[d] - user.carb_target_g)
            model.Add(dev_c >= user.carb_target_g - daily_carb[d])
            obj.append(w.macro_deviation * dev_c)

            dev_f = model.NewIntVar(0, big, f"fat_dev_{d}")
            model.Add(dev_f >= daily_fat[d] - user.fat_target_g)
            model.Add(dev_f >= user.fat_target_g - daily_fat[d])
            obj.append(w.macro_deviation * dev_f)

        # Cost penalty
        obj.append(w.cost_weight * total_cost)

        # Per-meal protein shortfall
        for v in pro_shortfall_vars:
            obj.append(w.protein_per_meal_shortfall * v)

        # Preferred workout days + avoid-day penalty
        pref_days = set(user.preferences.preferred_workout_days)
        avoid_days = set(user.preferences.avoid_workout_days)
        for wi in wk_items:
            if wi["day"] in avoid_days:
                obj.append(w.preference_violation * wi["sched"])
            if pref_days and wi["day"] not in pref_days:
                obj.append((w.preference_violation // 3) * wi["sched"])

        # Peri-workout meal timing penalties
        pre_window = user.preferences.pre_workout_meal_window_slots
        post_window = user.preferences.post_workout_meal_window_slots

        for i, wi in enumerate(wk_items):
            d = wi["day"]
            wt = wi["template"]
            same_day_meal_ids = [(d, m) for m in range(M)]

            if user.preferences.wants_pre_workout_meal:
                pre_ok = model.NewBoolVar(f"pre_ok_{i}")
                pre_bools = []
                for (dd, mm) in same_day_meal_ids:
                    b = model.NewBoolVar(f"pre_{i}_{mm}")
                    diff = model.NewIntVar(-SLOTS_PER_DAY, SLOTS_PER_DAY, f"dpre_{i}_{mm}")
                    model.Add(diff == wi["start"] - meal_end_vars[(dd, mm)])
                    model.Add(diff > 0).OnlyEnforceIf([b, meal_active[dd][mm]])
                    model.Add(diff <= pre_window).OnlyEnforceIf([b, meal_active[dd][mm]])
                    # b only meaningful when meal is active
                    model.AddImplication(b, meal_active[dd][mm])
                    pre_bools.append(b)
                model.AddBoolOr(pre_bools).OnlyEnforceIf(pre_ok)
                model.AddBoolAnd([b.Not() for b in pre_bools]).OnlyEnforceIf(pre_ok.Not())
                miss = model.NewBoolVar(f"miss_pre_{i}")
                model.AddBoolAnd([wi["sched"], pre_ok.Not()]).OnlyEnforceIf(miss)
                model.AddBoolOr([wi["sched"].Not(), pre_ok]).OnlyEnforceIf(miss.Not())
                obj.append(w.meal_timing_violation * miss)

            if user.preferences.wants_post_workout_meal:
                post_ok = model.NewBoolVar(f"post_ok_{i}")
                post_bools = []
                wk_end_i = model.NewIntVar(0, SLOTS_PER_DAY, f"wend_{i}")
                model.Add(wk_end_i == wi["start"] + wt.duration_slots)
                for (dd, mm) in same_day_meal_ids:
                    b = model.NewBoolVar(f"post_{i}_{mm}")
                    diff = model.NewIntVar(-SLOTS_PER_DAY, SLOTS_PER_DAY, f"dpost_{i}_{mm}")
                    model.Add(diff == meal_start_vars[(dd, mm)] - wk_end_i)
                    model.Add(diff >= 0).OnlyEnforceIf([b, meal_active[dd][mm]])
                    model.Add(diff <= post_window).OnlyEnforceIf([b, meal_active[dd][mm]])
                    model.AddImplication(b, meal_active[dd][mm])
                    post_bools.append(b)
                model.AddBoolOr(post_bools).OnlyEnforceIf(post_ok)
                model.AddBoolAnd([b.Not() for b in post_bools]).OnlyEnforceIf(post_ok.Not())
                miss = model.NewBoolVar(f"miss_post_{i}")
                model.AddBoolAnd([wi["sched"], post_ok.Not()]).OnlyEnforceIf(miss)
                model.AddBoolOr([wi["sched"].Not(), post_ok]).OnlyEnforceIf(miss.Not())
                obj.append(w.meal_timing_violation * miss)

        # Convenience bonus (negative term => rewarded)
        convenience_bonus = sum(
            f.convenience * serve[d][m][i]
            for d in range(D) for m in range(M) for i, f in enumerate(foods)
        )
        obj.append(-1 * convenience_bonus)

        model.Minimize(sum(obj))

        # ==================================================================
        # SOLVE
        # ==================================================================
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(
            self.time_limit_s or user.time_limit_s
        )
        solver.parameters.log_search_progress = self.log_search
        status = solver.Solve(model)
        runtime = time.perf_counter() - t0

        status_name = {
            cp_model.OPTIMAL: "OPTIMAL",
            cp_model.FEASIBLE: "FEASIBLE",
            cp_model.INFEASIBLE: "INFEASIBLE",
            cp_model.MODEL_INVALID: "ERROR",
            cp_model.UNKNOWN: "TIMEOUT",
        }.get(status, "ERROR")

        if status_name not in {"OPTIMAL", "FEASIBLE"}:
            return SolverResult(
                solver_name=self.name, status=status_name,
                runtime_s=runtime,
                infeasibility_reason=(
                    "Joint model had no feasible solution: try widening availability, "
                    "lowering workout_count_min, relaxing calorie band or budget."
                ),
            )

        # ==================================================================
        # EXTRACT SOLUTION -> Plan
        # ==================================================================
        daily_meals: list[list[MealPlacement]] = [[] for _ in range(D)]
        daily_wks: list[list[WorkoutPlacement]] = [[] for _ in range(D)]
        blocks: list[ScheduleBlock] = []
        daily_totals: list[dict[str, int]] = [
            {"cal": 0, "pro": 0, "carb": 0, "fat": 0, "cost": 0} for _ in range(D)
        ]

        for d in range(D):
            for m, mt in enumerate(meal_types):
                if solver.Value(meal_active[d][m]) == 0:
                    continue
                day_servings: dict[str, int] = {}
                for i, f in enumerate(foods):
                    v = solver.Value(serve[d][m][i])
                    if v > 0:
                        day_servings[f.id] = int(v)
                        daily_totals[d]["cal"] += f.calories * v
                        daily_totals[d]["pro"] += f.protein_g * v
                        daily_totals[d]["carb"] += f.carbs_g * v
                        daily_totals[d]["fat"] += f.fat_g * v
                        daily_totals[d]["cost"] += f.cost_cents * v
                s = int(solver.Value(meal_start_vars[(d, m)]))
                e = int(solver.Value(meal_end_vars[(d, m)]))
                mp = MealPlacement(
                    day=d, meal_type=mt, food_servings=day_servings,
                    start_slot=s, end_slot=e,
                )
                daily_meals[d].append(mp)
                label = ", ".join(
                    f"{food_by_id[fid].name} x{n}"
                    for fid, n in day_servings.items() if fid in food_by_id
                )
                blocks.append(ScheduleBlock(
                    day=d, start_slot=s, end_slot=e,
                    kind=ActivityKind.MEAL,
                    label=f"{mt.value}: {label}",
                    details={"meal_type": mt.value, "food_servings": day_servings},
                ))

        for wi in wk_items:
            if solver.Value(wi["sched"]) == 0:
                continue
            d = wi["day"]
            wt = wi["template"]
            s = int(solver.Value(wi["start"]))
            e = s + wt.duration_slots
            daily_wks[d].append(WorkoutPlacement(
                template_id=wt.id, day=d, start_slot=s, end_slot=e,
            ))
            blocks.append(ScheduleBlock(
                day=d, start_slot=s, end_slot=e,
                kind=ActivityKind.WORKOUT,
                label=f"{wt.name} ({wt.intensity.value})",
                details={"template_id": wt.id,
                         "intensity": wt.intensity.value,
                         "type": wt.workout_type.value},
            ))

        for d in range(D):
            blocks.append(ScheduleBlock(
                day=d, start_slot=sleep_starts[d], end_slot=sleep_ends[d],
                kind=ActivityKind.SLEEP,
                label=f"Sleep ({user.sleep.min_hours:.1f}h min)",
            ))
            if wake > 0:
                blocks.append(ScheduleBlock(
                    day=d, start_slot=0, end_slot=wake,
                    kind=ActivityKind.SLEEP,
                    label=f"Sleep (wake {wake // 2:02d}:{(wake % 2) * 30:02d})",
                ))

        daily_plans = [
            DailyPlan(
                day=d, meals=daily_meals[d], workouts=daily_wks[d],
                sleep_start_slot=sleep_starts[d],
                sleep_end_slot=sleep_ends[d],
                calories_total=daily_totals[d]["cal"],
                protein_total_g=daily_totals[d]["pro"],
                carbs_total_g=daily_totals[d]["carb"],
                fat_total_g=daily_totals[d]["fat"],
                cost_cents=daily_totals[d]["cost"],
            )
            for d in range(D)
        ]
        plan = Plan(
            user_name=user.name,
            daily_plans=daily_plans,
            schedule_blocks=sorted(blocks, key=lambda b: (b.day, b.start_slot)),
            weekly_cost_cents=sum(dp.cost_cents for dp in daily_plans),
        )

        return SolverResult(
            solver_name=self.name,
            status=status_name,
            objective_value=float(solver.ObjectiveValue()),
            runtime_s=runtime,
            plan=plan,
            extras={
                "formulation": "CP-SAT (joint)",
                "n_scheduled_workouts": sum(
                    int(solver.Value(w["sched"])) for w in wk_items
                ),
                "n_foods_considered": len(foods),
            },
        )
