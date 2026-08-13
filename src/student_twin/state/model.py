"""State objects and the transition.

The Gate 1 transition, implemented literally:

    z_{t+1} = z_t + alpha * (theta_i - z_t) + B u_t + C d_t + eps_t

`d_t` is the intervention vector. In OULAD it is identically zero  -  no
interventions are recorded. It exists in the transition so that simulation is
structurally possible and so that the difference between "observed" and
"hypothesised" is a type-level distinction rather than a naming convention.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np


class InferenceMethod(StrEnum):
    """How a state estimate was produced. Carried on every state object.

    A plot that mixes methods without saying so is a misreport, so the label
    travels with the data rather than living in a docstring.
    """

    LAPLACE = "laplace_approximate"      # production track, implemented
    MCMC = "mcmc_reference"              # reference track, not implemented
    PRIOR = "prior_only"                 # no observations yet
    SIMULATED = "simulated_forward"      # generated, not inferred


@dataclass(frozen=True)
class TwinState:
    """A student's latent state at one week, with its uncertainty.

    `mean` and `cov` are the Gaussian approximation to p(z_t | y_{1:t}).
    """

    student_id: str
    context_id: str
    t: int
    mean: np.ndarray                 # (d,)
    cov: np.ndarray                  # (d, d)
    method: InferenceMethod = InferenceMethod.LAPLACE
    n_observations: int = 0          # how much evidence has been absorbed

    @property
    def sd(self) -> np.ndarray:
        return np.sqrt(np.clip(np.diag(self.cov), 0.0, None))

    def interval(self, dim: int, z: float = 1.96) -> tuple[float, float]:
        m, s = float(self.mean[dim]), float(self.sd[dim])
        return (m - z * s, m + z * s)

    def as_dict(self, dim_names: tuple[str, ...]) -> dict[str, float | str | int]:
        out: dict[str, float | str | int] = {
            "student_id": self.student_id,
            "context_id": self.context_id,
            "t": self.t,
            "method": str(self.method),
            "n_observations": self.n_observations,
        }
        for i, name in enumerate(dim_names):
            out[f"{name}_mean"] = float(self.mean[i])
            out[f"{name}_sd"] = float(self.sd[i])
        return out


@dataclass(frozen=True)
class StepAttribution:
    """Why the state moved this week.

    `per_channel` decomposes the prior-to-posterior shift by observation channel.
    The decomposition is the first-order Bayesian one: for a Gaussian-approximate
    update, the mean shift is P_post @ sum_c grad_c, so each channel's share is
    P_post @ grad_c evaluated at the predicted mean. Contributions therefore sum
    to the total shift up to Newton's higher-order correction, and `residual`
    reports exactly that gap rather than hiding it.
    """

    t: int
    prior_mean: np.ndarray
    posterior_mean: np.ndarray
    per_channel: dict[str, np.ndarray]
    observations: dict[str, float]

    @property
    def total_shift(self) -> np.ndarray:
        return self.posterior_mean - self.prior_mean

    @property
    def residual(self) -> np.ndarray:
        explained = sum(self.per_channel.values()) if self.per_channel else 0.0
        return self.total_shift - explained

    def ranked(self, dim: int, dim_name: str = "") -> list[tuple[str, float]]:
        items = [(k, float(v[dim])) for k, v in self.per_channel.items()]
        return sorted(items, key=lambda kv: abs(kv[1]), reverse=True)


@dataclass
class StateTrajectory:
    """A student's full filtered history  -  the persistent twin object."""

    student_id: str
    context_id: str
    states: list[TwinState] = field(default_factory=list)
    attributions: list[StepAttribution] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.states)

    @property
    def current(self) -> TwinState:
        if not self.states:
            raise ValueError(f"no states for student {self.student_id}")
        return self.states[-1]

    def at(self, t: int) -> TwinState | None:
        for s in self.states:
            if s.t == t:
                return s
        return None

    def attribution_at(self, t: int) -> StepAttribution | None:
        for a in self.attributions:
            if a.t == t:
                return a
        return None

    def means(self) -> np.ndarray:
        return np.vstack([s.mean for s in self.states]) if self.states else np.empty((0, 0))

    def sds(self) -> np.ndarray:
        return np.vstack([s.sd for s in self.states]) if self.states else np.empty((0, 0))

    def to_frame(self, dim_names: tuple[str, ...]):
        import pandas as pd

        return pd.DataFrame([s.as_dict(dim_names) for s in self.states])


