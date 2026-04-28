"""Lightweight Streamlit UI.

Run with::

    streamlit run src/app/streamlit_app.py

Design goal: expose the three solvers behind a form, show the resulting
weekly plan + metrics, and let the user inspect infeasibility reasons. We
do *not* implement auth, user accounts, persistence, or CRUD -- that would
divert effort from the optimization side of the project.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

from src.data_ingestion.food_catalog import build_food_catalog
from src.data_ingestion.workouts import load_sample_workouts
from src.evaluation.metrics import compute_metrics
from src.evaluation.validator import validate_plan
from src.experiments.instance_generator import (
    InstanceParams,
    generate_user,
)
from src.experiments.presets import list_presets, load_preset
from src.models.enums import DietaryTag
from src.solvers import ALL_SOLVERS
from src.visualization.schedule_view import render_schedule_to_figure


st.set_page_config(
    page_title="Health Schedule Optimizer",
    page_icon="💪",
    layout="wide",
)

st.title("🥗 Constraint-Based Training & Nutrition Optimizer")
st.caption("CIS 1921 final project — LP / MIP / CP-SAT formulations")


# ---------------------------------------------------------------------------
# Sidebar form
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("Instance")
    mode = st.radio("Starting point", ["Scenario", "Preset"], index=0)

    if mode == "Scenario":
        scenario = st.selectbox(
            "Built-in scenario",
            [
                "balanced",
                "budget_student",
                "lean_bulk",
                "aggressive_cut",
                "vegetarian_athlete",
                "tight_class_schedule",
                "early_morning_lifter",
                "recovery_constrained",
                "impossible_case",
            ],
        )
        seed = st.number_input("Seed", min_value=0, value=1921, step=1)
        user = generate_user(scenario, InstanceParams(seed=int(seed)))
    else:
        presets = list_presets()
        preset_name = st.selectbox("Preset JSON", presets or ["(none)"])
        if presets:
            user = load_preset(preset_name)
        else:
            st.warning("No presets found under configs/presets/.")
            user = generate_user("balanced")

    st.subheader("Nutrition targets")
    user.calorie_target = st.number_input("Calorie target",
                                          value=user.calorie_target, step=50)
    user.calorie_tolerance = st.number_input("Calorie +/- tolerance",
                                             value=user.calorie_tolerance, step=10)
    user.protein_min_g = st.number_input("Protein floor (g)",
                                         value=user.protein_min_g, step=5)
    user.protein_target_g = st.number_input("Protein target (g)",
                                            value=user.protein_target_g, step=5)
    user.weekly_budget_cents = st.number_input(
        "Weekly budget (cents)",
        value=user.weekly_budget_cents, step=500,
    )

    st.subheader("Workouts")
    user.workout_count_min = st.number_input("Min workouts",
                                             value=user.workout_count_min, step=1)
    user.workout_count_max = st.number_input("Max workouts",
                                             value=user.workout_count_max, step=1)

    st.subheader("Solver")
    solver_choice = st.selectbox("Solver", list(ALL_SOLVERS.keys()),
                                 index=len(ALL_SOLVERS) - 1)
    time_limit = st.slider("Time limit (s)", 5, 90, 20)

    st.subheader("Dietary exclusions")
    exclusion_choices = [e.value for e in DietaryTag if e.name.startswith("CONTAINS_")
                          or e in (DietaryTag.VEGAN, DietaryTag.VEGETARIAN,
                                    DietaryTag.GLUTEN_FREE)]
    exclusions_ui = st.multiselect("Exclude these tags",
                                   exclusion_choices, default=[])
    user.dietary_exclusions = [DietaryTag(x) for x in exclusions_ui]

    solve_button = st.button("Solve", type="primary", use_container_width=True)


# ---------------------------------------------------------------------------
# Main pane
# ---------------------------------------------------------------------------
if solve_button:
    with st.spinner(f"Running {solver_choice}..."):
        solver_cls = ALL_SOLVERS[solver_choice]
        solver = solver_cls(time_limit_s=int(time_limit))
        foods = build_food_catalog(exclusions=user.dietary_exclusions)
        workouts = load_sample_workouts()
        result = solver.solve(user, foods, workouts)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Status", result.status)
    c2.metric("Runtime (s)", f"{result.runtime_s:.2f}")
    c3.metric("Objective",
              "—" if result.objective_value is None
              else f"{result.objective_value:.0f}")
    c4.metric("Feasible", "✅" if result.feasible else "❌")

    if not result.feasible:
        st.error(result.infeasibility_reason or "No feasible plan found.")
    else:
        metrics = compute_metrics(result, user)
        st.subheader("Key metrics")
        st.json(metrics.as_dict(), expanded=False)

        report = validate_plan(result.plan, user)
        if not report.ok:
            st.warning("Hard-constraint validator flagged issues:")
            for v in report.violations:
                st.write(f"- {v}")

        st.subheader("Weekly schedule")
        fig, _ = render_schedule_to_figure(result.plan)
        st.pyplot(fig)

        st.subheader("Daily breakdown")
        rows = []
        for dp in result.plan.daily_plans:
            rows.append({
                "day": dp.day,
                "kcal": dp.calories_total,
                "protein (g)": dp.protein_total_g,
                "carbs (g)": dp.carbs_total_g,
                "fat (g)": dp.fat_total_g,
                "cost (c)": dp.cost_cents,
                "workouts": len(dp.workouts),
                "meals": len(dp.meals),
            })
        st.dataframe(rows, use_container_width=True)
else:
    st.info(
        "Configure the instance on the left and click **Solve**. "
        "Try the same scenario with different solvers to compare formulations."
    )
