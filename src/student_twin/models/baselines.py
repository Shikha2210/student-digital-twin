"""The baseline ladder.

Gate 1 P0: every results table reports all of these, always. A twin quoted
without them is unevaluable, and the prior-assessment baseline in particular is
the one that sinks most student-prediction projects  -  it is very hard to beat and
almost never reported.

Every baseline predicts the same target as the readout  -  a weekly hazard on the
same person-period rows  -  so the comparison is like for like.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression


@dataclass
class BaselineResult:
    name: str
    description: str
    predictions: np.ndarray
    y_true: np.ndarray
    feature_names: tuple[str, ...] = ()
    notes: dict[str, str] = field(default_factory=dict)


def _fit_logistic(
    train: pd.DataFrame, test: pd.DataFrame, feats: list[str]
) -> tuple[np.ndarray, np.ndarray]:
    Xtr = train[feats].fillna(0.0).to_numpy(dtype=float)
    ytr = train["y"].to_numpy(dtype=int)
    Xte = test[feats].fillna(0.0).to_numpy(dtype=float)
    if len(np.unique(ytr)) < 2:
        p = float(np.clip(ytr.mean(), 1e-6, 1 - 1e-6))
        return np.full(len(Xte), p), test["y"].to_numpy(dtype=int)
    lr = LogisticRegression(max_iter=1000).fit(Xtr, ytr)
    return lr.predict_proba(Xte)[:, 1], test["y"].to_numpy(dtype=int)


def fit_majority_baseline(train: pd.DataFrame, test: pd.DataFrame) -> BaselineResult:
    """The floor. Predicts the training base rate for everyone, always."""
    rate = float(np.clip(train["y"].mean(), 1e-6, 1 - 1e-6))
    return BaselineResult(
        name="majority",
        description="Constant prediction at the training-set weekly hazard base rate.",
        predictions=np.full(len(test), rate),
        y_true=test["y"].to_numpy(dtype=int),
        notes={"base_rate": f"{rate:.5f}"},
    )


def fit_prior_assessment_baseline(
    train: pd.DataFrame, test: pd.DataFrame, feature_frame: pd.DataFrame
) -> BaselineResult:
    """Prior assessment behaviour only. The baseline that most often wins."""
    feats = [c for c in ("submission_rate", "score_vs_own_baseline") if c in feature_frame.columns]
    tr = train.merge(feature_frame[["student_id", "t", *feats]], on=["student_id", "t"], how="left")
    te = test.merge(feature_frame[["student_id", "t", *feats]], on=["student_id", "t"], how="left")
    if not feats:
        return fit_majority_baseline(train, test)
    preds, y = _fit_logistic(tr, te, feats)
    return BaselineResult(
        name="prior_assessment",
        description="Logistic hazard on submission rate and score relative to own baseline.",
        predictions=preds,
        y_true=y,
        feature_names=tuple(feats),
    )


def fit_rolling_feature_baseline(
    train: pd.DataFrame, test: pd.DataFrame, feature_frame: pd.DataFrame
) -> BaselineResult:
    """All tier-1 features, no latent state. The direct rival to the twin.

    If this matches the twin everywhere, the state is adding machinery and not
    information  -  precisely the Gate 1 weakness-1 scenario, and this baseline is
    how we would find out.
    """
    feats = [c for c in feature_frame.columns if c not in ("student_id", "context_id", "t")]
    tr = train.merge(feature_frame, on=["student_id", "context_id", "t"], how="left")
    te = test.merge(feature_frame, on=["student_id", "context_id", "t"], how="left")
    preds, y = _fit_logistic(tr, te, feats)
    return BaselineResult(
        name="rolling_features",
        description="Logistic hazard on the full tier-1 feature set, no latent state.",
        predictions=preds,
        y_true=y,
        feature_names=tuple(feats),
    )


def fit_gbm_baseline(
    train: pd.DataFrame, test: pd.DataFrame, feature_frame: pd.DataFrame, *, seed: int = 0
) -> BaselineResult:
    """Gradient boosting on tier-1 features. Expected to lead on discrimination."""
    feats = [c for c in feature_frame.columns if c not in ("student_id", "context_id", "t")]
    tr = train.merge(feature_frame, on=["student_id", "context_id", "t"], how="left")
    te = test.merge(feature_frame, on=["student_id", "context_id", "t"], how="left")
    Xtr, ytr = tr[feats].fillna(0.0).to_numpy(float), tr["y"].to_numpy(int)
    Xte = te[feats].fillna(0.0).to_numpy(float)
    if len(np.unique(ytr)) < 2:
        return fit_majority_baseline(train, test)
    gbm = HistGradientBoostingClassifier(
        max_iter=200, learning_rate=0.06, max_depth=4, random_state=seed
    ).fit(Xtr, ytr)
    return BaselineResult(
        name="gbm",
        description="HistGradientBoosting on the tier-1 feature set.",
        predictions=gbm.predict_proba(Xte)[:, 1],
        y_true=te["y"].to_numpy(dtype=int),
        feature_names=tuple(feats),
    )


def run_baseline_ladder(
    train: pd.DataFrame,
    test: pd.DataFrame,
    feature_frame: pd.DataFrame,
    *,
    seed: int = 0,
) -> list[BaselineResult]:
    """All baselines, in increasing order of sophistication."""
    return [
        fit_majority_baseline(train, test),
        fit_prior_assessment_baseline(train, test, feature_frame),
        fit_rolling_feature_baseline(train, test, feature_frame),
        fit_gbm_baseline(train, test, feature_frame, seed=seed),
    ]
