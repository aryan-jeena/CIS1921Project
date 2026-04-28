"""Loaders + catalog composition."""
from __future__ import annotations

from src.data_ingestion.food_catalog import (
    build_food_catalog,
    load_penn_dining_sample,
    load_sample_foods,
)
from src.data_ingestion.penn_dining import PennDiningParser
from src.models.enums import DietaryTag


def test_sample_catalog_nonempty(sample_foods):
    assert len(sample_foods) >= 20
    assert all(f.calories > 0 for f in sample_foods)


def test_penn_sample_loads(sample_penn):
    assert len(sample_penn) >= 3
    assert all(f.source == "penn_dining" for f in sample_penn)


def test_penn_parser_falls_back_when_offline():
    parser = PennDiningParser(urls=("http://127.0.0.1:59999/nope",), timeout_s=1)
    items = parser.load()
    # Always returns *something* (at least the bundled sample).
    assert items, "PennDiningParser.load() must never return an empty list"


def test_build_catalog_respects_exclusions():
    full = build_food_catalog()
    vegan = build_food_catalog(exclusions=[
        DietaryTag.CONTAINS_BEEF, DietaryTag.CONTAINS_PORK,
        DietaryTag.CONTAINS_SHELLFISH, DietaryTag.CONTAINS_DAIRY,
    ])
    assert len(vegan) < len(full)
    excluded = {
        DietaryTag.CONTAINS_BEEF, DietaryTag.CONTAINS_PORK,
        DietaryTag.CONTAINS_SHELLFISH, DietaryTag.CONTAINS_DAIRY,
    }
    for f in vegan:
        assert not set(f.dietary_tags).intersection(excluded)


def test_catalog_ids_unique():
    cat = build_food_catalog()
    ids = [f.id for f in cat]
    assert len(ids) == len(set(ids))


def test_sample_catalog_has_macros_assumed_by_solvers(sample_foods):
    # Solvers treat calories/protein/carbs/fat as ints -- confirm loader too.
    for f in sample_foods:
        assert isinstance(f.calories, int)
        assert isinstance(f.protein_g, int)
        assert isinstance(f.carbs_g, int)
        assert isinstance(f.fat_g, int)
