"""Twin state: transition, recursive update, persistence, uncertainty."""

from __future__ import annotations

import numpy as np
import pytest

from student_twin.config import StateConfig
from student_twin.evaluation.twin_tests import check_T1_sufficiency
from student_twin.state.model import (
    InferenceMethod,
    TwinState,
    transition,
    transition_jacobian,
)


# ---------------------------------------------------------------- config ---

def test_latent_dimension_cap_is_enforced():
    """Gate 1 allows 2 by default, 3 maximum. This is validated, not advisory."""
    with pytest.raises(ValueError, match="Gate 1 constraint"):
        StateConfig(n_dims=5, dim_names=("a", "b", "c", "d", "e"),
                    alpha_init=(0.1,) * 5, process_noise_init=(0.1,) * 5)


def test_dim_names_must_match_n_dims():
    with pytest.raises(ValueError, match="dim_names"):
        StateConfig(n_dims=2, dim_names=("only_one",))


# ------------------------------------------------------------ transition ---

def test_transition_reverts_toward_setpoint(params):
    """With no covariates or interventions, state moves toward theta, not past it."""
    theta = np.array([1.0, 1.0])
    z = np.array([0.0, 0.0])
    z1 = transition(z, theta, params)
    assert np.all(z1 > z)
    assert np.all(z1 <= theta + 1e-9)


def test_transition_fixed_point_at_setpoint(params):
    theta = np.array([0.4, -0.2])
    assert np.allclose(transition(theta, theta, params), theta)


def test_intervention_moves_state(params):
    """Intervenability: a non-zero d must change the transition output."""
    theta = np.zeros(params.n_dims)
    z = np.zeros(params.n_dims)
    d = np.zeros(len(params.intervention_names))
    d[0] = 1.0
    assert not np.allclose(transition(z, theta, params), transition(z, theta, params, d=d))


def test_intervention_channel_is_separate_from_observations(params):
    """No observation can write to d - the separation is structural."""
    from student_twin.simulation.intervention import Intervention

    with pytest.raises(ValueError, match="unknown intervention"):
        Intervention("content_view")


def test_jacobian_matches_alpha(params):
    assert np.allclose(np.diag(transition_jacobian(params)), 1.0 - params.alpha)


# ---------------------------------------------------------------- filter ---

def test_recursive_update_changes_state(twin_filter, params):
    prior = TwinState("s", "c", 0, np.zeros(params.n_dims), np.eye(params.n_dims),
                      InferenceMethod.PRIOR)
    m, P, contrib, n = twin_filter.update(
        prior.mean, prior.cov, {"content_view": 40.0, "resource": 20.0}
    )
    assert not np.allclose(m, prior.mean), "observations must move the state"
    assert n >= 1
    assert contrib, "attribution must be produced"


def test_uncertainty_shrinks_with_evidence(twin_filter, params):
    """More observation reduces posterior variance. If not, the filter is wrong."""
    P0 = np.eye(params.n_dims) * 2.0
    m0 = np.zeros(params.n_dims)
    _, P1, _, _ = twin_filter.update(m0, P0, {"content_view": 30.0})
    assert np.trace(P1) < np.trace(P0)


def test_posterior_covariance_is_positive_definite(twin_filter, params):
    m0 = np.zeros(params.n_dims)
    for obs in ({"content_view": 0.0}, {"content_view": 5000.0}, {"submission": 1.0}):
        _, P, _, _ = twin_filter.update(m0, np.eye(params.n_dims), obs)
        assert np.all(np.linalg.eigvalsh(P) > 0), f"non-PD covariance for {obs}"


def test_no_observations_leaves_state_at_prior(twin_filter, params):
    """An empty week must not fabricate an update."""
    m0 = np.ones(params.n_dims) * 0.3
    P0 = np.eye(params.n_dims)
    m, P, contrib, n = twin_filter.update(m0, P0, {})
    assert n == 0
    assert contrib == {}
    assert np.allclose(m, m0)


def test_missing_score_is_not_treated_as_zero(twin_filter, params):
    """A NaN score must be skipped, not imputed - imputing destroys the signal."""
    m0 = np.zeros(params.n_dims)
    P0 = np.eye(params.n_dims)
    a, _, ca, _ = twin_filter.update(m0, P0, {"content_view": 10.0})
    b, _, cb, _ = twin_filter.update(m0, P0, {"content_view": 10.0, "score": float("nan")})
    assert np.allclose(a, b)
    assert "score" not in ca and "score" not in cb


def test_state_persists_across_weeks(twin_filter, params):
    rows = [{"t": t, "content_view": 20.0, "resource": 5.0} for t in range(6)]
    traj = twin_filter.filter_student("s", "c", rows, np.zeros(params.n_dims))
    assert len(traj) == 6
    assert [s.t for s in traj.states] == list(range(6))
    assert traj.states[-1].n_observations > traj.states[0].n_observations


def test_T1_sufficiency_holds(twin_filter, params):
    """The defining property: the state carries history without replaying it."""
    rows = [{"t": t, "content_view": 10.0 + t, "resource": 3.0} for t in range(10)]
    res = check_T1_sufficiency(twin_filter, rows, np.zeros(params.n_dims))
    assert res.passed, res.detail


def test_filter_is_deterministic(twin_filter, params):
    rows = [{"t": t, "content_view": 12.0} for t in range(5)]
    a = twin_filter.filter_student("s", "c", rows, np.zeros(params.n_dims))
    b = twin_filter.filter_student("s", "c", rows, np.zeros(params.n_dims))
    assert np.allclose(a.current.mean, b.current.mean)


def test_states_are_labelled_with_inference_method(twin_filter, params):
    rows = [{"t": 0, "content_view": 5.0}]
    traj = twin_filter.filter_student("s", "c", rows, np.zeros(params.n_dims))
    assert traj.current.method is InferenceMethod.LAPLACE
