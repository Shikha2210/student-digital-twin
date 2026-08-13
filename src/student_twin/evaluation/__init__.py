"""Evaluation: metrics, splits, and negative controls.

Discrimination and calibration are always reported together. Gate 1 H1 predicts
parity on the first and an advantage on the second, so quoting only AUC would
hide the result the project is actually about.
"""

from .metrics import (
    MetricSet,
    auc,
    brier,
    expected_calibration_error,
    reliability_table,
    evaluate,
    compare,
)
from .splits import forward_chained_split, random_split_LEAKY
from .negative_controls import (
    NegativeControlResult,
    permute_time,
    permute_student_identity,
    permute_context_labels,
    run_negative_controls,
    leakage_verdict,
)

__all__ = [
    "MetricSet",
    "auc",
    "brier",
    "expected_calibration_error",
    "reliability_table",
    "evaluate",
    "compare",
    "forward_chained_split",
    "random_split_LEAKY",
    "NegativeControlResult",
    "permute_time",
    "permute_student_identity",
    "permute_context_labels",
    "run_negative_controls",
    "leakage_verdict",
]
