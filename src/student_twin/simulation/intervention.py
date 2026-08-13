"""The intervention vector  -  structurally separate from observed data.

READ THIS BEFORE USING ANYTHING HERE
------------------------------------
OULAD contains no recorded interventions. The matrix `C` mapping an intervention
to a change in state is therefore **not estimated from data and cannot be**. It is
a declared modelling sensitivity: a statement of the form "if a support programme
shifted weekly engagement by one within-cohort standard deviation, the model's
dynamics imply the following trajectory".

That is a conditional statement about the model, not a causal claim about
students. Every consumer of this module must present results as

    "Under the model's assumed transition dynamics, ..."

and never as

    "Doing X will improve this student's outcome."

The separation is enforced by types, not by discipline: interventions enter the
transition through `d_t`, a channel no observation can ever write to.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

#: Abstract simulation controls. Deliberately not named after real programmes  - 
#: naming one "tutoring" would invite reading the output as a tutoring effect.
INTERVENTION_NAMES: tuple[str, ...] = (
    "engagement_support",   # shifts the engagement dimension
    "workload_change",      # shifts both, negatively when load increases
    "academic_support",     # shifts the capability dimension
)

#: Default sensitivities, in state units (roughly within-cohort SDs) per unit of
#: intervention intensity. ASSUMED, not fitted. See docs/assumptions.md A-08.
DEFAULT_SENSITIVITY: dict[str, tuple[float, float]] = {
    "engagement_support": (0.40, 0.05),
    "workload_change": (-0.25, -0.15),
    "academic_support": (0.10, 0.35),
}


def default_C(n_dims: int) -> np.ndarray:
    """Build the (d, n_interventions) sensitivity matrix from declared defaults."""
    C = np.zeros((n_dims, len(INTERVENTION_NAMES)))
    for j, name in enumerate(INTERVENTION_NAMES):
        eng, cap = DEFAULT_SENSITIVITY[name]
        vals = (eng, cap)[:n_dims]
        for i, v in enumerate(vals):
            C[i, j] = v
    return C


@dataclass(frozen=True)
class Intervention:
    """One hypothetical control applied over a window of weeks."""

    name: str
    intensity: float = 1.0
    start_week: int = 0
    end_week: int | None = None      # None = to the end of the horizon

    def __post_init__(self) -> None:
        if self.name not in INTERVENTION_NAMES:
            raise ValueError(
                f"unknown intervention {self.name!r}; available: {list(INTERVENTION_NAMES)}"
            )
        if self.end_week is not None and self.end_week < self.start_week:
            raise ValueError("end_week precedes start_week")

    def active_at(self, week_offset: int) -> bool:
        if week_offset < self.start_week:
            return False
        return self.end_week is None or week_offset <= self.end_week


@dataclass(frozen=True)
class InterventionScenario:
    """A named bundle of interventions to simulate.

    `is_counterfactual` is always True. It exists so that any frame or plot
    derived from a scenario can be labelled automatically rather than relying on
    whoever wrote the chart to remember.
    """

    label: str
    interventions: tuple[Intervention, ...] = field(default_factory=tuple)
    is_counterfactual: bool = True

    @classmethod
    def baseline(cls) -> "InterventionScenario":
        """No intervention  -  the model's own forecast under observed dynamics."""
        return cls(label="baseline (no intervention)", interventions=(), is_counterfactual=False)

    def vector_at(self, week_offset: int) -> np.ndarray:
        v = np.zeros(len(INTERVENTION_NAMES))
        for iv in self.interventions:
            if iv.active_at(week_offset):
                v[INTERVENTION_NAMES.index(iv.name)] += iv.intensity
        return v

    def describe(self) -> str:
        if not self.interventions:
            return "No intervention applied; model dynamics only."
        parts = [
            f"{iv.name} at intensity {iv.intensity:+.2f} from week +{iv.start_week}"
            + (f" to +{iv.end_week}" if iv.end_week is not None else " onward")
            for iv in self.interventions
        ]
        return "Under the model's assumed transition dynamics: " + "; ".join(parts) + "."
