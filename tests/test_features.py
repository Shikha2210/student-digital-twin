"""Feature computation, provenance, and the temporal-leak guard."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from student_twin.config import FeatureConfig
from student_twin.features import REGISTRY
from student_twin.features.tier1 import TIER1_FEATURES, build_tier1
from student_twin.schema import CanonicalEvent, CanonicalType, Channel, EventTable


def test_all_tier1_features_registered():
    for name in TIER1_FEATURES:
        assert name in REGISTRY
        assert REGISTRY[name].tier == 1


def test_tier1_features_are_all_normalised():
    """A tier-1 feature carrying a raw unit would not survive transfer."""
    for name in REGISTRY.names(tier=1):
        assert REGISTRY[name].normalisation != "none"


def test_provenance_is_answerable(feats):
    text = REGISTRY.explain("engagement_ratio")
    assert "built from" in text and "normalised" in text
    assert REGISTRY.requires_types(["submission_rate"]) == {CanonicalType.SUBMISSION.value}


def test_no_institution_specific_features_exist():
    """Tier 3 must have no builder at all - the absence is the enforcement."""
    assert REGISTRY.names(tier=3) == []


def test_grid_is_dense_within_the_at_risk_window(feats):
    """Silence is a datum; non-existence is not.

    Every student's weeks start at 0 and are contiguous - a quiet week still
    gets a row, because disengagement must be visible. But the grid stops at
    withdrawal. Extending it past that invents zero-activity weeks that never
    happened, and since withdrawal is common those fabricated zeros dominate
    the fit and teach the model "no activity means very low state" from
    students who had already left.
    """
    for sid, grp in feats.groupby("student_id"):
        weeks = sorted(grp["t"].tolist())
        assert weeks[0] == 0, f"{sid} does not start at week 0"
        assert weeks == list(range(len(weeks))), f"{sid} has a gap in its week grid"


def test_grid_stops_at_withdrawal(small_data, config):
    """The at-risk boundary comes from the WITHDRAW event, and is respected."""
    from student_twin.features.tier1 import student_horizons

    feats = build_tier1(small_data.events, config.features, n_weeks=12)
    hz = student_horizons(small_data.events, 12).set_index("student_id")["last_week"]
    last_seen = feats.groupby("student_id")["t"].max()
    for sid, last in last_seen.items():
        assert last == hz[sid], f"{sid} spans past its at-risk boundary"

    out = small_data.outcomes.df.set_index("student_id")
    withdrawers = out[out["event_observed"]]
    assert len(withdrawers) > 0, "fixture must contain withdrawals for this to be meaningful"
    for sid, rec in withdrawers.iterrows():
        assert last_seen[sid] == int(rec["event_week"])


def test_no_all_zero_weeks_after_withdrawal(small_data, config):
    """Regression guard for the bug this fix addresses.

    Before truncation, 30.5% of observation rows were fabricated post-withdrawal
    zeros, against exactly one genuine zero-activity week among at-risk rows.
    """
    from student_twin.features.tier1 import BEHAVIOR_COLS, observation_frame

    obs = observation_frame(small_data.events, n_weeks=12)
    act = obs[[c for c in BEHAVIOR_COLS if c in obs.columns]].sum(axis=1)
    zero_frac = float((act == 0).mean())
    assert zero_frac < 0.05, (
        f"{zero_frac:.1%} of at-risk weeks have zero activity; the grid is probably "
        "extending past withdrawal again"
    )


def test_engagement_ratio_does_not_use_current_week():
    """The leak guard. Changing week t's activity must not change week t's baseline.

    Two cohorts identical except for a spike at the final week: every feature at
    earlier weeks must be untouched.
    """
    def cohort(spike: float) -> EventTable:
        evs = []
        for t in range(8):
            v = spike if t == 7 else 10.0
            evs.append(
                CanonicalEvent("s1", "c1", t, Channel.BEHAVIOR, CanonicalType.CONTENT_VIEW, v)
            )
        return EventTable.from_events(evs)

    a = build_tier1(cohort(10.0), FeatureConfig(), n_weeks=8)
    b = build_tier1(cohort(500.0), FeatureConfig(), n_weeks=8)
    early_a = a[a["t"] < 7][list(TIER1_FEATURES)].to_numpy(float)
    early_b = b[b["t"] < 7][list(TIER1_FEATURES)].to_numpy(float)
    assert np.allclose(early_a, early_b), "a later week changed an earlier feature: LEAK"


def test_features_are_finite(feats):
    arr = feats[list(TIER1_FEATURES)].to_numpy(dtype=float)
    assert np.isfinite(arr).all()


def test_entropy_bounded(feats):
    e = feats["activity_entropy"]
    assert (e >= -1e-9).all() and (e <= 1.0 + 1e-9).all()


def test_inactive_streak_bounded(feats):
    s = feats["inactive_streak"]
    assert (s >= 0).all() and (s <= 1.0).all()


def test_empty_input_returns_empty_frame():
    out = build_tier1(EventTable.empty(), FeatureConfig())
    assert out.empty
    assert set(TIER1_FEATURES) <= set(out.columns)
