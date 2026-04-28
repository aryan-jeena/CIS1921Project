"""Solver package.

Three independent formulations are exposed; they share the same
:class:`BaseSolver` interface so the experiment runner can treat them
interchangeably.
"""

from .base import BaseSolver
from .nutrition_only import NutritionOnlySolver
from .two_stage import TwoStageSolver
from .joint_cpsat import JointCPSATSolver

ALL_SOLVERS: dict[str, type[BaseSolver]] = {
    "nutrition_only": NutritionOnlySolver,
    "two_stage": TwoStageSolver,
    "joint_cpsat": JointCPSATSolver,
}

__all__ = [
    "BaseSolver",
    "NutritionOnlySolver",
    "TwoStageSolver",
    "JointCPSATSolver",
    "ALL_SOLVERS",
]
