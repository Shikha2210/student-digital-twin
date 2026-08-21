"""HTTP routes for daily student records.

A separate module from `routes.py` because this is the API's other half:
`routes.py` serves model output and is read-only by design, while
everything here is a student writing their own history. Mixing the two in
one file would blur the boundary the architecture rests on - that model
numbers enter through `scripts/ingest_run.py` and through nothing else.
The router is included into the same `/api` router, so the URL space is
one space.

Conventions carried over unchanged from `routes.py`:

* thin routes - parse, delegate to `services`, serialise
* `response_model` on every route, so a payload that stops matching the
  contract fails here rather than in the browser
* errors are `{"error": slug, "detail": sentence, "hint": optional}`
* 404 rather than an empty success

Two conventions are specific to this half.

**Every path begins `/profiles/{profile_id}`.** There is no route that
reaches a day, an activity or a week without naming its owner, and the
repository has no method that would let one. Isolation is therefore a
property of the URL space rather than a check somebody has to remember to
write; `tests/test_api_daily.py` asserts it from both directions.

**A day is addressed by its date, not by an opaque id.** `PUT
/days/2026-08-20` is idempotent, readable in a log, and lets the client
save without first resolving an id it does not have. Activities keep ids
because a day genuinely has many of them and they are edited one at a
time.
"""

from __future__ import annotations

import sqlite3
from datetime import date as _date

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query

from ..daily import calendar as cal
from ..daily.vocab import DailyValueError, vocabulary
from ..store.repository import Repository
from . import services
from .deps import get_repo, get_settings_dep
from .schemas import (
    ActivityCreate,
    ActivityOut,
    ActivityUpdate,
    DailyTimeline,
    DailyVocabulary,
    DayCreate,
    DayDetail,
    DayUpdate,
    WeekDetail,
)
from .settings import Settings

router = APIRouter()

#: How far ahead of the anchor a week number may be asked for. Not a
#: statement about how long a course is - it is a guard so that
#: `/weeks/900000000` does not turn into a date computation that overflows
#: and a 500. The timeline reports the real number of weeks, which is
#: derived from the data and is usually far smaller than this.
MAX_WEEK = 520


def _profile_or_404(repo: Repository, profile_id: str) -> dict:
    p = repo.profile(profile_id)
    if not p:
        raise HTTPException(404, detail={
            "error": "profile_not_found",
            "detail": f"profile {profile_id!r} does not exist",
            "hint": "Create one with POST /api/profiles before recording days."})
    return p


def _guard_writes(settings: Settings) -> None:
    """Daily records ride the same switch as profiles.

    They are the same category of data - a real person's own account of
    their life - so a deployment that has turned off personal data storage
    must not still accept days. One switch rather than two, because two
    switches is how one of them ends up on by accident.
    """
    if not settings.allow_profiles:
        raise HTTPException(403, detail={
            "error": "profiles_disabled",
            "detail": "STUDYTWIN_ALLOW_PROFILES is off in this deployment, and "
                      "daily records are personal data governed by the same switch.",
            "hint": "Set STUDYTWIN_ALLOW_PROFILES=1 to enable writes."})


def _valid_date(value: str) -> str:
    try:
        return cal.iso_date(value)
    except cal.DateFormatError as exc:
        raise HTTPException(422, detail={
            "error": "bad_date",
            "detail": str(exc),
            "hint": "Dates are ISO-8601 calendar dates: 2026-08-20."}) from exc


def _reject_future(iso: str) -> None:
    """A day that has not happened cannot be reported on.

    Rejected rather than accepted-and-flagged: the whole feature is a
    record of what happened, and a row dated next Tuesday is either a
    typo or a plan, and neither belongs in a history. Planning is a
    different feature with different semantics.
    """
    today = _date.today().isoformat()
    if iso > today:
        raise HTTPException(422, detail={
            "error": "future_date",
            "detail": f"{iso} has not happened yet (today is {today}).",
            "hint": "Daily records describe what happened, not what is planned."})


