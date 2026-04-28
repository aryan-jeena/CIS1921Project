"""Tests on the time-grid helpers and the two-stage scheduler."""
from __future__ import annotations

from src.config.settings import DAYS_PER_WEEK
from src.data_ingestion.food_catalog import build_food_catalog
from src.evaluation.validator import validate_plan
from src.experiments.instance_generator import InstanceParams, generate_user
from src.models.domain import TimeWindow
from src.models.enums import ActivityKind
from src.scheduling.time_grid import (
    build_availability_mask,
    iter_runs,
    split_week_slot,
    week_slot,
)
from src.solvers.two_stage import TwoStageSolver


def test_week_slot_roundtrip():
    for d in (0, 3, 6):
        for s in (0, 15, 47):
            assert split_week_slot(week_slot(d, s)) == (d, s)


def test_iter_runs_yields_contiguous_ranges():
    row = [False, True, True, False, False, True]
    runs = list(iter_runs(row))
    assert runs == [(1, 3), (5, 6)]


def test_availability_mask_from_windows():
    w = [TimeWindow(day=0, start_slot=10, end_slot=12),
         TimeWindow(day=3, start_slot=30, end_slot=34)]
    mask = build_availability_mask(w)
    assert mask[0][10] and mask[0][11]
    assert not mask[0][12]
    assert mask[3][30] and mask[3][33]
    assert not mask[3][34]


def test_two_stage_produces_non_overlapping_schedule(sample_workouts):
    user = generate_user("balanced", InstanceParams(seed=11))
    foods = build_food_catalog()
    res = TwoStageSolver(time_limit_s=20).solve(user, foods, sample_workouts)
    assert res.feasible, f"status={res.status}, reason={res.infeasibility_reason}"

    # No overlap (validator already checks this; assert it ran cleanly too)
    report = validate_plan(res.plan, user)
    assert report.ok, f"Hard violations: {report.violations}"

    # At least one workout scheduled within configured bounds
    n_workouts = sum(1 for b in res.plan.schedule_blocks if b.kind == ActivityKind.WORKOUT)
    assert user.workout_count_min <= n_workouts <= user.workout_count_max


def test_two_stage_produces_sleep_block_every_day(sample_workouts):
    user = generate_user("balanced", InstanceParams(seed=12))
    foods = build_food_catalog()
    res = TwoStageSolver(time_limit_s=20).solve(user, foods, sample_workouts)
    assert res.feasible
    sleep_days = {
        b.day for b in res.plan.schedule_blocks if b.kind == ActivityKind.SLEEP
    }
    assert sleep_days == set(range(DAYS_PER_WEEK))
