"""Sanity checks on the settings module and domain validators."""
from __future__ import annotations

import pytest

from src.config.settings import (
    DAYS_PER_WEEK,
    SLOTS_PER_DAY,
    slot_to_time,
    time_to_slot,
)
from src.models.domain import FoodItem, TimeWindow, UserProfile
from src.models.enums import DietaryTag, MealType


def test_time_grid_identities():
    assert SLOTS_PER_DAY == 48
    assert DAYS_PER_WEEK == 7
    assert slot_to_time(0) == "00:00"
    assert slot_to_time(14) == "07:00"
    assert time_to_slot(7) == 14
    assert time_to_slot(7, 30) == 15


def test_timewindow_rejects_bad_order():
    with pytest.raises(ValueError):
        TimeWindow(day=0, start_slot=20, end_slot=10)


def test_fooditem_default_meal_types_when_missing():
    f = FoodItem(
        id="x", name="generic", calories=100, protein_g=10,
        carbs_g=10, fat_g=4, cost_cents=100,
    )
    assert set(f.meal_types) == {
        MealType.BREAKFAST, MealType.LUNCH, MealType.DINNER, MealType.SNACK,
    }


def test_dietary_exclusions_filter():
    f = FoodItem(
        id="x", name="beef bowl", calories=500, protein_g=35,
        carbs_g=40, fat_g=20, cost_cents=600,
        dietary_tags=[DietaryTag.CONTAINS_BEEF],
    )
    assert f.allowed_for([DietaryTag.VEGETARIAN]) is True
    assert f.allowed_for([DietaryTag.CONTAINS_BEEF]) is False


def test_availability_mask_shape(balanced_user: UserProfile):
    mask = balanced_user.availability_mask()
    assert len(mask) == DAYS_PER_WEEK
    assert all(len(row) == SLOTS_PER_DAY for row in mask)
    # At least one slot is available.
    assert any(any(row) for row in mask)