def _reject_before_week_one(repo: Repository, profile_id: str, iso: str) -> None:
    """A date earlier than the student's declared week 1 has no week number.

    `week_index` is `CHECK (week_index >= 1)`, so writing one would raise an
    IntegrityError the caller could only read as a 500 - or, worse, be
    mistranslated into the 409 that the same exception type carries for a
    duplicate date. Caught here, where the reason can be stated.

    Only reachable when the student declared a `term_start` later than the day
    they are recording. An INFERRED anchor is the Monday of their earliest day,
    so it can never be after one.
    """
    declared = repo.term_start(profile_id)
    if not declared:
        return
    if cal.week_index(iso, declared) < 1:
        monday = cal.monday_of(declared).isoformat()
        raise HTTPException(422, detail={
            "error": "before_term_start",
            "detail": f"{iso} falls before week 1, which begins {monday}.",
            "hint": "Move the study start date on your profile back, or record "
                    "a date inside the study period."})


def _week_or_422(week: int) -> int:
    if week < 1 or week > MAX_WEEK:
        raise HTTPException(422, detail={
            "error": "bad_week",
            "detail": f"week must be between 1 and {MAX_WEEK}, got {week}",
            "hint": "GET /api/profiles/{id}/timeline reports how many weeks exist."})
    return week


def _resolve_day(repo: Repository, profile_id: str, iso: str) -> str:
    day_id = repo.day_id_for(profile_id, iso)
    if not day_id:
        raise HTTPException(404, detail={
            "error": "day_not_found",
            "detail": f"no record for {iso} on profile {profile_id!r}",
            "hint": "PUT the same URL to create it, or POST to /days."})
    return day_id


# ------------------------------------------------------------- vocabulary

@router.get("/daily/vocabulary", response_model=DailyVocabulary, tags=["daily"],
            summary="The closed vocabularies the daily forms and CHECK constraints share")
def daily_vocabulary() -> DailyVocabulary:
    """Categories, metrics with their ranges, prompts and sources.

    Served rather than duplicated in the frontend. A form whose options
    are typed out again in JavaScript drifts from the database CHECK the
    first time either changes, and the user sees a 422 they cannot act on.
    """
    return DailyVocabulary(**vocabulary())


# --------------------------------------------------------------- timeline

@router.get("/profiles/{profile_id}/timeline", response_model=DailyTimeline,
            tags=["daily"],
            summary="Every study week this student has, and the weekly rollups")
def profile_timeline(profile_id: str = Path(...),
                     repo: Repository = Depends(get_repo)) -> DailyTimeline:
    """The timeline is as long as the history is.

    `n_weeks` is derived: week 1 to the later of the last recorded week
    and the week containing today. There is no constant here, and in
    particular no twenty - a fixed-length strip that happens to be mostly
    empty makes a claim about the data that the data does not make.
    """
    _profile_or_404(repo, profile_id)
    return services.timeline(repo, profile_id)


@router.get("/profiles/{profile_id}/weeks/{week}", response_model=WeekDetail,
            tags=["daily"],
            summary="One study week: seven day slots, their days, and the rollup")
def profile_week(profile_id: str = Path(...), week: int = Path(..., ge=1),
                 repo: Repository = Depends(get_repo)) -> WeekDetail:
    """Always seven slots, recorded or not.

    A week the student never opened returns seven `recorded: false` slots
    and a rollup of zeros with `days_recorded: 0` - not a 404. The
    difference matters: the screen exists so that an empty week can be
    filled in, and 404-ing it would mean a student could only edit weeks
    they had already written to.
    """
    _profile_or_404(repo, profile_id)
    return services.week_detail(repo, profile_id, _week_or_422(week))


# ------------------------------------------------------------------- days

@router.get("/profiles/{profile_id}/days", response_model=list[DayDetail],
            tags=["daily"], summary="Recorded days, optionally within a date range")
