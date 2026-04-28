"""Shared pytest fixtures.

These fixtures give every test a reproducible catalog + workout library +
``balanced`` user without re-loading from disk every time.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


# Make ``src`` importable when the tests are run without ``pip install -e``.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session")
def sample_foods():
    from src.data_ingestion.food_catalog import load_sample_foods
    return load_sample_foods()


@pytest.fixture(scope="session")
def sample_penn():
    from src.data_ingestion.food_catalog import load_penn_dining_sample
    return load_penn_dining_sample()


@pytest.fixture(scope="session")
def sample_workouts():
    from src.data_ingestion.workouts import load_sample_workouts
    return load_sample_workouts()


@pytest.fixture
def balanced_user():
    from src.experiments.instance_generator import (
        InstanceParams,
        generate_user,
    )
    return generate_user("balanced", InstanceParams(seed=17))
