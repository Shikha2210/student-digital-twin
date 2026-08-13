"""Ground-truth recovery against the synthetic generative process.

This is the only place in the project where we know the right answer. The fixture
is generated from a known latent process, so these tests measure whether the
estimator recovers what actually produced the data, rather than whether it
produces plausible-looking output.

Tolerances are set from measured behaviour and act as regression guards. Where
current behaviour falls short of what we would want, the test asserts the
measured reality and says so - it does not assert an aspiration the code does not
meet, and it does not quietly lower the bar.
"""

from __future__ import annotations

import numpy as np
import pytest

from student_twin.adapters import get_adapter
from student_twin.config import Config
from student_twin.features.context import build_context_covariates
from student_twin.features.tier1 import observation_frame
from student_twin.state.filter import TwinFilter
from student_twin.state.fit import fit_twin

N_STUDENTS = 200
N_WEEKS = 20
SEED = 11


@pytest.fixture(scope="module")
def recovery():
    """Fit the twin on a known cohort and align estimates with the truth."""
    cfg = Config()
    adapter = get_adapter("synthetic", n_students=N_STUDENTS, n_weeks=N_WEEKS, seed=SEED)
    data = adapter.load()
    obs = observation_frame(data.events, n_weeks=N_WEEKS)
    ctx = build_context_covariates(data.events, data.contexts, n_weeks=N_WEEKS)
    params = fit_twin(data, obs, ctx, cfg)
    setpoints = getattr(params, "student_setpoints", {})
    trajs = TwinFilter(params, cfg.state).filter_all(obs, ctx, setpoints=setpoints)

    truth, true_sp = adapter.true_states, adapter.true_setpoints
    Z, T, dZ, dT, inside, est_sp, tru_sp = [], [], [], [], [], [], []
    for sid, tr in trajs.items():
        tt = truth.get(sid)
        if tt is None or len(tt) < 3:
            continue
        n = min(len(tr), len(tt))
        zf = np.vstack([s.mean for s in tr.states])[:n]
        sd = np.vstack([s.sd for s in tr.states])[:n]
        zt = tt[:n]
        Z.append(zf)
        T.append(zt)
        dZ.append(np.diff(zf, axis=0))
        dT.append(np.diff(zt, axis=0))
        inside.append(np.abs(zf - zt) <= 1.96 * sd)
        est_sp.append(setpoints.get(sid, params.mu0))
        tru_sp.append(true_sp[sid])

    return {
        "params": params,
        "Z": np.vstack(Z), "T": np.vstack(T),
        "dZ": np.vstack(dZ), "dT": np.vstack(dT),
        "inside": np.vstack(inside),
        "est_sp": np.vstack(est_sp), "tru_sp": np.vstack(tru_sp),
        "adapter": adapter, "data": data, "cfg": cfg,
    }


def _r(a, b) -> float:
    return float(np.corrcoef(a, b)[0, 1])


# ------------------------------------------------------------ state level ---

def test_engagement_state_is_recovered(recovery):
    r = _r(recovery["Z"][:, 0], recovery["T"][:, 0])
    assert r > 0.85, f"engagement state correlation with truth is only {r:.3f}"


def test_capability_state_is_recovered_weakly(recovery):
    """Capability recovers far less well than engagement, and that is expected.

    Scores arrive every 3-4 weeks; engagement is observed through four count
    channels every week. The capability dimension is simply much less observed.
    """
    r = _r(recovery["Z"][:, 1], recovery["T"][:, 1])
    assert r > 0.50, f"capability state correlation with truth is only {r:.3f}"


# -------------------------------------------------------------- trajectory ---

def test_trajectory_recovery_is_weaker_than_level_recovery(recovery):
    """Documents Gate 1 weakness 1 as a measurement, not an impression.

    The filter recovers WHERE a student sits much better than HOW they are
    moving. This is the same conclusion the level/trajectory decomposition and
    the permute_time control reach independently.
    """
    level = _r(recovery["Z"][:, 0], recovery["T"][:, 0])
    traj = _r(recovery["dZ"][:, 0], recovery["dT"][:, 0])
    assert traj < level, "trajectory recovery unexpectedly matched level recovery"
    assert traj > 0.40, f"engagement week-to-week change correlation collapsed to {traj:.3f}"


