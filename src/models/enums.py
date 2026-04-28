"""Enumerations used in the domain model.

Using string-valued enums keeps JSON config files human-readable while still
giving us strong typing inside the solver code.
"""
from __future__ import annotations

from enum import Enum


class Goal(str, Enum):
    """High-level training goal for the week."""

    CUT = "cut"                       # fat loss, calorie deficit
    LEAN_BULK = "lean_bulk"           # slow muscle gain, slight surplus
    MAINTENANCE = "maintenance"
    PERFORMANCE = "performance"       # athletic-focused
    GENERAL_HEALTH = "general_health"


class PreferredSplit(str, Enum):
    """Training split preference. Used as a soft-objective signal."""

    FULL_BODY = "full_body"
    UPPER_LOWER = "upper_lower"
    PUSH_PULL_LEGS = "push_pull_legs"
    BRO_SPLIT = "bro_split"
    CARDIO_FOCUS = "cardio_focus"


class WorkoutType(str, Enum):
    """Tag used for recovery spacing and preferred-split scoring."""

    FULL_BODY = "full_body"
    UPPER = "upper"
    LOWER = "lower"
    PUSH = "push"
    PULL = "pull"
    LEGS = "legs"
    CARDIO = "cardio"
    MOBILITY = "mobility"
    REST = "rest"


class Intensity(str, Enum):
    """Perceived-exertion tag.

    Only ``HARD`` and ``VERY_HARD`` sessions count toward recovery-spacing
    constraints.
    """

    EASY = "easy"
    MODERATE = "moderate"
    HARD = "hard"
    VERY_HARD = "very_hard"


class MealType(str, Enum):
    BREAKFAST = "breakfast"
    LUNCH = "lunch"
    DINNER = "dinner"
    SNACK = "snack"
    PRE_WORKOUT = "pre_workout"
    POST_WORKOUT = "post_workout"


class DietaryTag(str, Enum):
    """Tag attached to food items so exclusions are just set-intersection."""

    VEGETARIAN = "vegetarian"
    VEGAN = "vegan"
    HALAL = "halal"
    KOSHER = "kosher"
    GLUTEN_FREE = "gluten_free"
    DAIRY_FREE = "dairy_free"
    NUT_FREE = "nut_free"
    CONTAINS_PORK = "contains_pork"
    CONTAINS_BEEF = "contains_beef"
    CONTAINS_SHELLFISH = "contains_shellfish"
    CONTAINS_DAIRY = "contains_dairy"
    CONTAINS_GLUTEN = "contains_gluten"
    CONTAINS_NUTS = "contains_nuts"


class ActivityKind(str, Enum):
    """What kind of activity occupies a scheduled block."""

    WORKOUT = "workout"
    MEAL = "meal"
    SLEEP = "sleep"
    HYDRATION = "hydration"
    RECOVERY = "recovery"
    IDLE = "idle"
