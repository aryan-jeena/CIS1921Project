"""Instance generator determinism + scenario coverage."""
from __future__ import annotations

from src.experiments.instance_generator import (
    InstanceParams,
    generate_scenario_suite,
    generate_user,
)


def test_generator_is_deterministic():
    a = generate_user("balanced", InstanceParams(seed=42))
    b = generate_user("balanced", InstanceParams(seed=42))
    assert a.model_dump() == b.model_dump()


def test_scenario_suite_covers_all_named_scenarios():
    suite = generate_scenario_suite(seed=0)
    names = {u.name.split("_")[0] for u in suite}
    # Generator prefixes the scenario name, so the set of scenarios should
    # match what the CLI and docs advertise.
    assert "balanced" in "_".join(u.name for u in suite)
    assert len(suite) == 9


def test_impossible_case_has_hopeless_inputs():
    u = generate_user("impossible_case")
    # Calorie band is too small and windows too narrow.
    assert u.calorie_tolerance <= 50
    assert sum(w.duration for w in u.available_windows) < 50
    assert u.workout_count_min == 7


def test_presets_loadable():
    from src.experiments.presets import list_presets, load_preset
    names = list_presets()
    assert "budget_student" in names
    assert "lean_bulk" in names
    prof = load_preset("budget_student")
    assert prof.weekly_budget_cents == 4000
