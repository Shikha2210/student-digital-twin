"""Readout, baselines, simulation, intervention, and negative controls."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from student_twin.config import Config, rng_for
from student_twin.evaluation.metrics import evaluate, expected_calibration_error
from student_twin.evaluation.negative_controls import (
    leakage_verdict,
    permute_context_labels,
    permute_student_identity,
    permute_time,
)
from student_twin.evaluation.splits import forward_chained_split
from student_twin.models.baselines import run_baseline_ladder
from student_twin.models.readout import HazardReadout, build_person_period
from student_twin.simulation import Intervention, InterventionScenario, simulate_forward


@pytest.fixture(scope="module")
def filtered(twin_filter, obs, ctx, params):
    setpoints = getattr(params, "student_setpoints", {})
    return twin_filter.filter_all(obs, ctx, setpoints=setpoints)


@pytest.fixture(scope="module")
def pp(filtered, small_data, params, ctx):
    return build_person_period(filtered, small_data.outcomes, params, ctx)


# --------------------------------------------------------- person-period ---

def test_person_period_stops_at_event(pp, small_data):
    """Weeks after withdrawal do not exist. They are not zeros."""
    out = small_data.outcomes.df.set_index("student_id")
    for sid, grp in pp.groupby("student_id"):
        rec = out.loc[sid]
        if bool(rec["event_observed"]):
            assert grp["t"].max() <= float(rec["event_week"])


def test_exactly_one_event_row_per_withdrawer(pp, small_data):
    out = small_data.outcomes.df.set_index("student_id")
    for sid, grp in pp.groupby("student_id"):
        expected = 1 if bool(out.loc[sid]["event_observed"]) else 0
        assert int(grp["y"].sum()) == expected


def test_censored_students_have_no_positive_rows(pp, small_data):
    out = small_data.outcomes.df
    censored = set(out[~out["event_observed"]]["student_id"])
    assert pp[pp["student_id"].isin(censored)]["y"].sum() == 0


# ---------------------------------------------------------------- splits ---

def test_forward_chained_split_has_no_week_overlap(pp):
    tr, te = forward_chained_split(pp, 5)
    assert tr["t"].max() <= 5 < te["t"].min()


# --------------------------------------------------------------- readout ---

def test_readout_is_separable_from_state(pp, params):
    """Prediction is a byproduct of state: the readout holds no state of its own."""
    tr, te = forward_chained_split(pp, 5)
    r = HazardReadout.fit(tr, params)
    p = r.hazard(te)
    assert len(p) == len(te)
    assert np.all((p >= 0) & (p <= 1))
    assert all(f.startswith("z_") or f in params.context_covariates for f in r.feature_names)


def test_readout_consumes_only_state_and_context(pp, params, feats):
    """It must be impossible for a tier-1 feature to sneak into the readout."""
    tr, _ = forward_chained_split(pp, 5)
    r = HazardReadout.fit(tr, params)
    tier1_names = set(feats.columns) - {"student_id", "context_id", "t"}
    assert not (set(r.feature_names) & tier1_names)


def test_cumulative_risk_is_monotone(pp, params):
    tr, _ = forward_chained_split(pp, 5)
    r = HazardReadout.fit(tr, params)
    cr = r.cumulative_risk(pp)
    for _, grp in cr.groupby("student_id"):
        v = grp.sort_values("t")["cum_risk"].to_numpy()
        assert np.all(np.diff(v) >= -1e-9), "cumulative risk must not decrease"


# -------------------------------------------------------------- baselines ---

def test_baseline_ladder_runs_and_is_complete(pp, feats):
    tr, te = forward_chained_split(pp, 5)
    res = run_baseline_ladder(tr, te, feats, seed=0)
    assert {r.name for r in res} == {"majority", "prior_assessment", "rolling_features", "gbm"}
    for r in res:
        assert len(r.predictions) == len(r.y_true)
        assert np.all((r.predictions >= 0) & (r.predictions <= 1))


def test_majority_baseline_has_no_discrimination(pp, feats):
    tr, te = forward_chained_split(pp, 5)
    maj = next(r for r in run_baseline_ladder(tr, te, feats) if r.name == "majority")
    assert len(np.unique(maj.predictions)) == 1


# ---------------------------------------------------------------- metrics ---

def test_ece_near_zero_for_a_genuinely_calibrated_forecast():
    """Calibrated means observed frequency matches the predicted probability.

    Drawing y ~ Bernoulli(p) makes that true by construction, so ECE must be
    small. (Predicting 0.95 for outcomes that always occur is *not* calibrated -
    it has a real 0.05 gap, which an earlier version of this test wrongly
    expected to be zero.)
    """
    rng = np.random.default_rng(0)
    p = rng.uniform(0.05, 0.95, size=20_000)
    y = (rng.random(20_000) < p).astype(int)
    assert expected_calibration_error(y, p, 10) < 0.02


def test_ece_detects_a_miscalibrated_forecast():
    rng = np.random.default_rng(1)
    p_true = rng.uniform(0.05, 0.95, size=20_000)
    y = (rng.random(20_000) < p_true).astype(int)
    overconfident = np.clip(p_true * 1.8, 0, 1)
    assert expected_calibration_error(y, overconfident, 10) > 0.10


def test_auc_undefined_with_one_class_is_nan_not_imputed():
    m = evaluate("x", np.zeros(10, dtype=int), np.full(10, 0.3))
    assert np.isnan(m.auc), "a missing metric must be NaN, never silently filled"


# ------------------------------------------------------------- simulation ---

def test_simulation_produces_a_distribution(filtered, params, config):
    traj = next(iter(filtered.values()))
    theta = np.zeros(params.n_dims)
    sim = simulate_forward(
        traj.current, theta, params, InterventionScenario.baseline(),
        horizon=5, n_particles=200, rng=rng_for(config, "test"),
    )
    assert sim.states.shape == (200, 5, params.n_dims)
    assert sim.states[:, 0, 0].std() > 0, "a point forecast is not a distribution"


def test_simulation_uncertainty_grows_with_horizon(filtered, params, config):
    traj = next(iter(filtered.values()))
    sim = simulate_forward(
        traj.current, np.zeros(params.n_dims), params, InterventionScenario.baseline(),
        horizon=8, n_particles=400, rng=rng_for(config, "test2"),
    )
    first, last = sim.states[:, 0, 0].std(), sim.states[:, -1, 0].std()
    assert last > first, "process noise must accumulate over the horizon"


def test_simulation_is_reproducible_under_a_fixed_seed(filtered, params, config):
    traj = next(iter(filtered.values()))
    kw = dict(horizon=4, n_particles=100)
    a = simulate_forward(traj.current, np.zeros(params.n_dims), params,
                         InterventionScenario.baseline(), rng=rng_for(config, "fix"), **kw)
    b = simulate_forward(traj.current, np.zeros(params.n_dims), params,
                         InterventionScenario.baseline(), rng=rng_for(config, "fix"), **kw)
    assert np.allclose(a.states, b.states)


def test_baseline_scenario_is_not_flagged_counterfactual():
    assert InterventionScenario.baseline().is_counterfactual is False


def test_every_scenario_carries_a_provenance_string(filtered, params, config):
    traj = next(iter(filtered.values()))
    scen = InterventionScenario("boost", (Intervention("engagement_support", 1.0),))
    sim = simulate_forward(traj.current, np.zeros(params.n_dims), params, scen,
                           horizon=3, n_particles=50, rng=rng_for(config, "prov"))
    text = sim.provenance()
    assert "MODEL-GENERATED" in text
    assert "assumed transition dynamics" in text
    assert "SYNTHETIC" in text, "synthetic provenance must propagate to every artefact"


def test_intervention_shifts_the_simulated_trajectory(filtered, params, config):
    traj = next(iter(filtered.values()))
    theta = np.zeros(params.n_dims)
    kw = dict(horizon=6, n_particles=400)
    base = simulate_forward(traj.current, theta, params, InterventionScenario.baseline(),
                            rng=rng_for(config, "s"), **kw)
    scen = InterventionScenario("boost", (Intervention("engagement_support", 1.5),))
    alt = simulate_forward(traj.current, theta, params, scen, rng=rng_for(config, "s"), **kw)
    assert alt.states[:, -1, 0].mean() > base.states[:, -1, 0].mean()


def test_intervention_window_is_respected():
    scen = InterventionScenario("late", (Intervention("engagement_support", 1.0, start_week=3),))
    assert np.allclose(scen.vector_at(0), 0.0)
    assert scen.vector_at(3)[0] == 1.0


def test_unknown_intervention_rejected():
    with pytest.raises(ValueError, match="unknown intervention"):
        Intervention("free_pizza")


# ------------------------------------------------------ negative controls ---

def test_permute_time_preserves_within_student_mean(pp):
    """Documents exactly why this control is not a leakage test."""
    a = pp.groupby("student_id")["z_engagement"].mean()
    b = permute_time(pp, seed=1).groupby("student_id")["z_engagement"].mean()
    assert np.allclose(a.sort_index().to_numpy(), b.sort_index().to_numpy())


def test_permute_student_identity_preserves_event_count(pp):
    out = permute_student_identity(pp, seed=1)
    assert out.groupby("student_id")["y"].max().sum() == pp.groupby("student_id")["y"].max().sum()


def test_permute_context_labels_leaves_state_untouched(pp):
    out = permute_context_labels(pp, seed=1)
    assert np.allclose(out["z_engagement"].to_numpy(), pp["z_engagement"].to_numpy())


def test_leakage_verdict_flags_a_concerning_leakage_test():
    from student_twin.evaluation.negative_controls import NegativeControlResult

    bad = NegativeControlResult("permute_student_identity", "x", 0.9, 0.8, "SURVIVED",
                                True, True, "leak")
    assert "LEAKAGE SUSPECTED" in leakage_verdict([bad])
