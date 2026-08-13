"""Prediction. Deliberately downstream of, and separable from, the twin state.

`readout` consumes filtered states and nothing else. `baselines` never touches
the state at all. Keeping them apart is what lets E1 compare them honestly  -  and
what makes "prediction is a byproduct of state" checkable rather than asserted.
"""

from .readout import HazardReadout, build_person_period
from .baselines import (
    BaselineResult,
    fit_majority_baseline,
    fit_prior_assessment_baseline,
    fit_rolling_feature_baseline,
    fit_gbm_baseline,
    run_baseline_ladder,
)

__all__ = [
    "HazardReadout",
    "build_person_period",
    "BaselineResult",
    "fit_majority_baseline",
    "fit_prior_assessment_baseline",
    "fit_rolling_feature_baseline",
    "fit_gbm_baseline",
    "run_baseline_ladder",
]
