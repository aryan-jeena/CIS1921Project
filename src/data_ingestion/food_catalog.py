"""Food-catalog loaders.

The three entry points are intentionally flat so the experiment scripts and
Streamlit UI can compose them freely:

- :func:`load_sample_foods`       bundled curated CSV
- :func:`load_penn_dining_sample` bundled curated Penn Dining JSON
- :func:`load_foods_from_csv`     generic loader for any compatible CSV

:func:`build_food_catalog` composes sources, deduplicates on ``id``, and
applies dietary-exclusion filtering.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Iterable, Optional

from src.config.settings import SAMPLE_DIR
from src.models.domain import FoodItem
from src.models.enums import DietaryTag, MealType


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------
def _parse_tag_list(cell: str, enum_cls):
    """Parse a ';'-separated enum list from a CSV cell.

    Unknown tags are skipped silently; we log-and-continue rather than raise,
    because a CSV produced from scraped data is expected to occasionally drop
    a row that we don't understand.
    """
    if not cell:
        return []
    out = []
    for tok in cell.replace(",", ";").split(";"):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(enum_cls(tok))
        except ValueError:
            continue
    return out


def _food_from_csv_row(row: dict) -> FoodItem:
    """Build a :class:`FoodItem` from one row of the sample CSV."""
    return FoodItem(
        id=row["id"],
        name=row["name"],
        calories=int(float(row["calories"])),
        protein_g=int(float(row["protein_g"])),
        carbs_g=int(float(row["carbs_g"])),
        fat_g=int(float(row["fat_g"])),
        sodium_mg=int(float(row.get("sodium_mg", 0) or 0)),
        cost_cents=int(float(row["cost_cents"])),
        meal_types=_parse_tag_list(row.get("meal_types", ""), MealType),
        dietary_tags=_parse_tag_list(row.get("dietary_tags", ""), DietaryTag),
        convenience=int(float(row.get("convenience", 5) or 5)),
        max_servings_per_day=int(float(row.get("max_servings_per_day", 3) or 3)),
        source="sample",
    )


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------
def load_foods_from_csv(path: Path | str) -> list[FoodItem]:
    """Load a list of :class:`FoodItem` from a CSV with the sample-file
    column layout. Never raises on empty files -- returns ``[]``."""
    p = Path(path)
    if not p.exists():
        return []
    with p.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [_food_from_csv_row(row) for row in reader]


def load_sample_foods() -> list[FoodItem]:
    """Bundled curated food catalog."""
    return load_foods_from_csv(SAMPLE_DIR / "foods_sample.csv")


def load_penn_dining_sample() -> list[FoodItem]:
    """Bundled Penn Dining sample.

    Because dining-hall meals are already paid for via the meal plan, we keep
    their ``cost_cents`` at whatever the JSON declares. The curated sample
    file sets ``0`` for true dining-hall swipe-only items and a real cost
    for retail spots (Houston Market, Joe's, Accenture).
    """
    p = SAMPLE_DIR / "penn_dining_sample.json"
    if not p.exists():
        return []
    with p.open("r", encoding="utf-8") as f:
        rows = json.load(f)
    out: list[FoodItem] = []
    for row in rows:
        out.append(
            FoodItem(
                id=row["id"],
                name=row["name"],
                calories=int(row["calories"]),
                protein_g=int(row["protein_g"]),
                carbs_g=int(row["carbs_g"]),
                fat_g=int(row["fat_g"]),
                sodium_mg=int(row.get("sodium_mg", 0)),
                cost_cents=int(row.get("cost_cents", 0)),
                meal_types=[MealType(m) for m in row.get("meal_types", [])],
                dietary_tags=[DietaryTag(t) for t in row.get("dietary_tags", [])],
                convenience=int(row.get("convenience", 7)),
                max_servings_per_day=int(row.get("max_servings_per_day", 2)),
                source="penn_dining",
            )
        )
    return out


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------
def build_food_catalog(
    sources: Iterable[list[FoodItem]] | None = None,
    *,
    exclusions: Optional[list[DietaryTag]] = None,
    include_penn: bool = True,
    include_sample: bool = True,
) -> list[FoodItem]:
    """Compose food sources and apply dietary exclusions.

    Parameters
    ----------
    sources : iterable of FoodItem lists, optional
        Extra lists (e.g. a USDA loader's output). Appended after the bundled
        defaults.
    exclusions : list[DietaryTag], optional
        Remove items carrying any of these tags.
    include_penn, include_sample : bool
        Toggle the bundled sources.
    """
    catalog: list[FoodItem] = []
    if include_sample:
        catalog.extend(load_sample_foods())
    if include_penn:
        catalog.extend(load_penn_dining_sample())
    if sources is not None:
        for s in sources:
            catalog.extend(s)

    # dedupe by id, first win
    seen: set[str] = set()
    unique: list[FoodItem] = []
    for f in catalog:
        if f.id in seen:
            continue
        seen.add(f.id)
        unique.append(f)

    if exclusions:
        unique = [f for f in unique if f.allowed_for(exclusions)]
    return unique
