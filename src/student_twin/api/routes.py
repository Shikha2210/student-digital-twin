"""HTTP routes.

Thin by design: parse, delegate to `services`, serialise. Any route long
enough to contain a branch on model semantics belongs in the service
layer, where it is testable without a client.

Every response model is declared, so FastAPI validates the payload on the
way out. A route that starts returning a shape the contract does not
describe fails loudly here rather than silently in the browser.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from .. import __version__ as MODEL_VERSION
from ..store.repository import Repository
from . import services
from .deps import get_repo, get_settings_dep, resolve_run
from .schemas import (
    CapabilityTestRow,
    CohortPoint,
    ContrastPair,
    ControlRow,
    EvaluationPayload,
    Health,
    MetricRow,
    ProfileCreate,
    ProfileOut,
    RunDetail,
    RunSummary,
    ScenarioForecast,
    StateSeries,
    StudentPage,
    StudentSummary,
    TwinPayload,
)
from .settings import Settings

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------- meta

@router.get("/health", response_model=Health, tags=["meta"],
            summary="Liveness plus what the database actually contains")
def health(repo: Repository = Depends(get_repo)) -> Health:
    try:
        n_runs = int(repo.db.scalar("SELECT COUNT(*) FROM model_runs") or 0)
        n_mig = int(repo.db.scalar("SELECT COUNT(*) FROM schema_migrations") or 0)
        latest = repo.latest_run_id()
        db_ok = True
    except Exception:
        n_runs, n_mig, latest, db_ok = 0, 0, None, False
    return Health(
        status="ok" if db_ok and n_runs else "degraded",
        database=db_ok, migrations_applied=n_mig, runs=n_runs,
        latest_run_id=latest, model_version=MODEL_VERSION,
    )


@router.get("/runs", response_model=list[RunSummary], tags=["meta"],
            summary="Model runs, newest first")
def list_runs(limit: int = Query(20, ge=1, le=100),
              repo: Repository = Depends(get_repo)) -> list[RunSummary]:
    return [RunSummary(**r) for r in repo.list_runs(limit)]


@router.get("/runs/{run_id}", response_model=RunDetail, tags=["meta"],
            summary="Full manifest: config, fitted parameters, channel coverage")
def get_run(run_id: str = Path(...), repo: Repository = Depends(get_repo)) -> RunDetail:
    run = repo.run(run_id)
    if not run:
        raise HTTPException(404, detail={"error": "run_not_found",
                                         "detail": f"run {run_id!r} does not exist"})
    return RunDetail(**run, coverage=repo.coverage(run_id))


@router.get("/evaluation", response_model=EvaluationPayload, tags=["meta"],
            summary="Metrics, negative controls and capability tests for a run")
def evaluation(run_id: str = Depends(resolve_run),
               repo: Repository = Depends(get_repo)) -> EvaluationPayload:
    return EvaluationPayload(
        provenance=services.provenance_of(repo, run_id),
        metrics=[MetricRow(**m) for m in repo.metrics(run_id)],
        negative_controls=[ControlRow(**c) for c in repo.negative_controls(run_id)],
        capability_tests=[CapabilityTestRow(**t) for t in repo.capability_tests(run_id)],
        coverage=repo.coverage(run_id),
        not_implemented=services.NEVER_RUN,
    )


@router.get("/cohort", response_model=list[CohortPoint], tags=["meta"],
            summary="Per-student mean state and fitted set point")
def cohort(run_id: str = Depends(resolve_run),
           limit: int = Query(400, ge=1, le=2000),
           repo: Repository = Depends(get_repo)) -> list[CohortPoint]:
    return services.cohort_points(repo, run_id, limit)


@router.get("/contrast", response_model=ContrastPair, tags=["meta"],
            summary="Two students whose fitted set points genuinely differ")
def contrast(run_id: str = Depends(resolve_run),
             repo: Repository = Depends(get_repo)) -> ContrastPair:
    try:
        return services.contrast_pair(repo, run_id)
    except services.NotFound as exc:
        raise HTTPException(404, detail={"error": "no_contrast_pair",
                                         "detail": str(exc)}) from exc


# --------------------------------------------------------------- students

@router.get("/students", response_model=StudentPage, tags=["students"],
            summary="Paged list of students in a run")
def list_students(run_id: str = Depends(resolve_run),
                  limit: int = Query(50, ge=1, le=500),
                  offset: int = Query(0, ge=0),
                  repo: Repository = Depends(get_repo),
                  settings: Settings = Depends(get_settings_dep)) -> StudentPage:
    limit = min(limit, settings.max_page_size)
    return StudentPage(
        total=repo.count_students(run_id), limit=limit, offset=offset,
        items=[StudentSummary(**s) for s in repo.list_students(run_id, limit, offset)],
    )


@router.get("/students/demo", response_model=StudentSummary, tags=["students"],
            summary="The student the demo opens on, chosen from stored states")
def demo_student(run_id: str = Depends(resolve_run),
                 repo: Repository = Depends(get_repo)) -> StudentSummary:
    sid = repo.pick_demo_student(run_id)
    if not sid:
        raise HTTPException(404, detail={"error": "no_students",
                                         "detail": f"run {run_id!r} has no students"})
    return StudentSummary(**repo.student(run_id, sid))


@router.get("/students/{student_id}", response_model=StudentSummary, tags=["students"])
def get_student(student_id: str, run_id: str = Depends(resolve_run),
                repo: Repository = Depends(get_repo)) -> StudentSummary:
    s = repo.student(run_id, student_id)
    if not s:
        raise HTTPException(404, detail={
            "error": "student_not_found",
            "detail": f"student {student_id!r} is not in run {run_id!r}"})
    return StudentSummary(**s)


@router.get("/students/{student_id}/twin", response_model=TwinPayload, tags=["twin"],
            summary="Everything the dashboard needs for one student, in one call")
def student_twin(student_id: str, run_id: str = Depends(resolve_run),
                 repo: Repository = Depends(get_repo)) -> TwinPayload:
    try:
        return services.twin_payload(repo, run_id, student_id)
    except services.NotFound as exc:
        raise HTTPException(404, detail={"error": "not_found", "detail": str(exc)}) from exc


@router.get("/students/{student_id}/state", response_model=list[StateSeries],
            tags=["twin"], summary="Filtered latent state. INFERRED, not observed.")
def student_state(student_id: str, run_id: str = Depends(resolve_run),
                  repo: Repository = Depends(get_repo)) -> list[StateSeries]:
    rows = repo.states(run_id, student_id)
    if not rows:
        raise HTTPException(404, detail={
            "error": "no_states",
            "detail": f"no states stored for {student_id!r} in run {run_id!r}"})
    return services._series(rows, repo.run(run_id)["dim_names"])


@router.get("/students/{student_id}/forecast", response_model=list[ScenarioForecast],
            tags=["twin"], summary="Simulated futures. MODEL-GENERATED, not causal.")
def student_forecast(student_id: str, run_id: str = Depends(resolve_run),
                     repo: Repository = Depends(get_repo)) -> list[ScenarioForecast]:
    run = repo.run(run_id)
    out = services.scenario_forecasts(repo, run_id, student_id, run["dim_names"][0])
    if not out:
        raise HTTPException(404, detail={
            "error": "no_forecast",
            "detail": f"no simulated scenarios stored for {student_id!r}",
            "hint": "Re-ingest with --scenarios to generate them."})
    return out


# --------------------------------------------------------------- profiles

@router.post("/profiles", response_model=ProfileOut, status_code=201, tags=["profiles"],
             summary="Store a Twin created through onboarding")
def create_profile(body: ProfileCreate, repo: Repository = Depends(get_repo),
                   settings: Settings = Depends(get_settings_dep)) -> ProfileOut:
    if not settings.allow_profiles:
        raise HTTPException(403, detail={
            "error": "profiles_disabled",
            "detail": "STUDYTWIN_ALLOW_PROFILES is off in this deployment."})
    pid = uuid.uuid4().hex
    now = datetime.now(UTC).isoformat(timespec="seconds")
    repo.create_profile(pid, now, body.display_name, body.consent,
                        json.dumps(body.payload))
    return ProfileOut(profile_id=pid, created_at=now, updated_at=now,
                      display_name=body.display_name, consent=body.consent,
                      observations=0, payload=body.payload, model_input=False)


@router.get("/profiles/{profile_id}", response_model=ProfileOut, tags=["profiles"])
def get_profile(profile_id: str, repo: Repository = Depends(get_repo)) -> ProfileOut:
    p = repo.profile(profile_id)
    if not p:
        raise HTTPException(404, detail={"error": "profile_not_found",
                                         "detail": "no such profile"})
    return ProfileOut(**p, model_input=False)


@router.put("/profiles/{profile_id}", response_model=ProfileOut, tags=["profiles"])
def update_profile(profile_id: str, body: ProfileCreate,
                   repo: Repository = Depends(get_repo)) -> ProfileOut:
    now = datetime.now(UTC).isoformat(timespec="seconds")
    if not repo.update_profile(profile_id, now, body.display_name, body.consent,
                               json.dumps(body.payload)):
        raise HTTPException(404, detail={"error": "profile_not_found",
                                         "detail": "no such profile"})
    return ProfileOut(**repo.profile(profile_id), model_input=False)


@router.delete("/profiles/{profile_id}", status_code=204, tags=["profiles"],
               summary="Erase a profile. The only destructive route in the API.")
def delete_profile(profile_id: str, repo: Repository = Depends(get_repo)) -> None:
    if not repo.delete_profile(profile_id):
        raise HTTPException(404, detail={"error": "profile_not_found",
                                         "detail": "no such profile"})
