"""Tiny JSON / path helpers shared between the CLI, presets, and experiments."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def ensure_dir(path: Path) -> Path:
    """Ensure ``path`` exists (creating parent dirs) and return it."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_json(path: Path | str) -> Any:
    """Load JSON from disk. Accepts str or Path; raises FileNotFoundError
    with a helpful message."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"JSON file not found: {p}")
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(obj: Any, path: Path | str, *, indent: int = 2) -> Path:
    """Serialize ``obj`` to JSON at ``path``.

    Pydantic models are handled via ``model_dump`` so we never accidentally
    pickle them.
    """
    p = Path(path)
    ensure_dir(p.parent)
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump(mode="json")
    with p.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=indent, default=str)
    return p
