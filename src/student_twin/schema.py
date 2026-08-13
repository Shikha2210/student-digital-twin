"""Canonical event schema.

Everything downstream of an adapter speaks this vocabulary and nothing else. The
twin never sees an OULAD column name, which is the property that lets a second
dataset arrive as an adapter rather than a rewrite.

Design note  -  why validated frames rather than pydantic models
--------------------------------------------------------------
OULAD's clickstream is ~10.6M rows. Materialising one Python object per event is
not viable, so the schema is enforced as a *contract over a DataFrame*: required
columns, dtypes, allowed categorical values, and invariants, all checked at
construction. `CanonicalEvent` exists as a dataclass for documentation and for
building test fixtures one row at a time, not as the transport type.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Iterable

import pandas as pd


class Channel(StrEnum):
    """Top-level observation channel.

    LIFESTYLE and SELF_REPORT are declared here but supplied by no current
    adapter. They exist because the capstone proposal requires them and because
    the schema must not need changing when a survey instrument is added later.
    Every adapter must declare them unavailable rather than silently omit them.
    """

    BEHAVIOR = "behavior"
    ASSESSMENT = "assessment"
    ENROLMENT = "enrolment"
    LIFESTYLE = "lifestyle"
    SELF_REPORT = "self_report"


class CanonicalType(StrEnum):
    """Dataset-independent event type."""

    # behavior
    CONTENT_VIEW = "content_view"
    FORUM = "forum"
    QUIZ_ATTEMPT = "quiz_attempt"
    RESOURCE = "resource"
    ADMIN = "admin"
    # assessment
    SUBMISSION = "submission"
    SCORE = "score"
    # enrolment
    REGISTER = "register"
    WITHDRAW = "withdraw"
    # lifestyle / self-report  -  no adapter supplies these yet
    ACTIVITY_LOG = "activity_log"
    PERCEIVED_LOAD = "perceived_load"


CHANNEL_OF: dict[CanonicalType, Channel] = {
    CanonicalType.CONTENT_VIEW: Channel.BEHAVIOR,
    CanonicalType.FORUM: Channel.BEHAVIOR,
    CanonicalType.QUIZ_ATTEMPT: Channel.BEHAVIOR,
    CanonicalType.RESOURCE: Channel.BEHAVIOR,
    CanonicalType.ADMIN: Channel.BEHAVIOR,
    CanonicalType.SUBMISSION: Channel.ASSESSMENT,
    CanonicalType.SCORE: Channel.ASSESSMENT,
    CanonicalType.REGISTER: Channel.ENROLMENT,
    CanonicalType.WITHDRAW: Channel.ENROLMENT,
    CanonicalType.ACTIVITY_LOG: Channel.LIFESTYLE,
    CanonicalType.PERCEIVED_LOAD: Channel.SELF_REPORT,
}

BEHAVIOR_TYPES: tuple[CanonicalType, ...] = tuple(
    t for t, c in CHANNEL_OF.items() if c is Channel.BEHAVIOR
)

EVENT_COLUMNS: tuple[str, ...] = (
    "student_id",
    "context_id",
    "t",
    "channel",
    "canonical_type",
    "value",
)


@dataclass(frozen=True)
class CanonicalEvent:
    """One observation. Documentation and fixture-building type, not transport."""

    student_id: str
    context_id: str
    t: int
    channel: Channel
    canonical_type: CanonicalType
    value: float

    def __post_init__(self) -> None:
        if CHANNEL_OF[self.canonical_type] is not self.channel:
            raise SchemaError(
                f"canonical_type {self.canonical_type!r} belongs to channel "
                f"{CHANNEL_OF[self.canonical_type]!r}, not {self.channel!r}"
            )
        if self.t < 0:
            raise SchemaError(f"t must be non-negative, got {self.t}")


class SchemaError(ValueError):
    """Raised when data violates the canonical contract."""


class EventTable:
    """A validated long-format event frame.

    Construction validates; it does not coerce silently. An adapter that produces
    a malformed frame should fail loudly at the boundary rather than propagate a
    subtle error into the state model.
    """

    __slots__ = ("_df",)

    def __init__(self, df: pd.DataFrame, *, validate: bool = True) -> None:
        if validate:
            df = self._validate(df)
        self._df = df

    @staticmethod
    def _validate(df: pd.DataFrame) -> pd.DataFrame:
        missing = [c for c in EVENT_COLUMNS if c not in df.columns]
        if missing:
            raise SchemaError(f"event frame missing required columns: {missing}")

        extra = [c for c in df.columns if c not in EVENT_COLUMNS]
        if extra:
            raise SchemaError(
                f"event frame has unexpected columns {extra}. Dataset-specific fields "
                "belong in context metadata or must be mapped to a canonical type."
            )

        out = df.loc[:, list(EVENT_COLUMNS)].copy()

        bad_type = set(out["canonical_type"].astype(str)) - {t.value for t in CanonicalType}
        if bad_type:
            raise SchemaError(f"unknown canonical_type values: {sorted(bad_type)}")
        bad_chan = set(out["channel"].astype(str)) - {c.value for c in Channel}
        if bad_chan:
            raise SchemaError(f"unknown channel values: {sorted(bad_chan)}")

        # channel must agree with canonical_type; a mismatch means an adapter bug
        expected = out["canonical_type"].astype(str).map(
            {t.value: CHANNEL_OF[t].value for t in CanonicalType}
        )
        mismatch = out["channel"].astype(str) != expected
        if bool(mismatch.any()):
            first = out.loc[mismatch].iloc[0]
            raise SchemaError(
                f"channel/canonical_type mismatch, e.g. "
                f"{first['canonical_type']!r} declared as {first['channel']!r}"
            )

        out["student_id"] = out["student_id"].astype(str)
        out["context_id"] = out["context_id"].astype(str)
        out["t"] = pd.to_numeric(out["t"], errors="raise").astype("int32")
        if bool((out["t"] < 0).any()):
            raise SchemaError("t must be non-negative")
        out["value"] = pd.to_numeric(out["value"], errors="raise").astype("float64")
        if not out["value"].notna().all():
            raise SchemaError("value must not be NaN; absence is encoded by the absence of a row")

        out["channel"] = out["channel"].astype("category")
        out["canonical_type"] = out["canonical_type"].astype("category")
        return out.reset_index(drop=True)

    # -- accessors -------------------------------------------------------

    @property
    def df(self) -> pd.DataFrame:
        """The underlying frame. Treat as read-only."""
        return self._df

    def __len__(self) -> int:
        return len(self._df)

    def __repr__(self) -> str:
        n_students = self._df["student_id"].nunique() if len(self._df) else 0
        return f"EventTable(rows={len(self._df)}, students={n_students})"

    @property
    def present_types(self) -> set[str]:
        return set(self._df["canonical_type"].astype(str).unique())

    def for_student(self, student_id: str) -> pd.DataFrame:
        return self._df.loc[self._df["student_id"] == str(student_id)]

    def weekly_pivot(self, types: Iterable[CanonicalType] | None = None) -> pd.DataFrame:
        """Wide view: one row per (student, context, week), one column per type.

        Absent (student, week, type) combinations become 0 for count-like types
        and NaN for score. That asymmetry is deliberate: no clicks is a genuine
        zero, whereas no score is not a zero score.
        """
        types = tuple(types) if types is not None else tuple(CanonicalType)
        want = {t.value for t in types}
        sub = self._df[self._df["canonical_type"].astype(str).isin(want)]
        wide = (
            sub.pivot_table(
                index=["student_id", "context_id", "t"],
                columns="canonical_type",
                values="value",
                aggfunc="sum",
                observed=True,
            )
            .rename_axis(columns=None)
            .reset_index()
        )
        for t in types:
            if t.value not in wide.columns:
                # float NaN, never pd.NA: pd.NA yields an object column, and object
                # columns silently break rolling/expanding aggregation downstream.
                wide[t.value] = float("nan") if t is CanonicalType.SCORE else 0.0
        value_cols = [t.value for t in types]
        wide[value_cols] = wide[value_cols].astype("float64")
        count_like = [t.value for t in types if t is not CanonicalType.SCORE]
        wide[count_like] = wide[count_like].fillna(0.0)
        return wide.sort_values(["student_id", "t"]).reset_index(drop=True)

    @classmethod
    def from_events(cls, events: Iterable[CanonicalEvent]) -> "EventTable":
        rows = [
            {
                "student_id": e.student_id,
                "context_id": e.context_id,
                "t": e.t,
                "channel": str(e.channel),
                "canonical_type": str(e.canonical_type),
                "value": e.value,
            }
            for e in events
        ]
        return cls(pd.DataFrame(rows, columns=list(EVENT_COLUMNS)))

    @classmethod
    def empty(cls) -> "EventTable":
        return cls(pd.DataFrame({c: [] for c in EVENT_COLUMNS}))


@dataclass(frozen=True)
class ContextMetadata:
    """Tier-2 descriptors for one course-presentation.

    These condition the model. They are never memorised as identity: `context_id`
    itself is not a model input.
    """

    context_id: str
    n_weeks: int
    modality: str            # distance | blended | residential
    discipline: str          # stem | social_science | other
    cohort_size: int
    assessment_density: float          # assessments per week
    has_high_stakes_exam: bool = False
    mean_credit_load: float = float("nan")
    observed_base_rate: float = float("nan")   # filled from outcomes, not asserted
    source_dataset: str = "unknown"

    def as_covariates(self) -> dict[str, float]:
        """Numeric tier-2 vector. Identity fields are deliberately excluded."""
        return {
            "assessment_density": float(self.assessment_density),
            "has_high_stakes_exam": float(self.has_high_stakes_exam),
            "course_length": float(self.n_weeks),
            "log_cohort_size": math.log1p(self.cohort_size),
            "is_distance": float(self.modality == "distance"),
            "is_stem": float(self.discipline == "stem"),
        }


@dataclass(frozen=True)
class CoverageManifest:
    """What an adapter can and cannot supply.

    Gate 1 §03 requires this. Without it, a transfer experiment cannot separate
    "this context differs" from "this dataset lacks a forum channel", and every
    cross-dataset result is confounded by instrumentation.
    """

    dataset: str
    available: frozenset[str]
    unavailable: frozenset[str]
    notes: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        all_types = {t.value for t in CanonicalType}
        declared = set(self.available) | set(self.unavailable)
        if declared != all_types:
            missing = all_types - declared
            raise SchemaError(
                f"coverage manifest for {self.dataset!r} does not account for "
                f"{sorted(missing)}. Every canonical type must be explicitly "
                "declared available or unavailable."
            )
        if set(self.available) & set(self.unavailable):
            raise SchemaError("a type cannot be both available and unavailable")

    def supports(self, t: CanonicalType | str) -> bool:
        return str(t) in self.available

    def intersect(self, other: "CoverageManifest") -> frozenset[str]:
        """Channels common to two datasets  -  the only fair basis for transfer."""
        return frozenset(self.available & other.available)


@dataclass(frozen=True)
class OutcomeTable:
    """Person-level survival outcome.

    `event_week` is the week withdrawal was recorded; `event_observed` is False
    for students who completed or were censored at course end.
    """

    df: pd.DataFrame

    REQUIRED = ("student_id", "context_id", "event_week", "event_observed", "final_result")

    def __post_init__(self) -> None:
        missing = [c for c in self.REQUIRED if c not in self.df.columns]
        if missing:
            raise SchemaError(f"outcome frame missing columns: {missing}")

    @property
    def base_rate(self) -> float:
        return float(self.df["event_observed"].mean()) if len(self.df) else float("nan")


@dataclass(frozen=True)
class AdapterOutput:
    """Everything an adapter returns. The twin consumes only this."""

    events: EventTable
    contexts: dict[str, ContextMetadata]
    outcomes: OutcomeTable
    coverage: CoverageManifest

    def summary(self) -> dict[str, object]:
        return {
            "dataset": self.coverage.dataset,
            "n_events": len(self.events),
            "n_students": int(self.events.df["student_id"].nunique()),
            "n_contexts": len(self.contexts),
            "base_rate": self.outcomes.base_rate,
            "available_types": sorted(self.coverage.available),
            "unavailable_types": sorted(self.coverage.unavailable),
        }