@dataclass
class TwinParameters:
    """Fitted parameters of the state-space model.

    Emission parameters are keyed by canonical type so that a dataset lacking a
    channel simply has no entry  -  the filter skips it rather than imputing zero.
    """

    n_dims: int
    dim_names: tuple[str, ...]

    alpha: np.ndarray                                  # (d,) reversion rate
    Q: np.ndarray                                      # (d, d) process noise
    B: np.ndarray                                      # (d, n_ctx)
    C: np.ndarray                                      # (d, n_interventions)
    context_covariates: tuple[str, ...]
    intervention_names: tuple[str, ...]

    # emissions
    count_params: dict[str, tuple[float, np.ndarray, float]] = field(default_factory=dict)
    submit_params: tuple[float, np.ndarray] | None = None
    score_params: tuple[float, np.ndarray, float] | None = None

    mu0: np.ndarray | None = None                      # (d,) global prior mean
    P0: np.ndarray | None = None                       # (d, d) prior covariance
    setpoint_shrinkage: float = 4.0
    context_means: dict[str, np.ndarray] = field(default_factory=dict)

    fitted_on: str = "unknown"
    synthetic: bool = False

    def __post_init__(self) -> None:
        d = self.n_dims
        if self.mu0 is None:
            self.mu0 = np.zeros(d)
        if self.P0 is None:
            self.P0 = np.eye(d)
        for name, arr, shape in (
            ("alpha", self.alpha, (d,)),
            ("Q", self.Q, (d, d)),
            ("mu0", self.mu0, (d,)),
            ("P0", self.P0, (d, d)),
        ):
            if np.shape(arr) != shape:
                raise ValueError(f"{name} has shape {np.shape(arr)}, expected {shape}")
        if np.any(self.alpha < 0) or np.any(self.alpha > 1):
            raise ValueError("alpha must lie in [0, 1]: it is a per-week reversion fraction")

    def setpoint(self, context_id: str, student_mean: np.ndarray | None, n_obs: int) -> np.ndarray:
        """Empirical-Bayes personal set point.

        Shrinks the student's own average toward the context mean, with weight
        governed by how much has been seen. This is the partial pooling that makes
        a brand-new student behave like their cohort instead of like nothing.
        """
        ctx = self.context_means.get(context_id, self.mu0)
        if student_mean is None or n_obs <= 0:
            return np.asarray(ctx, dtype=float)
        k = self.setpoint_shrinkage
        return (n_obs * np.asarray(student_mean) + k * np.asarray(ctx)) / (n_obs + k)


def transition(
    z: np.ndarray,
    theta: np.ndarray,
    params: TwinParameters,
    u: np.ndarray | None = None,
    d: np.ndarray | None = None,
) -> np.ndarray:
    """Deterministic part of the Gate 1 transition (equation 7)."""
    z = np.asarray(z, dtype=float)
    out = z + params.alpha * (np.asarray(theta, dtype=float) - z)
    if u is not None and params.B.size:
        out = out + params.B @ np.asarray(u, dtype=float)
    if d is not None and params.C.size:
        out = out + params.C @ np.asarray(d, dtype=float)
    return out


def transition_jacobian(params: TwinParameters) -> np.ndarray:
    """d z_{t+1} / d z_t = diag(1 - alpha)."""
    return np.diag(1.0 - params.alpha)
