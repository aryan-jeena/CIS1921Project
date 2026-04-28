"""USDA FoodData Central loader.

FDC distributes CSVs from https://fdc.nal.usda.gov/download-datasets . The
most useful table for our purposes is ``food.csv`` joined with
``food_nutrient.csv`` on ``fdc_id``, but the full dataset is several hundred
MB and we do not want it in the repo.

This loader therefore expects the user to drop a pre-joined *summary* CSV
into ``data/raw/usda_summary.csv`` with columns::

    fdc_id, description, calories, protein_g, carbs_g, fat_g, sodium_mg

If the file is missing, we return an empty list so the rest of the pipeline
falls back to the sample + Penn Dining catalog. Nothing ever crashes.
"""
from __future__ import annotations

import csv
from pathlib import Path

from src.config.settings import RAW_DIR
from src.models.domain import FoodItem
from src.models.enums import MealType


def load_usda_csv(path: Path | str | None = None, *, max_rows: int = 500) -> list[FoodItem]:
    """Load a USDA *summary* CSV. Returns ``[]`` if the file is missing.

    ``max_rows`` guards against accidentally feeding the full 300k-row FDC
    dump through the solver.
    """
    p = Path(path) if path else RAW_DIR / "usda_summary.csv"
    if not p.exists():
        return []
    out: list[FoodItem] = []
    with p.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if i >= max_rows:
                break
            try:
                fid = row.get("fdc_id", f"usda_{i}")
                out.append(
                    FoodItem(
                        id=f"usda_{fid}",
                        name=row.get("description", f"USDA {fid}")[:80],
                        calories=int(float(row["calories"])),
                        protein_g=int(float(row["protein_g"])),
                        carbs_g=int(float(row["carbs_g"])),
                        fat_g=int(float(row["fat_g"])),
                        sodium_mg=int(float(row.get("sodium_mg", 0) or 0)),
                        cost_cents=int(float(row.get("cost_cents", 200) or 200)),
                        meal_types=[
                            MealType.BREAKFAST,
                            MealType.LUNCH,
                            MealType.DINNER,
                            MealType.SNACK,
                        ],
                        source="usda",
                        convenience=5,
                        max_servings_per_day=2,
                    )
                )
            except (KeyError, ValueError):
                # Skip malformed rows rather than failing the whole load.
                continue
    return out
