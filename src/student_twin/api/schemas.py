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

from pydantic import BaseModel, Field


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


class ProfileOut(BaseModel):
    profile_id: str
    created_at: str
    updated_at: str
    display_name: str | None = None
    consent: bool
    observations: int = Field(
        description="Always 0. No ingestion path for personal observations exists.")
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