def test_capability_trajectory_is_essentially_unrecovered(recovery):
    """Honest lower bound: week-to-week capability change is near noise.

    Recorded so that a future change which improves it is visible as a change.
    """
    traj = _r(recovery["dZ"][:, 1], recovery["dT"][:, 1])
    assert traj < 0.40, (
        f"capability trajectory recovery is now {traj:.3f} - if this improved, "
        "update the docs, the claim that it is unrecovered no longer holds"
    )


# ----------------------------------------------------------------- setpoint ---

def test_personal_setpoints_are_recovered(recovery):
    """The personalisation claim: does theta_i track the student's real norm?"""
    r = _r(recovery["est_sp"][:, 0], recovery["tru_sp"][:, 0])
    assert r > 0.80, f"engagement setpoint correlation is only {r:.3f}"


# -------------------------------------------------------------- uncertainty ---

def test_state_intervals_are_overconfident(recovery):
    """KNOWN DEFICIENCY, measured and pinned.

    Nominal 95% intervals cover only ~82% of true states. The twin is
    over-confident about where a student is, exactly as assumption A-05 predicts:
    parameter and transfer uncertainty are not estimated, so reported intervals
    are too narrow.

    The assertion band is a regression guard around measured behaviour. It is NOT
    an endorsement - 0.82 is not 0.95, and closing that gap is Phase 3 work.
    """
    cov = recovery["inside"].mean(axis=0)
    assert (cov > 0.70).all(), f"interval coverage collapsed further: {np.round(cov, 3)}"
    assert (cov < 0.93).any(), (
        f"coverage {np.round(cov, 3)} now looks calibrated - if uncertainty was "
        "fixed, update A-05 and this test"
    )


# ------------------------------------------------- emission scale regression ---

def test_emission_loadings_are_not_inflated(recovery):
    """Regression guard for the post-withdrawal grid bug.

    Before the at-risk truncation, ~30% of observation rows were fabricated
    all-zero weeks from students who had already left. Those spurious zeros
    inflated every emission loading by ~2.2x. Loadings within ~35% of truth mean
    the grid is still being truncated correctly.
    """
    from student_twin.adapters.synthetic import TRUE_LOADINGS

    params = recovery["params"]
    for ctype, (_, true_load) in TRUE_LOADINGS.items():
        if ctype.value not in params.count_params:
            continue
        _, load, _ = params.count_params[ctype.value]
        ratio = load[0] / true_load
        assert 0.65 < ratio < 1.35, (
            f"{ctype.value} loading ratio {ratio:.2f} is far from 1.0 - the "
            "observation grid may be extending past withdrawal again"
        )


# ------------------------------------------------------------- intervention ---

def test_intervention_response_matches_declared_sensitivity(recovery):
    """The simulated response must follow the C matrix we declared.

    This verifies the machinery, NOT a causal effect: C is assumed, never fitted
    (A-08). All this shows is that the simulator applies what it was told.
    """
    from student_twin.config import rng_for
    from student_twin.simulation import Intervention, InterventionScenario, simulate_forward
    from student_twin.simulation.intervention import DEFAULT_SENSITIVITY

    params = recovery["params"]
    cfg = recovery["cfg"]
    traj = None
    for t in recovery.get("_", []):
        pass
    adapter = recovery["adapter"]
    from student_twin.state.model import InferenceMethod, TwinState

    state = TwinState("probe", "SYN0_2026A", 5, np.zeros(params.n_dims),
                      np.eye(params.n_dims) * 0.1, InferenceMethod.LAPLACE)
    theta = np.zeros(params.n_dims)
    kw = dict(horizon=6, n_particles=600)
    base = simulate_forward(state, theta, params, InterventionScenario.baseline(),
                            rng=rng_for(cfg, "iv"), **kw)
    scen = InterventionScenario("boost", (Intervention("engagement_support", 1.0),))
    alt = simulate_forward(state, theta, params, scen, rng=rng_for(cfg, "iv"), **kw)

    delta = alt.states[:, 0, 0].mean() - base.states[:, 0, 0].mean()
    expected = DEFAULT_SENSITIVITY["engagement_support"][0]
    assert delta > 0, "declared positive sensitivity produced a non-positive response"
    assert abs(delta - expected) < 0.15, (
        f"first-step response {delta:.3f} does not match declared sensitivity {expected}"
    )
