"""Shared solver interface.

Every solver in this project accepts exactly the same three inputs --
a :class:`UserProfile`, a list of :class:`FoodItem`, and a list of
:class:`WorkoutTemplate` -- and returns a :class:`SolverResult`. Sticking
to this contract is what lets the experiment runner pass the same instance
to all formulations and produce an apples-to-apples comparison.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

from src.config.settings import DEFAULT_WEIGHTS, ScoringWeights
from src.models.domain import (
    FoodItem,
    SolverResult,
    UserProfile,
    WorkoutTemplate,
)


class BaseSolver(ABC):
    """Common base class for all three formulations."""

    name: str = "base"

    def __init__(
        self,
        *,
        weights: ScoringWeights | None = None,
        time_limit_s: int | None = None,
        log_search: bool = False,
    ) -> None:
        self.weights: ScoringWeights = weights or DEFAULT_WEIGHTS
        self.time_limit_s: int | None = time_limit_s
        self.log_search: bool = log_search

    # ------------------------------------------------------------------
    @abstractmethod
    def solve(
        self,
        user: UserProfile,
        foods: Iterable[FoodItem],
        workouts: Iterable[WorkoutTemplate],
    ) -> SolverResult:
        """Produce a :class:`SolverResult` for the given instance."""
        raise NotImplementedError
