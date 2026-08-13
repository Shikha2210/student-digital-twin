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


def test_grid_is_dense_silence_is_observed(feats):
    """A student with no events in a week still gets a row: silence is a datum."""
    counts = feats.groupby("student_id")["t"].agg(["min", "count"])
    assert (counts["min"] == 0).all()
    assert counts["count"].nunique() == 1, "every student must span the same week grid"


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
