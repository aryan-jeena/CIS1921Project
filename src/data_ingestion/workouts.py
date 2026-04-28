"""Workout library loader."""
from __future__ import annotations

import json
from pathlib import Path

from src.config.settings import SAMPLE_DIR
from src.models.domain import WorkoutTemplate


def load_workouts_from_json(path: Path | str) -> list[WorkoutTemplate]:
    """Load a list of :class:`WorkoutTemplate` from JSON. Returns ``[]`` if
    the file is missing."""
    p = Path(path)
    if not p.exists():
        return []
    with p.open("r", encoding="utf-8") as f:
        rows = json.load(f)
    return [WorkoutTemplate(**row) for row in rows]


def load_sample_workouts() -> list[WorkoutTemplate]:
    """Bundled workout library."""
    return load_workouts_from_json(SAMPLE_DIR / "workouts_sample.json")
