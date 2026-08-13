"""Discrimination and calibration metrics.

Calibration is not an afterthought here. For an early-warning system a
well-calibrated 0.70 AUC beats an overconfident 0.85, because a human acts on the
probability. ECE and the reliability table are therefore first-class outputs, not
diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score


def auc(y_true: np.ndarray, p: np.ndarray) -> float:
    y_true = np.asarray(y_true)
    if len(np.unique(y_true)) < 2:
        return float("nan")
    return float(roc_auc_score(y_true, p))


def brier(y_true: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((np.asarray(p, dtype=float) - np.asarray(y_true, dtype=float)) ** 2))


def reliability_table(y_true: np.ndarray, p: np.ndarray, n_bins: int = 10) -> pd.DataFrame:
    """Predicted vs. observed frequency per bin. The raw material for ECE."""
    p = np.asarray(p, dtype=float)
    y = np.asarray(y_true, dtype=float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1], right=False), 0, n_bins - 1)
    rows = []
    for b in range(n_bins):
        m = idx == b
        if not m.any():
            continue
        rows.append(
            {
                "bin": b,
                "lower": float(edges[b]),
                "upper": float(edges[b + 1]),
                "n": int(m.sum()),
                "mean_predicted": float(p[m].mean()),
                "observed_rate": float(y[m].mean()),
                "gap": float(p[m].mean() - y[m].mean()),
            }
        )
    return pd.DataFrame(rows)


def expected_calibration_error(y_true: np.ndarray, p: np.ndarray, n_bins: int = 10) -> float:
    tab = reliability_table(y_true, p, n_bins)
    if tab.empty:
        return float("nan")
    w = tab["n"] / tab["n"].sum()
    return float((w * tab["gap"].abs()).sum())


@dataclass
class MetricSet:
    name: str
    n: int
    positives: int
    auc: float
    brier: float
    ece: float
    mean_predicted: float
    observed_rate: float

    def as_dict(self) -> dict:
        return asdict(self)


def evaluate(name: str, y_true: np.ndarray, p: np.ndarray, n_bins: int = 10) -> MetricSet:
    y = np.asarray(y_true, dtype=int)
    p = np.asarray(p, dtype=float)
    return MetricSet(
        name=name,
        n=len(y),
        positives=int(y.sum()),
        auc=auc(y, p),
        brier=brier(y, p),
        ece=expected_calibration_error(y, p, n_bins),
        mean_predicted=float(p.mean()) if len(p) else float("nan"),
        observed_rate=float(y.mean()) if len(y) else float("nan"),
    )


def compare(results: list[MetricSet]) -> pd.DataFrame:
    """Results table, ordered by discrimination but showing calibration beside it."""
    df = pd.DataFrame([r.as_dict() for r in results])
    return df.sort_values("auc", ascending=False).reset_index(drop=True)
