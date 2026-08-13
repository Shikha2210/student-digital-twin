"""Generative forward simulation and the intervention interface.

Everything produced here is model-generated. Nothing in this package is an
estimate of what would happen to a real student, and the return types carry that
statement so a caller cannot lose it on the way to a chart.
"""

from .intervention import (
    INTERVENTION_NAMES,
    Intervention,
    InterventionScenario,
    default_C,
)
from .forward import SimulationResult, simulate_forward

__all__ = [
    "INTERVENTION_NAMES",
    "Intervention",
    "InterventionScenario",
    "default_C",
    "SimulationResult",
    "simulate_forward",
]
