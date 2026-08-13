"""Canonical schema validation."""

from __future__ import annotations

import pandas as pd
import pytest

from student_twin.schema import (
    CHANNEL_OF,
    CanonicalEvent,
    CanonicalType,
    Channel,
    CoverageManifest,
    EventTable,
    SchemaError,
)


def _row(**kw):
    base = dict(
        student_id="s1", context_id="c1", t=0,
        channel="behavior", canonical_type="content_view", value=1.0,
    )
    base.update(kw)
    return pd.DataFrame([base])


def test_valid_frame_round_trips():
    tbl = EventTable(_row())
    assert len(tbl) == 1
    assert tbl.df["t"].dtype == "int32"


def test_missing_column_rejected():
    df = _row().drop(columns=["value"])
    with pytest.raises(SchemaError, match="missing required columns"):
        EventTable(df)


def test_extra_column_rejected():
    """Dataset-specific fields must not ride along inside the event table."""
    df = _row()
    df["imd_band"] = "20-30%"
    with pytest.raises(SchemaError, match="unexpected columns"):
        EventTable(df)


def test_unknown_canonical_type_rejected():
    with pytest.raises(SchemaError, match="unknown canonical_type"):
        EventTable(_row(canonical_type="tea_break"))


def test_channel_type_mismatch_rejected():
    """A score is an assessment event; declaring it behaviour is an adapter bug."""
    with pytest.raises(SchemaError, match="mismatch"):
        EventTable(_row(canonical_type="score", channel="behavior"))


def test_negative_week_rejected():
    with pytest.raises(SchemaError, match="non-negative"):
        EventTable(_row(t=-1))


def test_nan_value_rejected():
    with pytest.raises(SchemaError, match="must not be NaN"):
        EventTable(_row(value=float("nan")))


def test_event_dataclass_enforces_channel():
    with pytest.raises(SchemaError):
        CanonicalEvent("s", "c", 0, Channel.BEHAVIOR, CanonicalType.SCORE, 1.0)


def test_every_canonical_type_has_a_channel():
    assert set(CHANNEL_OF) == set(CanonicalType)


def test_coverage_manifest_must_account_for_every_type():
    with pytest.raises(SchemaError, match="does not account for"):
        CoverageManifest(
            dataset="partial",
            available=frozenset({CanonicalType.FORUM.value}),
            unavailable=frozenset(),
        )


def test_coverage_intersect():
    allt = {t.value for t in CanonicalType}
    a = CoverageManifest("a", frozenset({"forum", "score"}), frozenset(allt - {"forum", "score"}))
    b = CoverageManifest("b", frozenset({"forum"}), frozenset(allt - {"forum"}))
    assert a.intersect(b) == frozenset({"forum"})


def test_weekly_pivot_zero_fills_counts_but_not_scores():
    """Absence of clicks is a zero. Absence of a score is not a zero score."""
    tbl = EventTable(_row())
    wide = tbl.weekly_pivot()
    assert wide["forum"].iloc[0] == 0.0
    assert pd.isna(wide["score"].iloc[0])
