"""JSON-file loader for user presets.

Separates "what's on disk" (configs/presets/*.json) from "what the solver
eats" (UserProfile). The UI and CLI both go through these helpers so we only
have one JSON schema to maintain.
"""
from __future__ import annotations

from pathlib import Path

from src.config.settings import PRESETS_DIR
from src.models.domain import UserProfile
from src.utils.io import load_json


def list_presets(dir_: Path | None = None) -> list[str]:
    """Return the base names of JSON presets in ``configs/presets/``."""
    d = Path(dir_) if dir_ else PRESETS_DIR
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


def load_preset(name: str, dir_: Path | None = None) -> UserProfile:
    """Load a single preset by name ("budget_student", etc.)."""
    d = Path(dir_) if dir_ else PRESETS_DIR
    path = d / f"{name}.json"
    raw = load_json(path)
    return UserProfile.model_validate(raw)
