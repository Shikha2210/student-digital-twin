"""Adapter contract and OULAD structural behaviour."""

from __future__ import annotations

import pytest

from student_twin.adapters import REGISTRY, OULADAdapter, RawDataMissing, get_adapter
from student_twin.schema import CanonicalType


def test_registry_exposes_both_adapters():
    assert {"oulad", "synthetic"} <= set(REGISTRY)


def test_synthetic_is_deterministic():
    a = get_adapter("synthetic", n_students=20, n_weeks=8, seed=3).load()
    b = get_adapter("synthetic", n_students=20, n_weeks=8, seed=3).load()
    assert len(a.events) == len(b.events)
    assert a.outcomes.base_rate == b.outcomes.base_rate


def test_synthetic_declares_lifestyle_unavailable():
    """The proposal wants lifestyle and self-report channels; no adapter has them."""
    cov = get_adapter("synthetic").coverage()
    assert CanonicalType.ACTIVITY_LOG.value in cov.unavailable
    assert CanonicalType.PERCEIVED_LOAD.value in cov.unavailable


def test_oulad_declares_coverage_without_data_present():
    """Coverage must be answerable before paying the load cost."""
    cov = OULADAdapter(root="does/not/exist").coverage()
    assert CanonicalType.CONTENT_VIEW.value in cov.available
    assert CanonicalType.PERCEIVED_LOAD.value in cov.unavailable
    assert "granularity" in cov.notes


def test_oulad_refuses_to_invent_data():
    """Missing raw data must raise with placement instructions, never fall back."""
    ad = OULADAdapter(root="does/not/exist")
    assert ad.is_available() is False
    with pytest.raises(RawDataMissing) as exc:
        ad.load()
    msg = str(exc.value)
    assert "studentVle.csv" in msg
    assert "data/README.md" in msg


def test_oulad_discipline_map_matches_documentation():
    from student_twin.adapters.oulad import DISCIPLINE

    social = {m for m, d in DISCIPLINE.items() if d == "social_science"}
    stem = {m for m, d in DISCIPLINE.items() if d == "stem"}
    assert social == {"AAA", "BBB", "GGG"}
    assert stem == {"CCC", "DDD", "EEE", "FFF"}


def test_outcomes_carry_censoring(small_data):
    df = small_data.outcomes.df
    assert set(["event_week", "event_observed"]) <= set(df.columns)
    completers = df[~df["event_observed"]]
    assert completers["event_week"].isna().all(), "censored students must have no event week"
