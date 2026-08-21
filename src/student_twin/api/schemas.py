"""Response and request models  -  the data contract, in code.

docs/DATA_CONTRACT.md describes these in prose. This file is the version
the machine checks, so the two cannot drift: FastAPI validates every
response against these models and raises rather than shipping a payload
that does not match.

Why pydantic here when docs/architecture.md rejected it. The rejection was
specific and remains correct: pandas frames, not per-row objects, are the
transport type INSIDE the pipeline, because OULAD's clickstream is 10.6M
rows and instantiating an object per row would be absurd. Validating a
few dozen fields at an HTTP boundary is a different job, and it is the one
job pydantic is unambiguously right for. The decision is recorded in
docs/architecture.md.

Every field that could be mistaken for an observation carries its
provenance in the model itself, not in a comment.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from ..daily.vocab import (
    ACTIVITY_CATEGORIES,
    ACTIVITY_STATUSES,
    MAX_DETAIL_CHARS,
    MAX_REFLECTION_CHARS,
    MAX_TITLE_CHARS,
    REFLECTION_PROMPTS,
    DailyValueError,
    check_metric,
)


# ---------------------------------------------------------------- provenance

class Provenance(BaseModel):
    """Where a number came from. Attached to every payload that carries one."""

    run_id: str
    dataset: str
    synthetic: bool = Field(description="True if no real student is described here.")
    seed: int
    model_version: str
    code_revision: str | None = None
    inference_method: str
    created_at: str
    note: str


class RunSummary(BaseModel):
    run_id: str
    created_at: str
    dataset: str
    synthetic: bool
    seed: int
    model_version: str
    code_revision: str | None = None
    inference_method: str
    n_students: int
    n_person_periods: int
    n_events: int
    notes: str | None = None


class RunDetail(RunSummary):
    n_dims: int
    dim_names: list[str]
    config: dict[str, Any]
    params: dict[str, Any] | None = None
    coverage: dict[str, list[str]]


# ------------------------------------------------------------------ students

class StudentSummary(BaseModel):
    student_id: str
    context_id: str
    n_weeks: int
    event_observed: bool
    event_week: int | None = None


class StudentPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[StudentSummary]


# --------------------------------------------------------------------- state

class StateSeries(BaseModel):
    """One latent dimension over time. INFERRED, never observed."""

    dim_name: str
    t: list[int]
    mean: list[float]
    sd: list[float] = Field(description="Marginal posterior SD. Multiply by 1.96 for 95%.")
    method: str = Field(description="InferenceMethod that produced these values.")


class BaselineEstimate(BaseModel):
    """Empirical-Bayes personal set point. A point estimate with no interval.

    The two-stage estimator does not produce a credible interval for theta.
    The field is absent rather than null-and-plausible.
    """

    dim_name: str
    theta: float
    shrinkage_k: float
    context_mean: float
    n_obs: int


class HazardPoint(BaseModel):
    t: int
    hazard: float = Field(ge=0.0, le=1.0)
    cum_risk: float = Field(ge=0.0, le=1.0)
    y: int = Field(description="1 if the modelled event occurred in this week.")


class WeekObservations(BaseModel):
    t: int
    channels: dict[str, float] = Field(
        description="Canonical channels actually observed. A missing key means "
                    "the dataset does not carry that channel, not zero.")
    features: dict[str, float]


class AttributionComponent(BaseModel):
    channel: str
    contribution: float
    observed_value: float | None = None


class AttributionStep(BaseModel):
    """First-order decomposition of one prior-to-posterior move.

    `residual` is the higher-order term the decomposition cannot assign.
    It is never folded into the components to make them sum to the shift.
    """

    t: int
    dim_name: str
    prior_mean: float = Field(
        description="PREDICT step: where the transition put the state before "
                    "this week's evidence was folded in.")
    prior_sd: float | None = Field(
        default=None,
        description="SD of the one-step-ahead prior, from P_pred = F P F' + Q. "
                    "Null for runs ingested before this field existed.")
    posterior_mean: float
    posterior_sd: float | None = None
    shift: float
    residual: float
    components: list[AttributionComponent]


# ----------------------------------------------------------------- forecasts

class ForecastQuantiles(BaseModel):
    dim_name: str
    h: list[int]
    t: list[int]
    q05: list[float]
    q50: list[float]
    q95: list[float]
    mean: list[float]


class ScenarioForecast(BaseModel):
    """MODEL-GENERATED. Not a prediction and not a causal estimate."""

    scenario_id: str
    label: str
    interventions: list[dict[str, Any]]
    is_counterfactual: bool
    horizon: int
    n_particles: int
    quantiles: list[ForecastQuantiles]
    cum_risk: list[float]
    paths: list[list[float]] = Field(
        default_factory=list,
        description="Individual simulated particle paths for the first dimension. "
                    "Real trajectories, not interpolation between quantiles.")
    disclaimer: str


# ------------------------------------------------------------- composite VIEW

class OwnDistribution(BaseModel):
    """Descriptive statistics OF THE INFERRED STATES, not of raw observations."""

    dim_name: str
    mean: float
    sd: float
    n: int
    weeks_below_theta: int
    longest_run_below: int
    current_run_below: int


class TwinPayload(BaseModel):
    """Everything one dashboard needs for one student, in one request.

    Deliberately composite. Six round trips to paint one screen is a worse
    contract than one call whose shape is documented and validated.
    """

    provenance: Provenance
    student: StudentSummary
    dim_names: list[str]
    state: list[StateSeries]
    baseline: list[BaselineEstimate]
    hazard: list[HazardPoint]
    observations: list[WeekObservations]
    attribution: list[AttributionStep]
    scenarios: list[ScenarioForecast]
    own_distribution: list[OwnDistribution]
    cohort_theta: list[float] = Field(
        description="Fitted set points across the cohort, for positional context.")


class CohortPoint(BaseModel):
    student_id: str
    mean_state: float
    theta: float
    last_state: float


class ContrastStudent(BaseModel):
    """One half of the landing page's central comparison."""

    student_id: str
    theta: float
    dim_name: str
    t: list[int]
    mean: list[float]
    sd: list[float]


