"""Recursive Bayesian filter  -  the synchronization property.

Each week: predict the state forward through the transition, then update it
against that week's observations. The posterior becomes next week's prior. No
history is replayed, which is exactly what test T1 checks.

Method: Laplace-approximate Gaussian filter. The emissions are non-Gaussian, so
the update has no closed form; we solve for the mode of the one-step log-posterior
by Newton iteration and take the negative inverse Hessian at the mode as the
covariance. This is an approximation and is labelled as one on every state object
it produces (`InferenceMethod.LAPLACE`).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import StateConfig
from ..schema import BEHAVIOR_TYPES, CanonicalType
from . import emissions as em
from .model import (
    InferenceMethod,
    StateTrajectory,
    StepAttribution,
    TwinParameters,
    TwinState,
    transition,
    transition_jacobian,
)

_JITTER = 1e-8


def _safe_inv(M: np.ndarray) -> np.ndarray:
    d = M.shape[0]
    for scale in (0.0, 1e-10, 1e-8, 1e-6, 1e-4, 1e-2):
        try:
            return np.linalg.inv(M + scale * np.eye(d))
        except np.linalg.LinAlgError:
            continue
    return np.linalg.pinv(M)


def _symmetrise(M: np.ndarray) -> np.ndarray:
    return 0.5 * (M + M.T)


class TwinFilter:
    """Recursive state estimator.

    The public surface (`filter_student`, `filter_all`) is deliberately method-
    agnostic so the MCMC reference track can be added as an alternative
    implementation without touching callers.
    """

    def __init__(self, params: TwinParameters, config: StateConfig | None = None) -> None:
        self.params = params
        self.config = config or StateConfig(
            n_dims=params.n_dims, dim_names=params.dim_names,
            alpha_init=tuple(params.alpha), process_noise_init=tuple(np.diag(params.Q)),
        )

    # -- one step --------------------------------------------------------

    def predict(
        self,
        state: TwinState,
        theta: np.ndarray,
        u: np.ndarray | None = None,
        d: np.ndarray | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Prior for week t+1 given the posterior at t."""
        m = transition(state.mean, theta, self.params, u=u, d=d)
        F = transition_jacobian(self.params)
        P = _symmetrise(F @ state.cov @ F.T + self.params.Q)
        return m, P

    def update(
        self, m_pred: np.ndarray, P_pred: np.ndarray, obs: dict[str, float]
    ) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray], int]:
        """Laplace update against one week of observations.

        Returns the posterior mean and covariance, the per-channel first-order
        contributions used for explanation, and how many channels were observed.
        """
        p = self.params
        P_inv = _safe_inv(P_pred)

        def channel_terms(z: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict[str, np.ndarray], int]:
            grad = np.zeros_like(m_pred)
            hess = np.zeros((len(m_pred), len(m_pred)))
            per: dict[str, np.ndarray] = {}
            n_obs = 0
            for ctype, (b0, load, phi) in p.count_params.items():
                if ctype not in obs:
                    continue
                _, g, h = em.negbin(float(obs[ctype]), z, b0, load, phi)
                grad += g
                hess += h
                per[ctype] = g
                n_obs += 1
            if p.submit_params is not None and CanonicalType.SUBMISSION.value in obs:
                b0, w = p.submit_params
                _, g, h = em.bernoulli(float(obs[CanonicalType.SUBMISSION.value]), z, b0, w)
                grad += g
                hess += h
                per[CanonicalType.SUBMISSION.value] = g
                n_obs += 1
            score = obs.get(CanonicalType.SCORE.value, np.nan)
            if p.score_params is not None and score is not None and np.isfinite(score):
                b0, w, sig = p.score_params
                _, g, h = em.gaussian_logit(float(score), z, b0, w, sig)
                grad += g
                hess += h
                per[CanonicalType.SCORE.value] = g
                n_obs += 1
            return grad, hess, per, n_obs

        # Newton iterations toward the mode of the log-posterior.
        z = m_pred.copy()
        for _ in range(self.config.max_newton_iters):
            g_obs, h_obs, _, _ = channel_terms(z)
            grad = -P_inv @ (z - m_pred) + g_obs
            H = -P_inv + h_obs
            H = _symmetrise(H) - _JITTER * np.eye(len(z))
            try:
                step = np.linalg.solve(H, grad)
            except np.linalg.LinAlgError:
                step = np.linalg.pinv(H) @ grad
            z_new = z - step
            if not np.all(np.isfinite(z_new)):
                break
            moved = float(np.max(np.abs(z_new - z)))
            z = z_new
            if moved < self.config.newton_tol:
                break

        g_obs, h_obs, _, n_obs = channel_terms(z)
        H = _symmetrise(-P_inv + h_obs) - _JITTER * np.eye(len(z))
        P_post = _symmetrise(_safe_inv(-H))
        # guard against a non-PD result from an extreme observation
        eigs = np.linalg.eigvalsh(P_post)
        if np.any(eigs <= 0):
            P_post = P_post + (abs(float(eigs.min())) + 1e-6) * np.eye(len(z))

        # Attribution is evaluated at the *prior* mean: it answers "what did this
        # week's evidence pull toward", not "what does the posterior imply".
        _, _, per_prior, _ = channel_terms(m_pred)
        contributions = {k: P_post @ v for k, v in per_prior.items()}
        return z, P_post, contributions, n_obs

    # -- whole trajectories ----------------------------------------------

    def filter_student(
        self,
        student_id: str,
        context_id: str,
        obs_rows: list[dict[str, float]],
        theta: np.ndarray,
        context_rows: list[np.ndarray] | None = None,
        interventions: list[np.ndarray] | None = None,
    ) -> StateTrajectory:
        """Filter one student's weeks in order. This is the twin's life cycle."""
        p = self.params
        traj = StateTrajectory(student_id=student_id, context_id=context_id)

        m = np.asarray(p.mu0, dtype=float).copy()
        P = np.asarray(p.P0, dtype=float).copy()
        prior_state = TwinState(
            student_id=student_id, context_id=context_id, t=-1,
            mean=m, cov=P, method=InferenceMethod.PRIOR, n_observations=0,
        )

        total_obs = 0
        for i, obs in enumerate(obs_rows):
            u = context_rows[i] if context_rows is not None and i < len(context_rows) else None
            d = interventions[i] if interventions is not None and i < len(interventions) else None
            if i == 0:
                m_pred, P_pred = m, P
            else:
                m_pred, P_pred = self.predict(prior_state, theta, u=u, d=d)

            m_post, P_post, contrib, n_obs = self.update(m_pred, P_pred, obs)
            total_obs += n_obs

            state = TwinState(
                student_id=student_id, context_id=context_id, t=int(obs.get("t", i)),
                mean=m_post, cov=P_post, method=InferenceMethod.LAPLACE,
                n_observations=total_obs,
            )
            traj.states.append(state)
            traj.attributions.append(
                StepAttribution(
                    t=int(obs.get("t", i)),
                    prior_mean=m_pred,
                    posterior_mean=m_post,
                    per_channel=contrib,
                    observations={k: float(v) for k, v in obs.items()
                                  if k != "t" and v is not None and np.isfinite(v)},
                )
            )
            prior_state = state
        return traj

    def filter_all(
        self,
        obs_frame: pd.DataFrame,
        context_frame: pd.DataFrame | None = None,
        *,
        setpoints: dict[str, np.ndarray] | None = None,
        max_students: int | None = None,
    ) -> dict[str, StateTrajectory]:
        """Filter every student in an observation frame."""
        p = self.params
        obs_cols = [t.value for t in BEHAVIOR_TYPES if t.value in obs_frame.columns]
        for extra in (CanonicalType.SUBMISSION.value, CanonicalType.SCORE.value):
            if extra in obs_frame.columns:
                obs_cols.append(extra)

        ctx_lookup: dict[tuple[str, int], np.ndarray] = {}
        if context_frame is not None and len(p.context_covariates):
            cols = [c for c in p.context_covariates if c in context_frame.columns]
            for _, r in context_frame.iterrows():
                ctx_lookup[(str(r["context_id"]), int(r["t"]))] = r[cols].to_numpy(dtype=float)

        out: dict[str, StateTrajectory] = {}
        groups = obs_frame.groupby(["student_id", "context_id"], observed=True, sort=True)
        for n, ((sid, cid), grp) in enumerate(groups):
            if max_students is not None and n >= max_students:
                break
            grp = grp.sort_values("t")
            rows: list[dict[str, float]] = []
            ctx_rows: list[np.ndarray] = []
            for _, r in grp.iterrows():
                d = {"t": int(r["t"])}
                for c in obs_cols:
                    v = r[c]
                    if c == CanonicalType.SCORE.value:
                        if pd.notna(v):
                            d[c] = float(v)
                    else:
                        d[c] = float(v) if pd.notna(v) else 0.0
                rows.append(d)
                ctx_rows.append(
                    ctx_lookup.get(
                        (str(cid), int(r["t"])), np.zeros(len(p.context_covariates))
                    )
                )
            theta = (setpoints or {}).get(str(sid))
            if theta is None:
                theta = p.setpoint(str(cid), None, 0)
            out[str(sid)] = self.filter_student(
                str(sid), str(cid), rows, theta, context_rows=ctx_rows
            )
        return out
