"""The twin state: persistence, transition, recursive update.

This package is the twin. Everything else either feeds it (adapters, features) or
reads from it (readout, simulation, explanation).

Inference status, stated plainly per Gate 1:

  reference (exact)     : full-posterior MCMC over parameters and states.
                          NOT IMPLEMENTED. `TwinFilter` exposes the interface it
                          would satisfy so adding it does not change callers.
  production (approx.)  : Laplace-approximate Gaussian filter  -  a Newton solve
                          for the mode of the one-step posterior, with the
                          negative inverse Hessian as covariance. IMPLEMENTED.
  prototype simplification : parameters are fitted in two stages rather than
                          jointly, and the score channel uses a Gaussian on the
                          logit scale rather than a Beta likelihood. Both are
                          recorded in docs/assumptions.md (A-03, A-04).
"""

from .model import (
    InferenceMethod,
    TwinParameters,
    TwinState,
    StateTrajectory,
    StepAttribution,
)
from .filter import TwinFilter
from .fit import fit_twin

__all__ = [
    "InferenceMethod",
    "TwinParameters",
    "TwinState",
    "StateTrajectory",
    "StepAttribution",
    "TwinFilter",
    "fit_twin",
]