def list_days(profile_id: str = Path(...),
              start: str | None = Query(None, description="Inclusive ISO date."),
              end: str | None = Query(None, description="Inclusive ISO date."),
              repo: Repository = Depends(get_repo)) -> list[DayDetail]:
    """Only days that exist. Absent days are absent, not returned empty.

    The week view is the place that renders seven slots including the
    empty ones, because that is a calendar. This route is a list of what
    was written.
    """
    _profile_or_404(repo, profile_id)
    if start or end:
        lo = _valid_date(start) if start else "0001-01-01"
        hi = _valid_date(end) if end else "9999-12-31"
        if lo > hi:
            raise HTTPException(422, detail={
                "error": "bad_range",
                "detail": f"start {lo} is after end {hi}"})
        rows = repo.days_between(profile_id, lo, hi)
    else:
        rows = repo.all_days(profile_id)
    return [services.day_detail(profile_id, r) for r in rows]


@router.post("/profiles/{profile_id}/days", response_model=DayDetail, status_code=201,
             tags=["daily"], summary="Open a new day, optionally with content")
def create_day(profile_id: str = Path(...), body: DayCreate = Body(...),
               repo: Repository = Depends(get_repo),
               settings: Settings = Depends(get_settings_dep)) -> DayDetail:
    """`409` when the date already exists rather than a silent merge.

    The UNIQUE (profile_id, date) constraint is allowed to raise and is
    translated here. Pre-checking with a SELECT would be a race, and
    quietly merging into the existing day would let a double-submitted
    form append the same five activities twice.
    """
    _guard_writes(settings)
    _profile_or_404(repo, profile_id)
    iso = _valid_date(body.date)
    _reject_future(iso)
    _reject_before_week_one(repo, profile_id, iso)
    try:
        day_id = repo.create_day(profile_id, iso)
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, detail={
            "error": "day_exists",
            "detail": f"{iso} is already recorded for this profile",
            "hint": f"PUT /api/profiles/{profile_id}/days/{iso} to replace it."}) from exc

    if body.observations or body.reflections:
        repo.replace_observations(day_id, body.observations)
        repo.replace_reflections(day_id, body.reflections)
    for i, a in enumerate(body.activities):
        repo.create_activity(day_id, {**a.model_dump(), "seq": i})
    return services.day_detail(profile_id, repo.day(profile_id, iso))


@router.get("/profiles/{profile_id}/days/{day_date}", response_model=DayDetail,
            tags=["daily"], summary="One day, complete")
def get_day(profile_id: str = Path(...), day_date: str = Path(...),
            repo: Repository = Depends(get_repo)) -> DayDetail:
    _profile_or_404(repo, profile_id)
    iso = _valid_date(day_date)
    row = repo.day(profile_id, iso)
    if row is None:
        raise HTTPException(404, detail={
            "error": "day_not_found",
            "detail": f"no record for {iso} on profile {profile_id!r}",
            "hint": "PUT the same URL to create it."})
    return services.day_detail(profile_id, row)


@router.put("/profiles/{profile_id}/days/{day_date}", response_model=DayDetail,
            tags=["daily"],
            summary="Create or replace a day's metrics and written answers")
def upsert_day(profile_id: str = Path(...), day_date: str = Path(...),
               body: DayUpdate = Body(...),
               repo: Repository = Depends(get_repo),
               settings: Settings = Depends(get_settings_dep)) -> DayDetail:
    """Create-or-replace on a client-chosen key, so Save is one call.

    REPLACE, not merge: an omitted metric has been cleared. A student who
    deletes their stress rating and saves must not find it still there,
    and a merge semantics would make clearing a field impossible through
    this route.

    Activities are untouched. They have their own ids and their own
    routes; folding them in would mean every save re-created every row and
    invalidated the ids the client was holding.
    """
    _guard_writes(settings)
    _profile_or_404(repo, profile_id)
    iso = _valid_date(day_date)
    _reject_future(iso)
    day_id = repo.day_id_for(profile_id, iso)
    if day_id is None:
        _reject_before_week_one(repo, profile_id, iso)
        day_id = repo.create_day(profile_id, iso)
    try:
        repo.replace_observations(day_id, body.observations)
        repo.replace_reflections(day_id, body.reflections)
    except (sqlite3.IntegrityError, DailyValueError) as exc:
        raise HTTPException(422, detail={
            "error": "invalid_day_content", "detail": str(exc)}) from exc
    return services.day_detail(profile_id, repo.day(profile_id, iso))


