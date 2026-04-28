"""Live optimization viewer: a Flask app that streams every intermediate
CP-SAT solution to the browser as the joint solver searches.

Usage::

    python -m src.app.live_server [--port 5050]
    # then open http://127.0.0.1:5050/

How it works
------------
CP-SAT's ``CpSolverSolutionCallback`` fires every time the solver finds a
better feasible solution. We register a callback that snapshots the
current variable values into a JSON-friendly dict and pushes it onto a
``queue.Queue``. A Server-Sent-Events (SSE) endpoint reads from that queue
and forwards each update to the browser, which redraws the weekly grid.

The solver runs in a background thread so the SSE handler can stream
incrementally without blocking. When the solve finishes the callback
puts a final ``status`` event on the queue and then ``None`` as a
sentinel; the SSE generator returns once it sees the sentinel.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import threading
import time
import webbrowser
from pathlib import Path
from typing import Iterable

from flask import Flask, Response, jsonify, render_template, request
from ortools.sat.python import cp_model

from src.config.settings import (
    DAY_NAMES,
    DAYS_PER_WEEK,
    SLOTS_PER_DAY,
    DEFAULT_WEIGHTS,
    slot_to_time,
)
from src.data_ingestion.food_catalog import build_food_catalog
from src.data_ingestion.workouts import load_sample_workouts
from src.experiments.instance_generator import (
    InstanceParams,
    apply_pantry_to_user,
    generate_user,
)
from src.experiments.presets import list_presets, load_preset
from src.models.domain import (
    DailyPlan,
    FoodItem,
    MealPlacement,
    Plan,
    ScheduleBlock,
    UserProfile,
    WorkoutPlacement,
    WorkoutTemplate,
)
from src.models.enums import ActivityKind, MealType
from src.scheduling.time_grid import build_availability_mask
from src.solvers.joint_cpsat import (
    JointCPSATSolver,
    _DEFAULT_MEAL_WINDOWS,
    _MEAL_ORDER,
)


HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"
STATIC = HERE / "static"
TEMPLATES.mkdir(exist_ok=True)
STATIC.mkdir(exist_ok=True)

app = Flask(__name__, template_folder=str(TEMPLATES), static_folder=str(STATIC))


# ---------------------------------------------------------------------------
# Streaming solver
# ---------------------------------------------------------------------------
class StreamingCallback(cp_model.CpSolverSolutionCallback):
    """Snapshot the active CP-SAT solution and push it onto a queue.

    Stores enough variable references at construction time that
    on_solution_callback can rebuild a small JSON-serialisable dict
    representing the placed meals + workouts + sleep + hydration on the
    7×48 grid.
    """

    def __init__(self, q, foods, meal_types, serve, meal_active,
                 meal_start_vars, wk_items, sleep_starts, sleep_ends, wake,
                 hydration_slot_vars_by_day, t0):
        super().__init__()
        self.q = q
        self.foods = foods
        self.meal_types = meal_types
        self.serve = serve
        self.meal_active = meal_active
        self.meal_start_vars = meal_start_vars
        self.wk_items = wk_items
        self.sleep_starts = sleep_starts
        self.sleep_ends = sleep_ends
        self.wake = wake
        self.hydration_slot_vars_by_day = hydration_slot_vars_by_day
        self.t0 = t0
        self.count = 0

    def on_solution_callback(self):
        self.count += 1
        # Build a flat list of {day, start, end, kind, label} blocks.
        blocks = []
        # Sleep — fixed blocks, drawn each time so the frontend has them.
        for d in range(DAYS_PER_WEEK):
            blocks.append({
                "day": d, "start": self.sleep_starts[d],
                "end": self.sleep_ends[d],
                "kind": "sleep", "label": "sleep",
            })
            if self.wake > 0:
                blocks.append({
                    "day": d, "start": 0, "end": self.wake,
                    "kind": "sleep", "label": "sleep",
                })
        # Meals — stream food servings too so the label changes when the
        # solver swaps foods around between iterations.
        M = len(self.meal_types)
        for d in range(DAYS_PER_WEEK):
            for m, mt in enumerate(self.meal_types):
                if self.Value(self.meal_active[d][m]) == 0:
                    continue
                start = int(self.Value(self.meal_start_vars[(d, m)]))
                items = []
                for i, f in enumerate(self.foods):
                    n = int(self.Value(self.serve[d][m][i]))
                    if n > 0:
                        items.append({"name": f.name.split(":")[-1].strip(),
                                      "n": n})
                blocks.append({
                    "day": d, "start": start, "end": start + 1,
                    "kind": "meal", "label": mt.value,
                    "id": f"meal-{d}-{m}",
                    "items": items,
                })
        # Workouts
        for wi in self.wk_items:
            if self.Value(wi["sched"]) == 0:
                continue
            d = wi["day"]
            wt = wi["template"]
            start = int(self.Value(wi["start"]))
            blocks.append({
                "day": d, "start": start, "end": start + wt.duration_slots,
                "kind": "workout",
                "label": wt.name,
                "intensity": wt.intensity.value,
                "id": f"wk-{wt.id}",
            })
        # Hydration
        for d in range(DAYS_PER_WEEK):
            for slot, bvar in self.hydration_slot_vars_by_day[d]:
                if int(self.Value(bvar)) == 1:
                    blocks.append({
                        "day": d, "start": slot, "end": slot + 1,
                        "kind": "hydration", "label": "💧",
                        "id": f"hyd-{d}-{slot}",
                    })

        evt = {
            "type": "solution",
            "n": self.count,
            "objective": float(self.ObjectiveValue()),
            "best_bound": float(self.BestObjectiveBound()),
            "elapsed_s": round(time.perf_counter() - self.t0, 3),
            "blocks": blocks,
        }
        self.q.put(evt)


def _build_and_solve_streaming(user, foods, workouts, q, time_limit_s):
    """Mirror of JointCPSATSolver.solve but with a streaming callback.

    Pulled out into this module so we can attach a callback that has direct
    references to every variable we want to read out incrementally. The
    underlying model is identical to the production solver — same hard
    constraints, same objective — only the search-strategy callback is new.
    """
    from src.solvers.joint_cpsat import JointCPSATSolver  # noqa: F401

    foods = [f for f in foods if f.allowed_for(user.dietary_exclusions)]
    foods = user.filter_pantry(foods)
    workouts = list(workouts)
    if user.candidate_workouts:
        workouts = [w for w in workouts if w.id in user.candidate_workouts]

    if not foods:
        q.put({"type": "status",
               "status": "INFEASIBLE",
               "message": "Empty food catalog after filters."})
        q.put(None)
        return

    model = cp_model.CpModel()
    mask = build_availability_mask(user.available_windows)
    D = DAYS_PER_WEEK
    M = min(user.max_meals_per_day, len(_MEAL_ORDER))
    meal_types = list(_MEAL_ORDER[:M])

    # Sleep clamp
    wake = min(user.sleep.latest_wake_slot, SLOTS_PER_DAY)
    bed = max(user.sleep.earliest_bedtime_slot, 0)

    # Nutrition vars
    serve = []
    for d in range(D):
        day_row = []
        for m, mt in enumerate(meal_types):
            meal_row = []
            for i, f in enumerate(foods):
                if mt not in f.meal_types:
                    meal_row.append(model.NewConstant(0))
                    continue
                meal_row.append(
                    model.NewIntVar(0, f.max_servings_per_day,
                                    f"serve_d{d}_m{m}_f{i}")
                )
            day_row.append(meal_row)
        serve.append(day_row)

    meal_active = []
    for d in range(D):
        row = []
        for m in range(M):
            active = model.NewBoolVar(f"meal_active_d{d}_m{m}")
            total_m = sum(serve[d][m][i] for i in range(len(foods)))
            model.Add(total_m >= 1).OnlyEnforceIf(active)
            model.Add(total_m == 0).OnlyEnforceIf(active.Not())
            row.append(active)
        meal_active.append(row)

    for d in range(D):
        for i, f in enumerate(foods):
            model.Add(sum(serve[d][m][i] for m in range(M)) <= f.max_servings_per_day)

    daily_cal, daily_pro, daily_carb, daily_fat = [], [], [], []
    for d in range(D):
        cal = sum(f.calories * serve[d][m][i] for m in range(M) for i, f in enumerate(foods))
        pro = sum(f.protein_g * serve[d][m][i] for m in range(M) for i, f in enumerate(foods))
        carb = sum(f.carbs_g * serve[d][m][i] for m in range(M) for i, f in enumerate(foods))
        fat = sum(f.fat_g * serve[d][m][i] for m in range(M) for i, f in enumerate(foods))
        daily_cal.append(cal); daily_pro.append(pro)
        daily_carb.append(carb); daily_fat.append(fat)
        model.Add(cal >= user.calorie_target - user.calorie_tolerance)
        model.Add(cal <= user.calorie_target + user.calorie_tolerance)
        model.Add(pro >= user.protein_min_g)

    total_cost = sum(
        f.cost_cents * serve[d][m][i]
        for d in range(D) for m in range(M) for i, f in enumerate(foods)
    )
    model.Add(total_cost <= user.weekly_budget_cents)

    # Per-meal protein shortfall
    pro_shortfall_vars = []
    for d in range(D):
        for m in range(M):
            short = model.NewIntVar(0, user.min_protein_per_meal_g,
                                    f"pro_short_d{d}_m{m}")
            mp = sum(f.protein_g * serve[d][m][i] for i, f in enumerate(foods))
            model.Add(short >= user.min_protein_per_meal_g * meal_active[d][m] - mp)
            pro_shortfall_vars.append(short)

    # Meal placement
    meal_start_vars = {}
    meal_end_vars = {}
    meal_intervals_by_day = [[] for _ in range(D)]
    for d in range(D):
        for m, mt in enumerate(meal_types):
            window_lo, window_hi = _DEFAULT_MEAL_WINDOWS[mt]
            allowed = [
                s for s in range(window_lo, min(window_hi, SLOTS_PER_DAY))
                if mask[d][s] and wake <= s < bed
            ]
            if not allowed:
                model.Add(meal_active[d][m] == 0)
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

    # Workout placement
    wk_items = []
    wk_intervals_by_day = [[] for _ in range(D)]
    for d in range(D):
        for wt in workouts:
            dur = wt.duration_slots
            valid = [
                s for s in range(SLOTS_PER_DAY - dur + 1)
                if all(mask[d][s + k] for k in range(dur))
                and s >= wake and s + dur <= bed
            ]
            if not valid:
                continue
            sched = model.NewBoolVar(f"wk_d{d}_{wt.id}")
            start = model.NewIntVarFromDomain(
                cp_model.Domain.FromValues(valid), f"wk_start_d{d}_{wt.id}",
            )
            end = model.NewIntVar(0, SLOTS_PER_DAY, f"wk_end_d{d}_{wt.id}")
            model.Add(end == start + dur)
            iv = model.NewOptionalIntervalVar(start, dur, end, sched,
                                              f"wk_iv_d{d}_{wt.id}")
            wk_intervals_by_day[d].append(iv)
            wk_items.append({"day": d, "template": wt, "sched": sched,
                             "start": start, "end": end})

    if wk_items:
        model.Add(sum(w["sched"] for w in wk_items) >= user.workout_count_min)
        model.Add(sum(w["sched"] for w in wk_items) <= user.workout_count_max)

    sleep_starts = [bed for _ in range(D)]
    sleep_ends = [SLOTS_PER_DAY for _ in range(D)]

    for d in range(D):
        pool = meal_intervals_by_day[d] + wk_intervals_by_day[d]
        if pool:
            model.AddNoOverlap(pool)

    # Recovery spacing
    for i, wi in enumerate(wk_items):
        for j in range(i + 1, len(wk_items)):
            wj = wk_items[j]
            if not (wi["template"].is_hard and wj["template"].is_hard):
                continue
            gap = max(user.recovery.min_gap_slots,
                      wi["template"].min_recovery_slots,
                      wj["template"].min_recovery_slots)
            asi = wi["start"] + wi["day"] * SLOTS_PER_DAY
            asj = wj["start"] + wj["day"] * SLOTS_PER_DAY
            aei = asi + wi["template"].duration_slots
            aej = asj + wj["template"].duration_slots
            both = model.NewBoolVar(f"both_rec_{i}_{j}")
            model.AddBoolAnd([wi["sched"], wj["sched"]]).OnlyEnforceIf(both)
            model.AddBoolOr([wi["sched"].Not(), wj["sched"].Not()]).OnlyEnforceIf(both.Not())
            order = model.NewBoolVar(f"order_{i}_{j}")
            model.Add(asj - aei >= gap).OnlyEnforceIf([both, order])
            model.Add(asi - aej >= gap).OnlyEnforceIf([both, order.Not()])

    hard_on_day = [model.NewBoolVar(f"hard_on_{d}") for d in range(D)]
    for d in range(D):
        day_hard = [w["sched"] for w in wk_items
                    if w["day"] == d and w["template"].is_hard]
        if day_hard:
            model.Add(sum(day_hard) >= 1).OnlyEnforceIf(hard_on_day[d])
            model.Add(sum(day_hard) == 0).OnlyEnforceIf(hard_on_day[d].Not())
        else:
            model.Add(hard_on_day[d] == 0)
    max_cons = user.recovery.max_consecutive_hard_days
    for d in range(D - max_cons):
        model.Add(sum(hard_on_day[d:d + max_cons + 1]) <= max_cons)

    # Hydration
    hydration_shortfall_vars = []
    hydration_slot_vars_by_day = [[] for _ in range(D)]
    if user.hydration.enabled and user.hydration.target_reminders_per_day > 0:
        h_lo = max(0, min(user.hydration.earliest_slot, SLOTS_PER_DAY))
        h_hi = max(h_lo + 1, min(user.hydration.latest_slot, SLOTS_PER_DAY))
        h_lo = max(h_lo, wake)
        h_hi = min(h_hi, bed)
        target = user.hydration.target_reminders_per_day
        spacing = max(1, user.hydration.min_spacing_slots)
        for d in range(D):
            slot_vars = []
            for s in range(h_lo, h_hi):
                b = model.NewBoolVar(f"hyd_d{d}_s{s}")
                slot_vars.append(b)
                hydration_slot_vars_by_day[d].append((s, b))
            if spacing > 1:
                for s in range(len(slot_vars) - spacing + 1):
                    model.Add(sum(slot_vars[s:s + spacing]) <= 1)
            count = sum(slot_vars) if slot_vars else 0
            short = model.NewIntVar(0, target, f"hyd_short_d{d}")
            model.Add(short >= target - count)
            hydration_shortfall_vars.append(short)

    # Objective
    w = DEFAULT_WEIGHTS
    obj = []
    for d in range(D):
        gap = model.NewIntVar(0, user.protein_target_g, f"pro_tgt_gap_{d}")
        model.Add(gap >= user.protein_target_g - daily_pro[d])
        obj.append(w.protein_deviation * gap)
    big = 2_000
    for d in range(D):
        dc = model.NewIntVar(0, big, f"carb_dev_{d}")
        model.Add(dc >= daily_carb[d] - user.carb_target_g)
        model.Add(dc >= user.carb_target_g - daily_carb[d])
        obj.append(w.macro_deviation * dc)
        df = model.NewIntVar(0, big, f"fat_dev_{d}")
        model.Add(df >= daily_fat[d] - user.fat_target_g)
        model.Add(df >= user.fat_target_g - daily_fat[d])
        obj.append(w.macro_deviation * df)
    obj.append(w.cost_weight * total_cost)
    for v in pro_shortfall_vars:
        obj.append(w.protein_per_meal_shortfall * v)
    for short in hydration_shortfall_vars:
        obj.append(w.hydration_shortfall * short)
    convenience_bonus = sum(
        f.convenience * serve[d][m][i]
        for d in range(D) for m in range(M) for i, f in enumerate(foods)
    )
    obj.append(-1 * convenience_bonus)
    model.Minimize(sum(obj))

    # Solve
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_s)
    solver.parameters.num_search_workers = 1   # easier to follow live

    t0 = time.perf_counter()
    cb = StreamingCallback(
        q, foods, meal_types, serve, meal_active, meal_start_vars,
        wk_items, sleep_starts, sleep_ends, wake,
        hydration_slot_vars_by_day, t0,
    )

    q.put({
        "type": "start",
        "user_name": user.name,
        "n_foods": len(foods),
        "n_workouts": len(workouts),
        "time_limit_s": time_limit_s,
        "calorie_target": user.calorie_target,
        "protein_min": user.protein_min_g,
        "workout_count_min": user.workout_count_min,
        "workout_count_max": user.workout_count_max,
    })

    status = solver.Solve(model, cb)
    elapsed = time.perf_counter() - t0
    status_name = {
        cp_model.OPTIMAL: "OPTIMAL",
        cp_model.FEASIBLE: "FEASIBLE",
        cp_model.INFEASIBLE: "INFEASIBLE",
        cp_model.MODEL_INVALID: "ERROR",
        cp_model.UNKNOWN: "TIMEOUT",
    }.get(status, "ERROR")

    q.put({
        "type": "status",
        "status": status_name,
        "elapsed_s": round(elapsed, 3),
        "n_solutions": cb.count,
        "final_objective": (
            float(solver.ObjectiveValue())
            if status_name in {"OPTIMAL", "FEASIBLE"} else None
        ),
    })
    q.put(None)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    presets = list_presets()
    return render_template("live.html", presets=presets)


@app.route("/presets")
def presets_route():
    return jsonify({"presets": list_presets()})


@app.route("/solve")
def solve_route():
    preset = request.args.get("preset", "dense_training")
    time_limit = int(request.args.get("time_limit", 12))

    user = load_preset(preset)
    foods = build_food_catalog(exclusions=user.dietary_exclusions)
    workouts = load_sample_workouts()

    q: queue.Queue = queue.Queue()
    thread = threading.Thread(
        target=_build_and_solve_streaming,
        args=(user, foods, workouts, q, time_limit),
        daemon=True,
    )
    thread.start()

    def stream():
        while True:
            evt = q.get()
            if evt is None:
                yield "event: done\ndata: {}\n\n"
                break
            yield f"data: {json.dumps(evt)}\n\n"

    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live CP-SAT viewer")
    parser.add_argument("--port", type=int, default=5050)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-open", action="store_true",
                        help="Don't auto-open the browser")
    args = parser.parse_args(argv)
    if not args.no_open and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        # Open a browser tab once when the server first starts.
        threading.Timer(0.7, lambda: webbrowser.open(
            f"http://{args.host}:{args.port}/")).start()
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
