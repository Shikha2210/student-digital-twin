"""Forward generative simulation  -  the generativity property.

Given a filtered state, sample particles from its posterior, push them through
the transition for K weeks, and emit observations at each step. The result is a
distribution over trajectories, not a point forecast, because a twin that reports
one future is claiming a certainty it does not have.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..schema import CanonicalType
from ..state.emissions import hazard_logit
from ..state.model import InferenceMethod, TwinParameters, TwinState, transition
from .intervention import InterventionScenario


@dataclass
class SimulationResult:
    """Model-generated trajectories. Not a prediction of what will happen."""

    student_id: str
    context_id: str
    scenario: InterventionScenario
    start_week: int
    horizon: int
    dim_names: tuple[str, ...]

    states: np.ndarray            # (n_particles, horizon, d)
    observations: dict[str, np.ndarray]   # canonical_type -> (n_particles, horizon)
    hazard: np.ndarray | None = None      # (n_particles, horizon)

    is_counterfactual: bool = True
    synthetic_source: bool = False

    def state_quantiles(self, q: tuple[float, ...]) -> pd.DataFrame:
        rows = []
        for h in range(self.horizon):
            row = {"t": self.start_week + 1 + h}
            for j, name in enumerate(self.dim_names):
                vals = self.states[:, h, j]
                for qq in q:
                    row[f"{name}_q{int(qq * 100):02d}"] = float(np.quantile(vals, qq))
                row[f"{name}_mean"] = float(vals.mean())
            rows.append(row)
        return pd.DataFrame(rows)

    def observation_quantiles(self, ctype: str, q: tuple[float, ...]) -> pd.DataFrame:
        arr = self.observations[ctype]
        rows = []
        for h in range(self.horizon):
            row = {"t": self.start_week + 1 + h, "mean": float(arr[:, h].mean())}
            for qq in q:
                row[f"q{int(qq * 100):02d}"] = float(np.quantile(arr[:, h], qq))
            rows.append(row)
        return pd.DataFrame(rows)

    def cumulative_risk(self) -> np.ndarray | None:
        """P(withdrawn by each future week), averaged over particles."""
        if self.hazard is None:
            return None
        survive = np.cumprod(1.0 - self.hazard, axis=1)
        return 1.0 - survive.mean(axis=0)

    def provenance(self) -> str:
        base = (
            f"MODEL-GENERATED SCENARIO: {self.scenario.label}. "
            f"{self.scenario.describe()} "
            f"Trajectories are simulated from the fitted transition dynamics and are "
            f"not observations."
        )
        if self.synthetic_source:
            base += " SOURCE DATA IS SYNTHETIC: this says nothing about real students."
        return base


def simulate_forward(
    state: TwinState,
    theta: np.ndarray,
    params: TwinParameters,
    scenario: InterventionScenario,
    *,
    horizon: int = 8,
    n_particles: int = 500,
    context_rows: list[np.ndarray] | None = None,
    hazard_params: tuple[float, np.ndarray] | None = None,
    rng: np.random.Generator | None = None,
) -> SimulationResult:
    """Monte-Carlo the twin forward under a scenario.

    Particles are drawn from the filtered posterior, so the bands widen with both
    process noise and the state uncertainty we already had. Collapsing to the
    posterior mean would understate the spread and make the twin look more
    confident than it is.
    """
    rng = rng or np.random.default_rng(0)
    d = params.n_dims

    cov = np.atleast_2d(state.cov)
    try:
        particles = rng.multivariate_normal(state.mean, cov, size=n_particles)
    except np.linalg.LinAlgError:
        particles = state.mean + rng.normal(0, np.sqrt(np.diag(cov) + 1e-6),
                                            size=(n_particles, d))

    states = np.zeros((n_particles, horizon, d))
    obs: dict[str, list[np.ndarray]] = {c: [] for c in params.count_params}
    if params.submit_params is not None:
        obs[CanonicalType.SUBMISSION.value] = []
    if params.score_params is not None:
        obs[CanonicalType.SCORE.value] = []
    hazards = np.zeros((n_particles, horizon)) if hazard_params is not None else None

    chol = np.linalg.cholesky(params.Q + 1e-9 * np.eye(d))

    for h in range(horizon):
        u = context_rows[h] if context_rows is not None and h < len(context_rows) else None
        dvec = scenario.vector_at(h)
        noise = rng.standard_normal((n_particles, d)) @ chol.T
        particles = (
            np.array([transition(p, theta, params, u=u, d=dvec) for p in particles]) + noise
        )
        states[:, h, :] = particles

        for ctype, (b0, load, phi) in params.count_params.items():
            eta = np.clip(b0 + particles @ load, -12, 12)
            mu = np.exp(eta)
            lam = rng.gamma(phi, mu / phi)
            obs[ctype].append(rng.poisson(lam).astype(float))

        if params.submit_params is not None:
            b0, w = params.submit_params
            p_sub = 1.0 / (1.0 + np.exp(-np.clip(b0 + particles @ w, -12, 12)))
            obs[CanonicalType.SUBMISSION.value].append((rng.random(n_particles) < p_sub).astype(float))

        if params.score_params is not None:
            b0, w, sig = params.score_params
            eta = b0 + particles @ w + rng.normal(0, sig, size=n_particles)
            obs[CanonicalType.SCORE.value].append(1.0 / (1.0 + np.exp(-np.clip(eta, -12, 12))))

        if hazards is not None and hazard_params is not None:
            hb0, hw = hazard_params
            hazards[:, h] = [hazard_logit(p, hb0, hw) for p in particles]

    return SimulationResult(
        student_id=state.student_id,
        context_id=state.context_id,
        scenario=scenario,
        start_week=state.t,
        horizon=horizon,
        dim_names=params.dim_names,
        states=states,
        observations={k: np.column_stack(v) for k, v in obs.items() if v},
        hazard=hazards,
        is_counterfactual=scenario.is_counterfactual,
        synthetic_source=params.synthetic,
    )


def posterior_predictive_check(
    sim: SimulationResult, actual: pd.DataFrame, ctype: str
) -> dict[str, float]:
    """T2 diagnostic: are simulated observations distributionally plausible?

    Reports coverage of the 90% band and a dispersion ratio. A dispersion ratio
    well below 1 is the classic failure  -  simulated futures smoother than real
    ones  -  and is the specific thing Gate 1 T2 says would force withdrawal of the
    scenario feature.
    """
    if ctype not in sim.observations or actual.empty:
        return {"coverage_90": float("nan"), "dispersion_ratio": float("nan"), "n": 0}
    weeks = [sim.start_week + 1 + h for h in range(sim.horizon)]
    act = actual.set_index("t")[ctype] if ctype in actual.columns else None
    if act is None:
        return {"coverage_90": float("nan"), "dispersion_ratio": float("nan"), "n": 0}

    hits, sim_sds, act_vals = [], [], []
    for h, wk in enumerate(weeks):
        if wk not in act.index:
            continue
        a = float(act.loc[wk]) if np.ndim(act.loc[wk]) == 0 else float(act.loc[wk].iloc[0])
        col = sim.observations[ctype][:, h]
        lo, hi = np.quantile(col, [0.05, 0.95])
        hits.append(lo <= a <= hi)
        sim_sds.append(col.std())
        act_vals.append(a)

    if not hits:
        return {"coverage_90": float("nan"), "dispersion_ratio": float("nan"), "n": 0}
    act_sd = float(np.std(act_vals)) if len(act_vals) > 1 else float("nan")
    mean_sim_sd = float(np.mean(sim_sds))
    return {
        "coverage_90": float(np.mean(hits)),
        "dispersion_ratio": float(mean_sim_sd / act_sd) if act_sd and act_sd > 0 else float("nan"),
        "n": len(hits),
    }