@router.delete("/profiles/{profile_id}/days/{day_date}", status_code=204,
               tags=["daily"],
               summary="Erase a day and everything recorded in it")
def delete_day(profile_id: str = Path(...), day_date: str = Path(...),
               repo: Repository = Depends(get_repo),
               settings: Settings = Depends(get_settings_dep)) -> None:
    """Hard delete, cascading to activities, metrics and prose.

    A soft delete would leave a person's account of a day in the database
    after they asked for it to be gone, which is the opposite of what the
    `profiles` island exists to guarantee.
    """
    _guard_writes(settings)
    _profile_or_404(repo, profile_id)
    iso = _valid_date(day_date)
    if not repo.delete_day(profile_id, iso):
        raise HTTPException(404, detail={
            "error": "day_not_found",
            "detail": f"no record for {iso} on profile {profile_id!r}"})


# ------------------------------------------------------------- activities

@router.post("/profiles/{profile_id}/days/{day_date}/activities",
             response_model=ActivityOut, status_code=201, tags=["daily"],
             summary="Add one activity to a day")
def create_activity(profile_id: str = Path(...), day_date: str = Path(...),
                    body: ActivityCreate = Body(...),
                    repo: Repository = Depends(get_repo),
                    settings: Settings = Depends(get_settings_dep)) -> ActivityOut:
    """The day must already exist.

    Auto-creating it would make a mistyped date silently open a day the
    student never intended, in a week they were not looking at. The client
    creates the day first, which it has to do anyway to show the panel.
    """
    _guard_writes(settings)
    _profile_or_404(repo, profile_id)
    iso = _valid_date(day_date)
    day_id = _resolve_day(repo, profile_id, iso)
    try:
        activity_id = repo.create_activity(day_id, body.model_dump())
    except sqlite3.IntegrityError as exc:
        raise HTTPException(422, detail={
            "error": "invalid_activity", "detail": str(exc)}) from exc
    day = repo.day(profile_id, iso)
    return next(a for a in services.day_detail(profile_id, day).activities
                if a.activity_id == activity_id)


@router.put("/profiles/{profile_id}/activities/{activity_id}",
            response_model=ActivityOut, tags=["daily"],
            summary="Replace one activity")
def update_activity(profile_id: str = Path(...), activity_id: str = Path(...),
                    body: ActivityUpdate = Body(...),
                    repo: Repository = Depends(get_repo),
                    settings: Settings = Depends(get_settings_dep)) -> ActivityOut:
    """Resolved through the owning profile, never by id alone.

    `activity_day` joins `day_records` on `profile_id`, so an activity
    belonging to somebody else is a 404 here and not an edit. That is the
    isolation guarantee, enforced by the query rather than by a check a
    future route might forget.
    """
    _guard_writes(settings)
    _profile_or_404(repo, profile_id)
    owned = repo.activity_day(profile_id, activity_id)
    if not owned:
        raise HTTPException(404, detail={
            "error": "activity_not_found",
            "detail": f"activity {activity_id!r} is not on this profile"})
    try:
        repo.update_activity(activity_id, body.model_dump(exclude_unset=False))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(422, detail={
            "error": "invalid_activity", "detail": str(exc)}) from exc
    day = repo.day(profile_id, owned["date"])
    return next(a for a in services.day_detail(profile_id, day).activities
                if a.activity_id == activity_id)


@router.delete("/profiles/{profile_id}/activities/{activity_id}", status_code=204,
               tags=["daily"], summary="Remove one activity")
def delete_activity(profile_id: str = Path(...), activity_id: str = Path(...),
                    repo: Repository = Depends(get_repo),
                    settings: Settings = Depends(get_settings_dep)) -> None:
    _guard_writes(settings)
    _profile_or_404(repo, profile_id)
    if not repo.activity_day(profile_id, activity_id):
        raise HTTPException(404, detail={
            "error": "activity_not_found",
            "detail": f"activity {activity_id!r} is not on this profile"})
    repo.delete_activity(activity_id)
