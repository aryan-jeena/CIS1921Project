"""Global configuration: paths, seeds, and scoring weights."""

from .settings import (
    ROOT,
    DATA_DIR,
    SAMPLE_DIR,
    PROCESSED_DIR,
    RAW_DIR,
    PRESETS_DIR,
    REPORTS_DIR,
    FIGURES_DIR,
    TABLES_DIR,
    DEFAULT_SEED,
    SLOTS_PER_DAY,
    MINUTES_PER_SLOT,
    DAYS_PER_WEEK,
    DEFAULT_WEIGHTS,
    ScoringWeights,
)

__all__ = [
    "ROOT",
    "DATA_DIR",
    "SAMPLE_DIR",
    "PROCESSED_DIR",
    "RAW_DIR",
    "PRESETS_DIR",
    "REPORTS_DIR",
    "FIGURES_DIR",
    "TABLES_DIR",
    "DEFAULT_SEED",
    "SLOTS_PER_DAY",
    "MINUTES_PER_SLOT",
    "DAYS_PER_WEEK",
    "DEFAULT_WEIGHTS",
    "ScoringWeights",
]
