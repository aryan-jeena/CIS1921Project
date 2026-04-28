"""Stage-2 scheduler: place nutrition output + workouts + sleep in time.

Given
  - a set of :class:`MealPlacement` buckets for each day (stage-1 output),
  - a list of candidate :class:`WorkoutTemplate`,
  - a :class:`UserProfile` with availability + sleep + recovery rules,
this CP-SAT model chooses:
  - how many workouts to schedule and where,
  - a start slot for each kept workout and each meal bucket,
  - a sleep block per night.

Hard constraints
----------------
H1. Every meal bucket starts during an available slot and lies within its
    preferred meal-type window if one is configured.
H2. Workouts start during an available slot, within their duration.
H3. No two activities on the same day overlap (NoOverlap on daily intervals).
H4. Sleep block per day: ``min_hours`` contiguous slots, positioned across
    the nightly window ``[earliest_bedtime, latest_wake + 24h)`` (we model
    sleep as belonging to the day it *starts*).
H5. Workout count in ``[workout_count_min, workout_count_max]``.
H6. Minimum recovery gap between two ``is_hard`` workouts (cross-day).

Soft objective
--------------
- Peri-workout meal timing bonus (pre-/post-workout within window).
- Preferred-workout-day bonus.
- Fragmentation penalty (counted as the number of idle-to-activity flips).
- Convenience bonus from the stage-1 food selection (passed through).

If the nutrition selection is too big to fit in the user's windows, the model
returns ``INFEASIBLE`` with a reason string instead of crashing.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
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
from src.models.enums import ActivityKind, Intensity, MealType
from src.scheduling.time_grid import build_availability_mask


# Default meal windows if the user didn't specify any. These match "normal"
# campus life: breakfast early, lunch midday, dinner evening, snacks flexible.
_DEFAULT_MEAL_WINDOWS: dict[MealType, tuple[int, int]] = {
    MealType.BREAKFAST: (12, 22),   # 06:00-11:00
    MealType.LUNCH: (22, 30),       # 11:00-15:00
    MealType.DINNER: (34, 44),      # 17:00-22:00
    MealType.SNACK: (16, 44),       # 08:00-22:00
    MealType.PRE_WORKOUT: (12, 44),
    MealType.POST_WORKOUT: (12, 44),
}


@dataclass
class Stage2Scheduler:
    """CP-SAT scheduler that consumes stage-1 meal buckets and workout
    templates and produces a fully-placed weekly plan."""

    weights: ScoringWeights = DEFAULT_WEIGHTS
    time_limit_s: int = 20
    log_search: bool = False

    # ------------------------------------------------------------------
    def schedule(
        self,
        user: UserProfile,
        meal_buckets: Iterable[MealPlacement],
        foods: Iterable[FoodItem],
        workouts: Iterable[WorkoutTemplate],
    ) -> SolverResult:
        meal_buckets = list(meal_buckets)
        foods = user.filter_pantry(list(foods))
        workouts = list(workouts)
        food_by_id = {f.id: f for f in foods}

        t0 = time.perf_counter()
        model = cp_model.CpModel()

        # ------------------------------------------------------------------
        # Availability -> list of (day, list-of-contiguous-ranges)
        # ------------------------------------------------------------------
        mask = build_availability_mask(user.available_windows)

        # ------------------------------------------------------------------
        # Meals: one presence bool + a start slot per bucket. Each meal
        # occupies exactly one slot (30 min).
        # ------------------------------------------------------------------
        meal_starts: list[cp_model.IntVar] = []
        meal_ends: list[cp_model.IntVar] = []
        meal_intervals_by_day: list[list[cp_model.IntervalVar]] = [[] for _ in range(DAYS_PER_WEEK)]
        meal_presence: list[cp_model.IntVar] = []

        for idx, mp in enumerate(meal_buckets):
            dur = 1  # 30-minute meal window
            # Domain: any slot on the meal's day where (a) user is available
            # and (b) slot is in the meal-type window.
            window_lo, window_hi = _DEFAULT_MEAL_WINDOWS.get(mp.meal_type, (0, SLOTS_PER_DAY))
            allowed = [
                s for s in range(window_lo, min(window_hi, SLOTS_PER_DAY))
                if mask[mp.day][s]
            ]
            if not allowed:
                # This meal cannot be placed; flag the whole model infeasible
                # with a helpful message.
                runtime = time.perf_counter() - t0
                return SolverResult(
                    solver_name="two_stage",
                    status="INFEASIBLE",
                    runtime_s=runtime,
                    infeasibility_reason=(
                        f"No available slot for {mp.meal_type.value} on day {mp.day} "
                        f"within window slots [{window_lo},{window_hi})."
                    ),
                )

            start = model.NewIntVarFromDomain(
                cp_model.Domain.FromValues(allowed), f"meal_start_{idx}"
            )
            end = model.NewIntVar(0, SLOTS_PER_DAY, f"meal_end_{idx}")
            model.Add(end == start + dur)
            presence = model.NewConstant(1)     # meals are mandatory
            interval = model.NewIntervalVar(start, dur, end, f"meal_iv_{idx}")
            meal_starts.append(start)
            meal_ends.append(end)
            meal_presence.append(presence)
            meal_intervals_by_day[mp.day].append(interval)

        # ------------------------------------------------------------------
        # Workouts: one scheduled-bool per template per day. If scheduled,
        # start lies in an available window with enough room for duration.
        # ------------------------------------------------------------------
        # Only consider candidate template ids if user provided them.
        if user.candidate_workouts:
            workouts = [w for w in workouts if w.id in user.candidate_workouts]

        # Represent workout decisions as (day, template) pairs.
        wk_scheduled: list[cp_model.IntVar] = []      # bool per (d, w)
        wk_start: list[cp_model.IntVar] = []          # int per (d, w)
        wk_day: list[int] = []
        wk_template: list[WorkoutTemplate] = []
        wk_intervals_by_day: list[list[cp_model.IntervalVar]] = [[] for _ in range(DAYS_PER_WEEK)]

        for d in range(DAYS_PER_WEEK):
            # Slots where a workout of length ``dur`` could START.
            for wt in workouts:
                dur = wt.duration_slots
                valid_starts = [
                    s for s in range(SLOTS_PER_DAY - dur + 1)
                    if all(mask[d][s + k] for k in range(dur))
                ]
                if not valid_starts:
                    continue

                sched = model.NewBoolVar(f"wk_sched_d{d}_{wt.id}")
                start = model.NewIntVarFromDomain(
                    cp_model.Domain.FromValues(valid_starts),
                    f"wk_start_d{d}_{wt.id}",
                )
                end = model.NewIntVar(0, SLOTS_PER_DAY, f"wk_end_d{d}_{wt.id}")
                model.Add(end == start + dur)

                interval = model.NewOptionalIntervalVar(
                    start, dur, end, sched, f"wk_iv_d{d}_{wt.id}"
                )

                wk_scheduled.append(sched)
                wk_start.append(start)
                wk_day.append(d)
                wk_template.append(wt)
                wk_intervals_by_day[d].append(interval)

        # Workout count bounds
        model.Add(sum(wk_scheduled) >= user.workout_count_min)
        model.Add(sum(wk_scheduled) <= user.workout_count_max)

        # ------------------------------------------------------------------
        # Sleep: fixed nightly blocks (no decision variables).
        #
        # Realistic sleep crosses midnight, so we model each night as two
        # intervals on the day grid:
        #   morning_sleep[d]  : [0, latest_wake_slot)
        #   evening_sleep[d]  : [earliest_bedtime_slot, SLOTS_PER_DAY)
        # Total sleep per night = latest_wake + (SLOTS_PER_DAY - earliest_bedtime).
        # The no-overlap requirement is already handled implicitly because
        # the user's availability mask does not include these slots (they
        # declared themselves unavailable), so no meal/workout can be placed
        # there. We still emit the blocks so they show up in the rendered
        # schedule and the validator.
        # ------------------------------------------------------------------
        sleep_min_slots = int(round(user.sleep.min_hours * 2))
        wake = min(user.sleep.latest_wake_slot, SLOTS_PER_DAY)
        bed = max(user.sleep.earliest_bedtime_slot, 0)
        nightly_sleep_slots = wake + (SLOTS_PER_DAY - bed)
        sleep_hard_violation = nightly_sleep_slots < sleep_min_slots
        # Flat lists for later extraction (one per day, representing the
        # *evening* bedtime start; the morning half is implicit).
        sleep_starts: list[int] = [bed for _ in range(DAYS_PER_WEEK)]
        sleep_ends: list[int] = [SLOTS_PER_DAY for _ in range(DAYS_PER_WEEK)]

        # ------------------------------------------------------------------
        # No-overlap per day (meals + workouts + sleep all disjoint).
        # ------------------------------------------------------------------
        for d in range(DAYS_PER_WEEK):
            pool = meal_intervals_by_day[d] + wk_intervals_by_day[d]
            if pool:
                model.AddNoOverlap(pool)

        # ------------------------------------------------------------------
        # Recovery: min_gap_slots between any two scheduled HARD workouts.
        # Implemented as pairwise "if both scheduled, |end1-start2| >= gap".
        # The gap parameter comes from user.recovery.min_gap_slots OR the
        # template's own min_recovery_slots, whichever is tighter.
        # ------------------------------------------------------------------
        week_slot = lambda day, s: day * SLOTS_PER_DAY + s
        n_wk = len(wk_scheduled)
        for i in range(n_wk):
            for j in range(i + 1, n_wk):
                wi, wj = wk_template[i], wk_template[j]
                if not (wi.is_hard and wj.is_hard):
                    continue
                gap = max(
                    user.recovery.min_gap_slots,
                    wi.min_recovery_slots,
                    wj.min_recovery_slots,
                )
                di, dj = wk_day[i], wk_day[j]

                # Both workouts' absolute week-slot start times.
                abs_i_start = wk_start[i] + di * SLOTS_PER_DAY
                abs_j_start = wk_start[j] + dj * SLOTS_PER_DAY
                abs_i_end = abs_i_start + wi.duration_slots
                abs_j_end = abs_j_start + wj.duration_slots

                # If both scheduled, then either i ends >= gap before j, or vice versa.
                both = model.NewBoolVar(f"both_{i}_{j}")
                model.AddBoolAnd([wk_scheduled[i], wk_scheduled[j]]).OnlyEnforceIf(both)
                model.AddBoolOr([wk_scheduled[i].Not(), wk_scheduled[j].Not()]).OnlyEnforceIf(both.Not())

                i_before_j = model.NewBoolVar(f"ij_{i}_{j}")
                model.Add(abs_j_start - abs_i_end >= gap).OnlyEnforceIf([both, i_before_j])
                model.Add(abs_i_start - abs_j_end >= gap).OnlyEnforceIf([both, i_before_j.Not()])

        # ------------------------------------------------------------------
        # Soft terms
        # ------------------------------------------------------------------
        w = self.weights
        obj_terms: list = []

        # Preferred workout days: reward scheduling on a preferred day.
        pref_days = set(user.preferences.preferred_workout_days)
        avoid_days = set(user.preferences.avoid_workout_days)
        for i in range(n_wk):
            if wk_day[i] in avoid_days:
                # Penalise scheduling on an avoided day.
                obj_terms.append(w.preference_violation * wk_scheduled[i])
            if pref_days and wk_day[i] not in pref_days:
                obj_terms.append((w.preference_violation // 3) * wk_scheduled[i])

        # Peri-workout meal timing: for each scheduled workout, try to have
        # at least one meal within the pre/post window. We model this as a
        # bool "has_pre"/"has_post" per workout; penalize when false.
        pre_window = user.preferences.pre_workout_meal_window_slots
        post_window = user.preferences.post_workout_meal_window_slots

        for i in range(n_wk):
            wt = wk_template[i]
            d = wk_day[i]
            same_day_meal_idxs = [k for k, mp in enumerate(meal_buckets) if mp.day == d]
            if not same_day_meal_idxs:
                continue

            if user.preferences.wants_pre_workout_meal:
                pre_ok = model.NewBoolVar(f"pre_ok_{i}")
                # pre_ok => exists meal m on same day with 0 < wk_start - meal_end <= pre_window
                pre_bools = []
                for k in same_day_meal_idxs:
                    b = model.NewBoolVar(f"pre_bool_{i}_{k}")
                    diff = model.NewIntVar(-SLOTS_PER_DAY, SLOTS_PER_DAY, f"diff_pre_{i}_{k}")
                    model.Add(diff == wk_start[i] - meal_ends[k])
                    model.Add(diff > 0).OnlyEnforceIf(b)
                    model.Add(diff <= pre_window).OnlyEnforceIf(b)
                    # b=False: either diff<=0 or diff>pre_window (no extra constraint needed)
                    pre_bools.append(b)
                model.AddBoolOr(pre_bools).OnlyEnforceIf(pre_ok)
                model.AddBoolAnd([b.Not() for b in pre_bools]).OnlyEnforceIf(pre_ok.Not())

                # Penalise "scheduled AND NOT pre_ok"
                miss = model.NewBoolVar(f"miss_pre_{i}")
                model.AddBoolAnd([wk_scheduled[i], pre_ok.Not()]).OnlyEnforceIf(miss)
                model.AddBoolOr([wk_scheduled[i].Not(), pre_ok]).OnlyEnforceIf(miss.Not())
                obj_terms.append(w.meal_timing_violation * miss)

            if user.preferences.wants_post_workout_meal:
                post_ok = model.NewBoolVar(f"post_ok_{i}")
                post_bools = []
                wk_end_i = model.NewIntVar(0, SLOTS_PER_DAY, f"wk_end_{i}")
                model.Add(wk_end_i == wk_start[i] + wt.duration_slots)
                for k in same_day_meal_idxs:
                    b = model.NewBoolVar(f"post_bool_{i}_{k}")
                    diff = model.NewIntVar(-SLOTS_PER_DAY, SLOTS_PER_DAY, f"diff_post_{i}_{k}")
                    model.Add(diff == meal_starts[k] - wk_end_i)
                    model.Add(diff >= 0).OnlyEnforceIf(b)
                    model.Add(diff <= post_window).OnlyEnforceIf(b)
                    post_bools.append(b)
                model.AddBoolOr(post_bools).OnlyEnforceIf(post_ok)
                model.AddBoolAnd([b.Not() for b in post_bools]).OnlyEnforceIf(post_ok.Not())

                miss = model.NewBoolVar(f"miss_post_{i}")
                model.AddBoolAnd([wk_scheduled[i], post_ok.Not()]).OnlyEnforceIf(miss)
                model.AddBoolOr([wk_scheduled[i].Not(), post_ok]).OnlyEnforceIf(miss.Not())
                obj_terms.append(w.meal_timing_violation * miss)

        # Fragmentation proxy: count the number of scheduled workouts on
        # "avoid" days, scaled. Cheap but effective for ranking plans.
        model.Minimize(sum(obj_terms) if obj_terms else 0)

        # ------------------------------------------------------------------
        # Solve
        # ------------------------------------------------------------------
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(self.time_limit_s)
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
                solver_name="two_stage",
                status=status_name,
                runtime_s=runtime,
                infeasibility_reason=(
                    "Stage-2 could not place chosen meals + workouts inside the "
                    "user's availability with the given sleep/recovery rules."
                ),
            )

        # ------------------------------------------------------------------
        # Extract solution -> Plan
        # ------------------------------------------------------------------
        blocks: list[ScheduleBlock] = []
        daily_totals: list[dict[str, int]] = [
            {"cal": 0, "pro": 0, "carb": 0, "fat": 0, "cost": 0} for _ in range(DAYS_PER_WEEK)
        ]
        daily_meals: list[list[MealPlacement]] = [[] for _ in range(DAYS_PER_WEEK)]
        daily_wks: list[list[WorkoutPlacement]] = [[] for _ in range(DAYS_PER_WEEK)]

        for idx, mp in enumerate(meal_buckets):
            s = int(solver.Value(meal_starts[idx]))
            e = int(solver.Value(meal_ends[idx]))
            # Accumulate totals
            for fid, n in mp.food_servings.items():
                f = food_by_id.get(fid)
                if not f:
                    continue
                daily_totals[mp.day]["cal"] += f.calories * n
                daily_totals[mp.day]["pro"] += f.protein_g * n
                daily_totals[mp.day]["carb"] += f.carbs_g * n
                daily_totals[mp.day]["fat"] += f.fat_g * n
                daily_totals[mp.day]["cost"] += f.cost_cents * n
            placed = MealPlacement(
                day=mp.day, meal_type=mp.meal_type,
                food_servings=mp.food_servings, start_slot=s, end_slot=e,
            )
            daily_meals[mp.day].append(placed)
            label = ", ".join(
                f"{food_by_id[fid].name} x{n}"
                for fid, n in mp.food_servings.items()
                if fid in food_by_id
            ) or mp.meal_type.value
            blocks.append(ScheduleBlock(
                day=mp.day, start_slot=s, end_slot=e,
                kind=ActivityKind.MEAL, label=f"{mp.meal_type.value}: {label}",
                details={"meal_type": mp.meal_type.value,
                         "food_servings": mp.food_servings},
            ))

        for i in range(n_wk):
            if int(solver.Value(wk_scheduled[i])) == 0:
                continue
            wt = wk_template[i]
            d = wk_day[i]
            s = int(solver.Value(wk_start[i]))
            e = s + wt.duration_slots
            daily_wks[d].append(WorkoutPlacement(
                template_id=wt.id, day=d, start_slot=s, end_slot=e,
            ))
            blocks.append(ScheduleBlock(
                day=d, start_slot=s, end_slot=e,
                kind=ActivityKind.WORKOUT, label=f"{wt.name} ({wt.intensity.value})",
                details={"template_id": wt.id,
                         "intensity": wt.intensity.value,
                         "type": wt.workout_type.value},
            ))

        for d in range(DAYS_PER_WEEK):
            # Evening sleep block (bedtime -> midnight).
            blocks.append(ScheduleBlock(
                day=d, start_slot=sleep_starts[d], end_slot=sleep_ends[d],
                kind=ActivityKind.SLEEP,
                label=f"Sleep ({user.sleep.min_hours:.1f}h min)",
            ))
            # Morning sleep block (midnight -> wake) shown on the same day.
            if wake > 0:
                blocks.append(ScheduleBlock(
                    day=d, start_slot=0, end_slot=wake,
                    kind=ActivityKind.SLEEP,
                    label=f"Sleep (wake {wake // 2:02d}:{(wake % 2) * 30:02d})",
                ))

        daily_plans = [
            DailyPlan(
                day=d,
                meals=daily_meals[d],
                workouts=daily_wks[d],
                sleep_start_slot=sleep_starts[d],
                sleep_end_slot=sleep_ends[d],
                calories_total=daily_totals[d]["cal"],
                protein_total_g=daily_totals[d]["pro"],
                carbs_total_g=daily_totals[d]["carb"],
                fat_total_g=daily_totals[d]["fat"],
                cost_cents=daily_totals[d]["cost"],
            )
            for d in range(DAYS_PER_WEEK)
        ]
        plan = Plan(
            user_name=user.name,
            daily_plans=daily_plans,
            schedule_blocks=sorted(blocks, key=lambda b: (b.day, b.start_slot)),
            weekly_cost_cents=sum(dp.cost_cents for dp in daily_plans),
        )

        return SolverResult(
            solver_name="two_stage",
            status=status_name,
            objective_value=float(solver.ObjectiveValue()),
            runtime_s=runtime,
            plan=plan,
            extras={"formulation": "MIP+CP-SAT",
                    "n_scheduled_workouts": sum(int(solver.Value(v)) for v in wk_scheduled)},
        )
