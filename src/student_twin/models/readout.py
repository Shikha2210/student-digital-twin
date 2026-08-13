"""Discrete-time hazard readout.

    h_{i,t} = sigmoid( gamma . z_{i,t} + gamma_u . u_{c,t} + gamma_0 )

Dropout is a timing problem, so the target is a per-week hazard on person-period
data rather than a single end-of-course label. Students still enrolled at the
last observed week are censored, not negatives  -  treating them as negatives is a
standard and serious error that inflates every metric.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

from ..schema import OutcomeTable
from ..state.model import StateTrajectory, TwinParameters


def build_person_period(
    trajectories: dict[str, StateTrajectory],
    outcomes: OutcomeTable,
    params: TwinParameters,
    context_frame: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Long-format risk set: one row per student-week at risk.

    A student who withdraws in week 6 contributes weeks 0..6, with y = 1 only in
    week 6. A student who completes contributes every observed week with y = 0.
    Weeks after withdrawal do not exist  -  they are not zeros.
    """
    out = outcomes.df.set_index("student_id")
    rows: list[dict] = []

    for sid, traj in trajectories.items():
        if sid not in out.index:
            continue
        rec = out.loc[sid]
        if isinstance(rec, pd.DataFrame):
            rec = rec.iloc[0]
        observed = bool(rec["event_observed"])
        ev_week = rec["event_week"]
        ev_week = float(ev_week) if pd.notna(ev_week) else np.inf

        for st in traj.states:
            if st.t > ev_week:
                break                      # no longer at risk
            y = int(observed and st.t == ev_week)
            row = {
                "student_id": sid,
                "context_id": traj.context_id,
                "t": st.t,
                "y": y,
                "n_observations": st.n_observations,
            }
            for j, name in enumerate(params.dim_names):
                row[f"z_{name}"] = float(st.mean[j])
                row[f"sd_{name}"] = float(st.sd[j])
            rows.append(row)

    pp = pd.DataFrame(rows)
    if context_frame is not None and len(pp) and len(params.context_covariates):
        cols = [c for c in params.context_covariates if c in context_frame.columns]
        if cols:
            pp = pp.merge(
                context_frame[["context_id", "t", *cols]], on=["context_id", "t"], how="left"
            )
            pp[cols] = pp[cols].fillna(0.0)
    return pp


@dataclass
class HazardReadout:
    """Fitted hazard model. Holds no state of its own."""

    coef: np.ndarray
    intercept: float
    feature_names: tuple[str, ...]
    dim_names: tuple[str, ...]
    n_train_rows: int = 0

    @classmethod
    def fit(
        cls,
        person_period: pd.DataFrame,
        params: TwinParameters,
        *,
        use_context: bool = True,
    ) -> "HazardReadout":
        feats = [f"z_{n}" for n in params.dim_names]
        if use_context:
            feats += [c for c in params.context_covariates if c in person_period.columns]
        X = person_period[feats].to_numpy(dtype=float)
        y = person_period["y"].to_numpy(dtype=int)
        if len(np.unique(y)) < 2:
            return cls(
                coef=np.zeros(len(feats)),
                intercept=float(np.log((y.mean() + 1e-6) / (1 - y.mean() + 1e-6))),
                feature_names=tuple(feats),
                dim_names=params.dim_names,
                n_train_rows=len(y),
            )
        lr = LogisticRegression(max_iter=1000, C=1.0).fit(X, y)
        return cls(
            coef=lr.coef_[0],
            intercept=float(lr.intercept_[0]),
            feature_names=tuple(feats),
            dim_names=params.dim_names,
            n_train_rows=len(y),
        )

    def hazard(self, person_period: pd.DataFrame) -> np.ndarray:
        X = person_period[list(self.feature_names)].to_numpy(dtype=float)
        eta = np.clip(self.intercept + X @ self.coef, -30, 30)
        return 1.0 / (1.0 + np.exp(-eta))

    def state_only_params(self) -> tuple[float, np.ndarray]:
        """(intercept, weights on state dims) for use inside forward simulation."""
        w = np.zeros(len(self.dim_names))
        for j, name in enumerate(self.dim_names):
            key = f"z_{name}"
            if key in self.feature_names:
                w[j] = self.coef[self.feature_names.index(key)]
        return float(self.intercept), w

    def cumulative_risk(self, person_period: pd.DataFrame) -> pd.DataFrame:
        """Per-student P(withdrawn by week t) from the weekly hazards."""
        pp = person_period.copy()
        pp["hazard"] = self.hazard(pp)
        pp = pp.sort_values(["student_id", "t"])
        pp["survival"] = (
            pp.groupby("student_id", observed=True)["hazard"].transform(lambda h: (1 - h).cumprod())
        )
        pp["cum_risk"] = 1.0 - pp["survival"]
        return pp