class ContrastPair(BaseModel):
    """Two real students whose fitted set points genuinely differ.

    Chosen from stored baselines rather than picked for narrative
    convenience: the argument only holds if the data supplies the pair.
    """

    provenance: Provenance
    high: ContrastStudent
    low: ContrastStudent


class MetricRow(BaseModel):
    model_name: str
    auc: float | None = None
    brier: float | None = None
    ece: float | None = None
    n: int
    positives: int


class ControlRow(BaseModel):
    control: str
    verdict: Literal["COLLAPSED", "SURVIVED", "UNDEFINED"]
    auc: float | None = None
    is_leakage_test: bool


class CapabilityTestRow(BaseModel):
    test_id: str
    name: str
    passed: bool
    statistic: float | None = None
    threshold: float | None = None
    detail: str | None = None


class EvaluationPayload(BaseModel):
    provenance: Provenance
    metrics: list[MetricRow]
    negative_controls: list[ControlRow]
    capability_tests: list[CapabilityTestRow]
    coverage: dict[str, list[str]]
    not_implemented: list[str] = Field(
        description="Capability tests that have never run. Absent is not passed.")


# ------------------------------------------------------------------ profiles

class ProfileCreate(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    consent: bool = False
    payload: dict[str, Any] = Field(default_factory=dict)
    term_start: str | None = Field(
        default=None, pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="First day of the study period. The anchor that turns a "
                    "calendar date into 'week N'. Optional: when it is absent "
                    "the Monday of the earliest recorded day is used instead, "
                    "and the timeline says the anchor was inferred rather than "
                    "quietly presenting an invented week 1.")


class ProfileOut(BaseModel):
    profile_id: str
    created_at: str
    updated_at: str
    display_name: str | None = None
    consent: bool
    term_start: str | None = None
    observations: int = Field(
        description="Weekly behavioural observations fed to the inference model. "
                    "Always 0: no ingestion path for personal observations "
                    "exists. Daily records are a different thing entirely and "
                    "are counted by `days_recorded`.")
    days_recorded: int = Field(
        default=0,
        description="Day records this profile owns. RAW student-entered history, "
                    "persisted and aggregated, consumed by no model.")
    payload: dict[str, Any]
    model_input: bool = Field(
        default=False,
        description="Whether any stored answer is used by the inference model. "
                    "False, and it is a field rather than a footnote.")


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    database: bool
    migrations_applied: int
    runs: int
    latest_run_id: str | None = None
    model_version: str


class ErrorOut(BaseModel):
    error: str
    detail: str
    hint: str | None = None


# ================================================================
# DAILY RECORDS
# ----------------------------------------------------------------
# The one part of this contract that carries RAW input rather than
# model output, and the models below are built so a consumer cannot
# lose track of which it is holding.
#
#   raw       what the student typed. `DayDetail.activities`,
#             `.observations`, `.reflections`.
#   derived   arithmetic over the raw rows, computed on read by
#             student_twin.daily.aggregate. `WeekRollup`. Carries `n`
#             and coverage counts so a partial total cannot read as a
#             complete one.
#   model     absent from every model here, deliberately. The field
#             `model_input: false` says so on the payload rather than
#             in a document nobody opens.
#
# Optionality is meaningful throughout. `observations` holds only the
# metrics that were recorded; a missing key means NOT RECORDED and
# there is no default that could be mistaken for a value. That is the
# same rule the `observations` table follows in the schema, carried
# out to the wire.
# ================================================================

class ActivityBase(BaseModel):
    """One thing a student did. Raw input, never inferred."""

    title: str = Field(min_length=1, max_length=MAX_TITLE_CHARS)
    category: Literal[ACTIVITY_CATEGORIES] = Field(  # type: ignore[valid-type]
        description="Closed vocabulary, mirrored by a CHECK constraint. "
                    "Free text here would become forty spellings of 'studying'.")
    detail: str | None = Field(default=None, max_length=MAX_DETAIL_CHARS)
    subject: str | None = Field(
        default=None, max_length=120,
        description="Course, module or topic. Free text: it is the student's "
                    "own vocabulary and nothing aggregates across it.")
    start_time: str | None = Field(
        default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
        description="24-hour HH:MM. Null means the student did not record a "
                    "clock time, which is most days logged from memory.")
    end_time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    minutes: int | None = Field(
        default=None, ge=1, le=1440,
        description="Duration. Null means UNKNOWN and is never coerced to 0 - "
                    "a zero would be counted in a weekly total as if it were a "
                    "measurement.")
    importance: int | None = Field(default=None, ge=1, le=5)
    status: Literal[ACTIVITY_STATUSES] | None = None  # type: ignore[valid-type]

    @model_validator(mode="after")
    def _times_and_duration_agree(self) -> "ActivityBase":
        """Derive `minutes` from the clock when both ends are known.

        Deriving rather than requiring: a student who wrote 09:00-10:30
        should not have to also type 90. When both a range and an explicit
        duration arrive, the explicit one is kept - it is what the person
        asserted, and silently overwriting it would discard the more
        direct statement.

        An end before the start is rejected instead of being wrapped past
        midnight. A day boundary crossing is a real thing that happens,
        and guessing which of the two readings was meant would put an
        invented eleven-hour study session in a weekly total.
        """
        if self.start_time and self.end_time:
            sh, sm = (int(x) for x in self.start_time.split(":"))
            eh, em = (int(x) for x in self.end_time.split(":"))
            span = (eh * 60 + em) - (sh * 60 + sm)
            if span <= 0:
                raise ValueError(
                    "end_time must be later than start_time on the same day; "
                    "record an activity that runs past midnight as two entries")
            if self.minutes is None:
                self.minutes = span
        elif self.end_time and not self.start_time:
            raise ValueError("end_time without start_time does not describe a span")
        return self


class ActivityCreate(ActivityBase):
    pass


class ActivityUpdate(ActivityBase):
    """A full replacement of one activity. Every field is resent.

    PATCH-style partial updates are not offered: the day panel edits a
    whole row in a form and sends it back, and a partial-update path
    would exist only to let a future caller clear a field by omission
    without meaning to.
    """


class ActivityOut(ActivityBase):
    activity_id: str
    day_id: str
    seq: int = Field(description="Stable display order within the day.")
    source: str = Field(
        description="Who wrote the row: student | system | import | other. "
                    "Only 'student' has a writer today.")
    created_at: str
    updated_at: str


class DayContent(BaseModel):
    """The structured and written parts of a day, as a complete set.

    A PUT of this object REPLACES what is stored, so an omitted metric is
    a cleared metric. That is the behaviour a form needs: a student who
    deletes their stress rating and saves must not find it still there.
    """

    observations: dict[str, float] = Field(
        default_factory=dict,
        description="Recorded metrics only. A missing key means NOT RECORDED. "
                    "Ranges are enforced per metric: 1-5 for the scales, "
                    "0-24 for sleep_hours. See GET /api/daily/vocabulary.")
    reflections: dict[str, str] = Field(
        default_factory=dict,
        description="Answered prompts only. Blank answers are dropped rather "
                    "than stored, so 'unanswered' and 'answered with nothing' "
                    "stay distinguishable.")

    @field_validator("observations")
    @classmethod
    def _metrics_are_known_and_in_range(cls, v: dict[str, float]) -> dict[str, float]:
        try:
            return {m: check_metric(m, val) for m, val in v.items()}
        except DailyValueError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("reflections")
    @classmethod
    def _prompts_are_known(cls, v: dict[str, str]) -> dict[str, str]:
        for prompt, body in v.items():
            if prompt not in REFLECTION_PROMPTS:
                raise ValueError(
                    f"unknown reflection prompt {prompt!r}. Known prompts: "
                    f"{', '.join(REFLECTION_PROMPTS)}")
            if len(body) > MAX_REFLECTION_CHARS:
                raise ValueError(
                    f"{prompt} is longer than {MAX_REFLECTION_CHARS} characters")
        return v


class DayCreate(DayContent):
    """Open a day, optionally with content and activities already in it."""

    date: str = Field(
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="ISO-8601 calendar date. The week is DERIVED from it "
                    "server-side and is never accepted from a client.")
    activities: list[ActivityCreate] = Field(default_factory=list)


class DayUpdate(DayContent):
    """Replace a day's metrics and prose. Activities are their own routes.

    Activities are excluded on purpose: they have ids, they are edited one
    at a time, and folding them into a whole-day replace would mean every
    save re-created every row and invalidated every activity_id the client
    was holding.
    """


class DayDetail(BaseModel):
    """One day, complete. RAW - nothing here was inferred or estimated."""

    day_id: str
    profile_id: str
    date: str
    week: int = Field(description="Study week, derived from date and term_start.")
    day_of_week: int = Field(ge=1, le=7, description="ISO: 1 = Monday, 7 = Sunday.")
    source: str
    created_at: str
    updated_at: str
    activities: list[ActivityOut]
    observations: dict[str, float]
    reflections: dict[str, str]
    model_input: bool = Field(
        default=False,
        description="Whether any of this reaches the inference model. FALSE. "
                    "Daily data is persisted, aggregated and displayed; the "
                    "state filter consumes weekly behavioural channels from a "
                    "pipeline run and nothing else. A field, not a footnote.")


class DaySlot(BaseModel):
    """One of the seven slots in a week view, recorded or not.

    A slot with `recorded: false` carries no counts and no metrics - not
    zeros. The week view renders it as 'No data' with an add action, which
    is the only honest rendering of a day that was never opened.
    """

    date: str
    day_of_week: int = Field(ge=1, le=7)
    weekday: str = Field(description="Monday ... Sunday, for direct display.")
    recorded: bool
    day_id: str | None = None
    n_activities: int = 0
    n_metrics: int = 0
    n_reflections: int = 0
    is_future: bool = Field(
        default=False,
        description="The date has not happened yet in the server's timezone. "
                    "The UI offers no 'add' action for it, because a day that "
                    "has not occurred cannot be reported on.")


class MetricSummaryOut(BaseModel):
    """DERIVED. A descriptive statistic over recorded days, not an estimate."""

    metric: str
    mean: float
    min: float
    max: float
    n: int = Field(
        description="Days in the week that carry this metric. Travels with the "
                    "mean so an average over one day cannot read as a weekly figure.")


class CategoryTotalOut(BaseModel):
    """DERIVED. Counts and logged minutes for one activity category."""

    category: str
    n_activities: int
    minutes: int
    without_duration: int = Field(
        description="Activities in this category with no recorded duration, so "
                    "`minutes` is visibly a partial sum rather than a total.")


class WeekRollupOut(BaseModel):
    """DERIVED weekly summary of raw daily rows.

    Not a model output, not comparable to `twin_states`, and never
    plotted against a latent trajectory as though the two were the same
    kind of quantity.
    """

    week: int
    start_date: str
    end_date: str
    days_recorded: int
    days_with_content: int = Field(
        description="Days that hold at least one activity, metric or answer. "
                    "A day can be opened and left empty.")
    n_activities: int
    minutes_logged: int
    activities_without_duration: int
    n_reflections: int
    by_category: list[CategoryTotalOut]
    metrics: list[MetricSummaryOut]


class WeekDetail(BaseModel):
    """One study week: seven slots, the days behind them, and the rollup."""

    profile_id: str
    week: int
    start_date: str
    end_date: str
    term_start: str
    term_start_declared: bool = Field(
        description="False when the anchor was inferred from the earliest "
                    "recorded day rather than declared by the student. Week "
                    "numbers move if they later declare one, and the UI says so.")
    slots: list[DaySlot]
    days: list[DayDetail]
    rollup: WeekRollupOut
    derived: bool = Field(
        default=True,
        description="`rollup` is arithmetic over the rows in `days`, computed "
                    "on read. Nothing in this payload is a model quantity.")


class TimelineWeek(BaseModel):
    week: int
    start_date: str
    end_date: str
    days_recorded: int
    n_activities: int
    has_data: bool


class DailyTimeline(BaseModel):
    """Every week this student has, plus the shape of the history.

    `weeks` spans week 1 to the last week that holds data - or to the
    current week when that is later, because a student needs somewhere to
    put today. It is NOT padded to twenty, or to any other fixed number:
    how long a history is, is a property of the history.
    """

    profile_id: str
    term_start: str | None = None
    term_start_declared: bool
    n_weeks: int = Field(description="Length of `weeks`. Derived, never a constant.")
    weeks: list[TimelineWeek]
    days_recorded: int
    first_date: str | None = None
    last_date: str | None = None
    today: str = Field(description="The server's date, so the UI agrees with "
                                   "the validation that rejects future days.")
    rollups: list[WeekRollupOut]
    model_input: bool = Field(
        default=False,
        description="False. See DayDetail.model_input.")


class VocabularyItem(BaseModel):
    value: str
    label: str


class MetricSpec(BaseModel):
    value: str
    label: str
    min: float
    max: float
    unit: str
    step: float


class DailyVocabulary(BaseModel):
    """The closed vocabularies, served so the client cannot keep its own copy.

    A form whose options are typed out again in JavaScript drifts from the
    CHECK constraint the first time either changes, and the failure shows
    up as a 422 the user cannot act on.
    """

    activity_categories: list[VocabularyItem]
    activity_statuses: list[VocabularyItem]
    metrics: list[MetricSpec]
    reflection_prompts: list[VocabularyItem]
    sources: list[str]
