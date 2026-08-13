"""The readout must behave correctly in BOTH regimes.

Two failure modes are possible and both are tested here:

  under-detection   the outcome genuinely depends on within-student deterioration
                    and the diagnostic fails to see it
  manufacture       the outcome is purely level-driven and the diagnostic invents
                    a trajectory story anyway

These test the *diagnostic and the regime machinery*. They deliberately do NOT
assert that the twin predicts well in the trajectory-dominant regime, because it
does not - that limitation is pinned separately and honestly in
`test_known_limitation_...` below rather than hidden behind a softer threshold.
"""

from __future__ import annotations

import numpy as np
import pytest

from student_twin.config import Config
from student_twin.evaluation.twin_tests import decompose_level_vs_trajectory
from student_twin.pipeline import run_pipeline

N_STUDENTS = 300
N_WEEKS = 20


def _run(regime: str):
    return run_pipeline(
        Config(),
        adapter_name="synthetic",
        adapter_kwargs=dict(n_students=N_STUDENTS, n_weeks=N_WEEKS, regime=regime),
        run_controls=False,
    )


@pytest.fixture(scope="module")
def level_run():
    return _run("level_dominant")


@pytest.fixture(scope="module")
def traj_run():
    return _run("trajectory_dominant")


def _decompose(r):
    cut = max(3, int(r.person_period["t"].quantile(0.6)))
    return decompose_level_vs_trajectory(r.person_period, r.params, cut)


# ---------------------------------------------------- regime construction ---

def test_regimes_actually_differ_in_ground_truth():
    """Guard the instrument before trusting anything it measures.

    If both regimes generated the same latent structure, every test below would
    pass vacuously.
    """
    from student_twin.adapters import get_adapter

    shares = {}
    for regime in ("level_dominant", "trajectory_dominant"):
        a = get_adapter("synthetic", n_students=200, n_weeks=N_WEEKS, regime=regime)
        a.load()
        mus, devs = [], []
        for traj in a.true_states.values():
            if len(traj) < 3:
                continue
            m = traj.mean(axis=0)
            mus.append(m)
            devs.append(traj - m)
        vb = np.vstack(mus).var(axis=0)
        vw = np.vstack(devs).var(axis=0)
        shares[regime] = float((vb / (vb + vw))[0])

    assert shares["level_dominant"] > 0.70, shares
    assert shares["trajectory_dominant"] < 0.60, shares
    assert shares["level_dominant"] > shares["trajectory_dominant"] + 0.20


# -------------------------------------------------------- under-detection ---

def test_detects_within_student_deterioration_when_outcome_depends_on_it(traj_run):
    """Item 10: when risk genuinely depends on deviation from a personal baseline,
    the deviation term must carry more discrimination than the level term."""
    d = _decompose(traj_run)
    assert d.auc_deviation_only > d.auc_level_only, (
        f"deviation {d.auc_deviation_only:.3f} did not beat level "
        f"{d.auc_level_only:.3f} in a trajectory-dominant world"
    )
    assert d.trajectory_share > 0.50, f"trajectory share only {d.trajectory_share:.3f}"
    assert "TRAJECTORY-DRIVEN" in d.verdict


# ------------------------------------------------------------ manufacture ---

def test_does_not_manufacture_trajectory_signal_when_truth_is_level_driven(level_run):
    """Item 11: the mirror image. A level-dominant world must not be reported as
    trajectory-driven."""
    d = _decompose(level_run)
    assert d.auc_level_only > d.auc_deviation_only, (
        f"level {d.auc_level_only:.3f} did not beat deviation "
        f"{d.auc_deviation_only:.3f} in a level-dominant world"
    )
    assert d.trajectory_share < 0.40, f"trajectory share inflated to {d.trajectory_share:.3f}"
    assert "TRAJECTORY-DRIVEN" not in d.verdict


# ------------------------------------------------------- shrinkage adapts ---

def test_setpoint_shrinkage_adapts_to_the_regime(level_run, traj_run):
    """The empirical-Bayes ratio k = sigma_within^2 / tau_between^2 must respond
    to how much students actually differ.

    A fixed k cannot: measured with k pinned at 4.0, the estimated set points had
    over twice the true between-student spread, and everything that subtracted
    them subtracted noise.
    """
    k_level = np.atleast_1d(np.asarray(level_run.params.setpoint_shrinkage, dtype=float))
    k_traj = np.atleast_1d(np.asarray(traj_run.params.setpoint_shrinkage, dtype=float))
    assert k_level[0] < k_traj[0], (
        f"shrinkage did not adapt: level k={k_level[0]:.2f}, trajectory k={k_traj[0]:.2f}. "
        "Students who genuinely differ should be shrunk LESS."
    )
    assert level_run.params.between_var[0] > traj_run.params.between_var[0]


def test_shrinkage_is_estimated_not_the_config_default(level_run):
    """Regression guard: the config value is a fallback, not the operative number."""
    k = np.atleast_1d(np.asarray(level_run.params.setpoint_shrinkage, dtype=float))
    assert not np.allclose(k, 4.0), "shrinkage looks like the hard-coded default"
    assert level_run.params.between_var is not None
    assert level_run.params.within_var is not None


# ------------------------------------------------------ known limitation ---

def test_known_limitation_twin_underperforms_features_when_trajectory_dominates(traj_run):
    """PINNED FAILURE, not a passing grade.

    When risk depends on fast within-student change, the 2-D latent state loses to
    plain tier-1 features. Week-to-week trajectory recovery is r ~ 0.57 in BOTH
    regimes - an information limit set by weekly count noise, not by the readout.
    A 2-D state compressed for reconstruction cannot retain fluctuation that is
    not identifiable from a single week of counts.

    This test exists so the limitation cannot be silently "fixed" by a change that
    merely moves numbers around. If the twin ever genuinely beats features here,
    this test fails and the docs must be updated to say so.
    """
    m = {x.name: x.auc for x in traj_run.metrics}
    assert m["twin_state"] < m["rolling_features"] + 0.05, (
        f"twin {m['twin_state']:.3f} now matches or beats rolling_features "
        f"{m['rolling_features']:.3f} in the trajectory regime - genuinely good "
        "news, but update README and docs/assumptions.md A-16 before relaxing this."
    )


def test_twin_still_leads_in_the_level_dominant_regime(level_run):
    """The twin must not have been broken in the regime where it does work."""
    m = {x.name: x.auc for x in level_run.metrics}
    assert m["twin_state"] > m["rolling_features"], (
        f"twin {m['twin_state']:.3f} lost to rolling_features {m['rolling_features']:.3f} "
        "in the level-dominant regime"
    )
    assert m["twin_state"] > 0.65
