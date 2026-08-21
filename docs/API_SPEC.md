# StudyTwin API specification

```
uvicorn student_twin.api.app:app --port 8000
```

* Interactive docs: <http://127.0.0.1:8000/api/docs> (Swagger, generated)
* Machine-readable: <http://127.0.0.1:8000/api/openapi.json>
* The same process serves the frontend at `/` unless `STUDYTWIN_SERVE_WEB=0`

This document explains *why* each route exists and what its response is allowed
to claim. The generated Swagger page is the authority on exact field types; it
cannot drift, because it is produced from the same pydantic models FastAPI
validates against.

---

## Design decisions

**Read-only for model data.** There is no `POST /api/students`, no
`POST /api/simulate`. Model numbers enter through one path only -
`scripts/ingest_run.py`, which runs the real pipeline and writes the result.
An HTTP endpoint that fits a model on request would mean the API had its own
copy of the model, which is the thing this architecture is built to prevent.

**Writable for what a person owns.** Profiles and daily records are the two
resources a student writes, and they are the two that describe a real person
rather than a pipeline run. They are kept in their own module
(`routes_daily.py`) and their own tables, with no path from either into a model
table - so "the API is read-only for model data" stays true in the strong sense:
nothing a user can POST can reach a number the model produced. See
[`DAILY_RECORDS.md`](DAILY_RECORDS.md).

**One composite route for the dashboard.** `GET /students/{id}/twin` returns
everything one screen needs. Six round trips to paint one page is a worse
contract than one whose shape is documented and validated.

**`run_id` is optional everywhere and echoed always.** Omit it and the latest
run is used, which keeps the common case a single URL. The response always
names the run it read, so nothing is ambiguous after the fact.

**404 rather than an empty success.** A student who is not in a run produces
`404`, not a payload of empty arrays. An empty chart and a missing student look
identical to a user; a status code does not.

---

## Conventions

| | |
|---|---|
| Base path | `/api` |
| Content type | `application/json` |
| Auth | **None.** See *Security* below. |
| Errors | `{ "detail": { "error": "<slug>", "detail": "<sentence>", "hint": "<optional>" } }` |
| Pagination | `limit` (1–500, capped by `STUDYTWIN_MAX_PAGE_SIZE`), `offset` (≥0) |
| Validation failure | `422` with FastAPI's field-level report |

---

## Route table

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness plus what the database actually contains |
| GET | `/api/runs` | Model runs, newest first |
| GET | `/api/runs/{run_id}` | Full manifest: config, fitted parameters, coverage |
| GET | `/api/evaluation` | Metrics, negative controls, capability tests |
| GET | `/api/cohort` | Per-student mean state and fitted set point |
| GET | `/api/contrast` | Two students whose set points genuinely differ |
| GET | `/api/students` | Paged list of students in a run |
| GET | `/api/students/demo` | The student the demo opens on |
| GET | `/api/students/{id}` | One student's identity and event status |
| GET | `/api/students/{id}/twin` | **Composite.** Everything for one dashboard |
| GET | `/api/students/{id}/state` | Filtered latent state only |
| GET | `/api/students/{id}/forecast` | Simulated scenarios only |
| POST | `/api/profiles` | Store a Twin created through onboarding |
| GET | `/api/profiles/{id}` | Read a profile |
| PUT | `/api/profiles/{id}` | Replace a profile |
| DELETE | `/api/profiles/{id}` | Erase a profile |
| GET | `/api/daily/vocabulary` | Activity categories, metrics and ranges, prompts |
| GET | `/api/profiles/{id}/timeline` | Every study week this student has, plus rollups |
| GET | `/api/profiles/{id}/weeks/{week}` | One week: seven day slots, days, rollup |
| GET | `/api/profiles/{id}/days` | Recorded days, optionally within a date range |
| POST | `/api/profiles/{id}/days` | Open a day, optionally with content |
| GET | `/api/profiles/{id}/days/{date}` | One day, complete |
| PUT | `/api/profiles/{id}/days/{date}` | Create or replace a day's metrics and answers |
| DELETE | `/api/profiles/{id}/days/{date}` | Erase a day and everything in it |
| POST | `/api/profiles/{id}/days/{date}/activities` | Add one activity to a day |
| PUT | `/api/profiles/{id}/activities/{aid}` | Replace one activity |
| DELETE | `/api/profiles/{id}/activities/{aid}` | Remove one activity |

---

## Meta

### `GET /api/health`

Liveness *and* contents. A health check that returns `{"status":"ok"}` while the
database is empty is worse than useless, so this one reports what is there.

```json
{ "status": "ok", "database": true, "migrations_applied": 2,
  "runs": 1, "latest_run_id": "f7bf16...", "model_version": "0.1.0" }
```

`status` is `degraded` when the database is reachable but holds no run.

**Data source:** `model_runs`, `schema_migrations`.
**Errors:** none. Failure is reported in the body, not the status code.

---

### `GET /api/runs?limit=20`

Newest first. Each row is one execution of the pipeline.

**Response:** `RunSummary[]` - `run_id`, `created_at`, `dataset`, `synthetic`,
`seed`, `model_version`, `code_revision`, `inference_method`, `n_students`,
`n_person_periods`, `n_events`, `notes`.

**Validation:** `limit` 1–100.

---

### `GET /api/runs/{run_id}`

`RunSummary` plus `n_dims`, `dim_names`, `config` (the full resolved `Config`),
`params` (fitted `alpha`, `diag(Q)`, `mu0`, emission loadings, dispersions,
shrinkage) and `coverage`.

This route is the reproducibility record: config + seed + model version + code
revision are everything needed to re-run.

**Errors:** `404 run_not_found`.

---

### `GET /api/evaluation?run_id=`

```jsonc
{ "provenance": {...},
  "metrics":           [ { "model_name": "twin_state", "auc": 0.705, ... } ],
  "negative_controls": [ { "control": "permute_time", "verdict": "SURVIVED", ... } ],
  "capability_tests":  [ { "test_id": "T1", "passed": true, ... } ],
  "coverage":          { "available": [...], "unavailable": [...] },
  "not_implemented":   [ "T3 ... NOT IMPLEMENTED", "T4 ... NOT IMPLEMENTED" ] }
```

`capability_tests` holds only tests that **ran**. Tests that have never been
implemented are named in `not_implemented`. An absent row could be misread as a
pass; a sentence saying NOT IMPLEMENTED cannot.

`verdict` is constrained by the database to `COLLAPSED | SURVIVED | UNDEFINED`.

---

### `GET /api/cohort?limit=400`

`CohortPoint[]`: `student_id`, `mean_state`, `theta`, `last_state`, all for the
run's first dimension. Both axes of the landing page's central argument - how a
student compares to everyone (`mean_state`) and to themselves
(`last_state - theta`).

---

### `GET /api/contrast`

Two students at opposite ends of the fitted set-point distribution, both with a
near-full history. Returns `ContrastPair { provenance, high, low }` where each
side carries `student_id`, `theta`, `t`, `mean`, `sd`.

**Errors:** `404 no_contrast_pair` when the run does not contain a pair that
genuinely differs. The landing page then omits the comparison rather than
assembling one from students who do not actually differ.

---

## Students

### `GET /api/students?run_id=&limit=50&offset=0`

```json
{ "total": 40, "limit": 50, "offset": 0, "items": [ StudentSummary, ... ] }
```

**Validation:** `limit` 1–500 then capped by `STUDYTWIN_MAX_PAGE_SIZE`;
`offset` ≥ 0. Out-of-range is `422`.

---

### `GET /api/students/demo`

The student the demo opens on: the largest sustained decline in the first
dimension, computed from stored states. Deliberately **not** a hard-coded id -
re-ingesting with a different seed picks a different student and the demo still
tells a legible story.

**Errors:** `404 no_students`.

---

### `GET /api/students/{student_id}/twin`

The composite. Full field-by-field description in
[`DATA_CONTRACT.md`](DATA_CONTRACT.md) §3.

**Data source:** `students`, `twin_states`, `baselines`, `hazards`,
`observations`, `features`, `attribution_steps`, `attribution_components`,
`scenarios`, `forecasts`, `forecast_risk`, `forecast_paths`.

**Errors:** `404 not_found` when the student is not in the run.

**Guarantees asserted by tests:**

* `state[0].dim_name == dim_names[0]`
* `shift == Σ components.contribution + residual`
* every `scenarios[i].disclaimer` contains `NOT A CAUSAL ESTIMATE`
* `provenance.synthetic` is present and boolean

---

### `GET /api/students/{id}/state` · `GET /api/students/{id}/forecast`

Narrow reads for clients that do not need the composite. Same models, same
guarantees. `forecast` returns `404 no_forecast` with a `hint` when no scenarios
were stored for that student, rather than an empty array.

---

## Profiles

The only writable resource, and the only one that can contain data about a real
person. Kept in its own table so "drop all model data" and "delete a user" are
different operations.

### `POST /api/profiles` → `201`

```jsonc
// request
{ "display_name": "Sid", "consent": true, "payload": { "courses": ["ML"], ... } }
// response
{ "profile_id": "...", "created_at": "...", "updated_at": "...",
  "display_name": "Sid", "consent": true,
  "observations": 0,
  "payload": { ... },
  "model_input": false }
```

`model_input: false` and `observations: 0` are **fields, not footnotes**. The
inference model learns from weekly behavioural observations; this prototype has
no path to collect them, so nothing a user types is model input. A client cannot
render a profile without receiving that fact.

`days_recorded` counts the profile's daily records - raw student-entered
history, which `observations` deliberately does not include because the two are
different things. `term_start` is the Monday anchoring week numbering for those
records; it is normalised to a Monday on write, so the response echoes the stored
value rather than the submitted one. **Changing it on a `PUT` re-derives every
stored `week_index`**, because leaving them alone would silently misfile the
student's whole history.

**Validation:** `display_name` ≤ 120 chars, `term_start` an ISO date.
`payload` is stored verbatim as JSON.
**Disabled** with `403 profiles_disabled` when `STUDYTWIN_ALLOW_PROFILES=0`.

### `GET|PUT|DELETE /api/profiles/{id}`

`404 profile_not_found` when absent. `DELETE` returns `204` and is the only
destructive route in the API.

---

## Daily records

The API's other half. Everything above this section serves model output and is
read-only by design; everything here is a student writing their own history.
They share a URL space and a set of conventions, and are separate modules
(`routes.py`, `routes_daily.py`) so the boundary stays legible.

Full reasoning, including the model-integration status:
[`DAILY_RECORDS.md`](DAILY_RECORDS.md).

**Two conventions are specific to this half.**

*Every path begins `/api/profiles/{profile_id}`.* There is no route that reaches
a day, an activity or a week without naming its owner, and the repository has no
method that would let one. Isolation is a property of the URL space rather than a
check somebody has to remember to write.

*A day is addressed by its date, not by an opaque id.* `PUT
/days/2026-08-20` is idempotent, readable in a log, and lets a client save
without first resolving an id it does not have. Activities keep ids, because a
day genuinely has many of them and they are edited one at a time.

**Writes ride the `STUDYTWIN_ALLOW_PROFILES` switch.** Daily records are the same
category of data as a profile - a real person's account of their own life - so a
deployment that has turned off personal data storage must not still accept days.
One switch rather than two, because two is how one of them ends up on by
accident. `403 profiles_disabled`.

### Route table

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/daily/vocabulary` | Categories, metrics with ranges, prompts, sources |
| GET | `/api/profiles/{id}/timeline` | Every study week this student has, plus weekly rollups |
| GET | `/api/profiles/{id}/weeks/{week}` | One week: seven day slots, their days, the rollup |
| GET | `/api/profiles/{id}/days` | Recorded days, optionally `?start=&end=` |
| POST | `/api/profiles/{id}/days` | Open a day, optionally with content |
| GET | `/api/profiles/{id}/days/{date}` | One day, complete |
| PUT | `/api/profiles/{id}/days/{date}` | Create or replace a day's metrics and answers |
| DELETE | `/api/profiles/{id}/days/{date}` | Erase a day and everything in it |
| POST | `/api/profiles/{id}/days/{date}/activities` | Add one activity |
| PUT | `/api/profiles/{id}/activities/{activity_id}` | Replace one activity |
| DELETE | `/api/profiles/{id}/activities/{activity_id}` | Remove one activity |

---

### `GET /api/daily/vocabulary`

The closed vocabularies the forms and the SQL `CHECK` constraints share.

```jsonc
{ "activity_categories": [ { "value": "class", "label": "Class or lecture" }, ... ],
  "activity_statuses":   [ { "value": "done",  "label": "Completed" }, ... ],
  "metrics": [ { "value": "mood", "label": "Mood", "min": 1, "max": 5,
                 "unit": "/5", "step": 1 },
               { "value": "sleep_hours", "label": "Sleep", "min": 0, "max": 24,
                 "unit": "h", "step": 0.5 }, ... ],
  "reflection_prompts": [ { "value": "difficult",
                            "label": "What did you find difficult?" }, ... ],
  "sources": ["student", "system", "import", "other"] }
```

Served rather than duplicated in the frontend. A form whose options are typed out
again in JavaScript drifts from the `CHECK` the first time either changes, and the
user sees a `422` they cannot act on.

---

### `GET /api/profiles/{id}/timeline`

```jsonc
{ "profile_id": "...", "term_start": "2026-06-22", "term_start_declared": true,
  "n_weeks": 9, "days_recorded": 12,
  "first_date": "2026-06-24", "last_date": "2026-08-20",
  "today": "2026-08-21",
  "weeks":   [ { "week": 1, "start_date": "2026-06-22", "end_date": "2026-06-28",
                 "days_recorded": 3, "n_activities": 7, "has_data": true }, ... ],
  "rollups": [ WeekRollup, ... ],
  "model_input": false }
```

**`n_weeks` is derived, and there is no constant behind it.** The span runs from
week 1 to whichever is later: the last week holding data, or the week containing
today. Today is included so a student always has somewhere to put today's entry;
nothing beyond it is manufactured. A fixed-length strip that happens to be mostly
empty makes a claim about the data that the data does not make.

`rollups` covers **only weeks that hold rows**. An empty week has no rollup,
because a row of zeros reads as a measurement.

`term_start_declared: false` means the anchor was inferred from the earliest
recorded day rather than set by the student. Week numbers move if they later
declare one, and the UI says so.

**Errors:** `404 profile_not_found`.

---

### `GET /api/profiles/{id}/weeks/{week}`

```jsonc
{ "profile_id": "...", "week": 8,
  "start_date": "2026-08-10", "end_date": "2026-08-16",
  "term_start": "2026-06-22", "term_start_declared": true,
  "slots": [ { "date": "2026-08-10", "day_of_week": 1, "weekday": "Monday",
               "recorded": false, "day_id": null, "n_activities": 0,
               "n_metrics": 0, "n_reflections": 0, "is_future": false }, ... ],
  "days":   [ DayDetail, ... ],
  "rollup": WeekRollup,
  "derived": true }
```

**Always seven slots, recorded or not, and never a `404` for an untouched week.**
The screen exists so an empty week can be filled in; 404-ing it would mean a
student could only edit weeks they had already written to. A slot with
`recorded: false` carries no counts and no metrics — not zeros.

`is_future` marks a date that has not happened in the server's timezone, so the
UI can withhold the add action rather than offering one the API will refuse.

**Validation:** `week` 1–520. Out of range is `422 bad_week`. The cap is a guard
against a date computation on `/weeks/900000000`, not a statement about course
length — the real number of weeks is on the timeline and comes from the data.

---

### `GET|POST /api/profiles/{id}/days`

`GET` returns only the days that **exist**, optionally filtered by `?start=` and
`?end=` (inclusive ISO dates). The week route is the one that renders seven slots
including empty ones, because that is a calendar; this is a list of what was
written. `start` after `end` is `422 bad_range`.

`POST` opens a day, optionally with observations, reflections and activities in
one request:

```jsonc
{ "date": "2026-08-13",
  "observations": { "mood": 4, "focus": 3, "sleep_hours": 7 },
  "reflections": { "difficult": "dynamic programming",
                   "learned": "memoization" },
  "activities": [ { "title": "DBMS Lecture", "category": "class",
                    "start_time": "09:00", "end_time": "10:30" } ] }
```

→ `201` with the complete `DayDetail`. The week is **derived server-side** from
the date; a client that could send its own week number could file Thursday in
week 3 and Friday in week 40.

**`409 day_exists` on a duplicate date**, translated from the
`UNIQUE (profile_id, date)` constraint rather than pre-checked with a `SELECT`,
which would be a race. Quietly merging into the existing day would let a
double-submitted form append the same five activities twice.

---

### `GET|PUT|DELETE /api/profiles/{id}/days/{date}`

`PUT` is **create-or-replace**, so Save is one call whether or not the day
already existed:

```jsonc
{ "observations": { "mood": 2 }, "reflections": {} }
```

**REPLACE, not merge.** An omitted metric has been *cleared*. A student who
deletes their stress rating and saves must not find it still there, and merge
semantics would make clearing a field impossible through this route.

**Activities are untouched by a `PUT`.** They have their own ids and their own
routes; folding them in would mean every save re-created every row and
invalidated the ids the client was holding.

`DELETE` is a hard delete returning `204`, cascading to activities, metrics and
prose. A soft delete would leave a person's account of a day in the database
after they asked for it to be gone.

**Errors:** `404 day_not_found` (with a hint naming the `PUT`), `422 bad_date`,
`422 future_date`, `422 invalid_day_content`.

---

### Activities

```jsonc
// POST /api/profiles/{id}/days/{date}/activities
{ "title": "Worked on ML assignment", "category": "assignment",
  "subject": "Machine Learning", "detail": "finished the write-up",
  "start_time": "11:00", "end_time": "13:00",
  "minutes": null, "importance": 4, "status": "partial" }
```

→ `201 ActivityOut`, carrying `activity_id`, `seq`, `source` and timestamps.

**`minutes` is derived from the clock pair** when it is not given: `11:00–13:00`
stores `120`. An explicitly stated duration always wins, because it is the more
direct statement and overwriting it would discard what the person asserted.
`null` means **unknown** and stays null — it is excluded from weekly totals
rather than counted as zero.

**An `end_time` before its `start_time` is `422`**, not wrapped past midnight.
Guessing which of the two readings was meant would put an invented eleven-hour
session in a weekly total; an overnight activity is recorded as two entries.

**The day must already exist** (`404 day_not_found`). Auto-creating it would make
a mistyped date silently open a day the student never intended, in a week they
were not looking at.

`PUT` and `DELETE` on `/activities/{activity_id}` resolve through the owning
profile, never by id alone: the query joins `day_records` on `profile_id`, so an
activity belonging to somebody else is a `404` and not an edit.

---

### Honesty guarantees, asserted by tests

`tests/test_api_daily.py` asserts each of these directly:

* **a metric that was not recorded is ABSENT from the payload** — not zero, not
  null. The UI can then omit the element rather than render a placeholder.
* **`model_input: false`** is present on every daily payload and on the profile.
  Daily data is persisted, aggregated and displayed, and consumed by no model;
  see [`DAILY_RECORDS.md`](DAILY_RECORDS.md) §5 for why, specifically.
* **`minutes_logged` never travels without `activities_without_duration`**, so a
  sum over half the activities cannot be read as a total.
* **every weekly metric mean carries `n`** — a one-day average and a seven-day
  average are different claims.
* **an opened-but-empty day is distinguishable from an absent one**:
  `days_recorded` counts the first, `days_with_content` only the second.
* **one profile cannot read or edit another's records**, asserted from both
  directions including by activity id.

### Daily-record errors

| Status | `error` | Cause |
|---|---|---|
| 404 | `profile_not_found` | no such profile |
| 404 | `day_not_found` | that date is not recorded for this profile |
| 404 | `activity_not_found` | no such activity **on this profile** |
| 409 | `day_exists` | `UNIQUE (profile_id, date)` |
| 422 | `bad_date` | not an ISO-8601 calendar date |
| 422 | `future_date` | the day has not happened yet |
| 422 | `bad_week` | week outside 1–520 |
| 422 | `bad_range` | `start` after `end` |
| 422 | `invalid_day_content` | a database constraint rejected the content |
| 403 | `profiles_disabled` | `STUDYTWIN_ALLOW_PROFILES=0` |


---

## Errors

| Status | `error` | Cause |
|---|---|---|
| 404 | `run_not_found` | `run_id` does not exist |
| 404 | `student_not_found` / `not_found` | student not in that run |
| 404 | `no_states` / `no_forecast` / `no_contrast_pair` | run holds no such rows |
| 404 | `profile_not_found` | no such profile |
| 403 | `profiles_disabled` | `STUDYTWIN_ALLOW_PROFILES=0` |
| 422 | (FastAPI field report) | query/body validation |
| 500 | `internal_error` | unhandled server fault |
| 503 | `no_model_run` | database migrated but empty; `hint` gives the command |

A `500` never returns a stack trace. The trace goes to the server log; the
client gets a sentence it can render.

---

## Security

Stated plainly, including what is **not** done.

**Implemented**

| Control | How |
|---|---|
| SQL injection | Every value is a bound parameter. No user input is ever string-interpolated into SQL. All queries live in `store/repository.py`. `tests/test_api.py` fires a `'; DROP TABLE students;--` path parameter and asserts it 404s inertly. |
| Input validation | pydantic models on every request body and query parameter; out-of-range is `422` before any handler runs. |
| Response validation | Every route declares a `response_model`; a payload that does not match the contract raises server-side. |
| CORS | Explicit origin list from `STUDYTWIN_CORS_ORIGINS`. Never `*` - `POST /api/profiles` accepts a name, and a wildcard origin on a route that stores anything about a person is careless even locally. |
| Secret management | No secret in the codebase. All configuration is environment variables with development-safe defaults (`api/settings.py`). |
| Error leakage | Unhandled exceptions are logged and returned as a generic `500`. |
| PII isolation | The `profiles` table is the only one that can hold a real name. No foreign key connects it to any model table. `DELETE` is a hard delete. |
| Destructive-write surface | Four routes, all reaching only data the requesting profile owns: `DELETE /api/profiles/{id}` (cascades to every day), `DELETE .../days/{date}`, `DELETE .../activities/{aid}`, and `PUT .../days/{date}` which replaces a day's content. No route can delete or alter a model number. |
| Cross-account access | Every daily route is scoped by `profile_id` in its path, and every repository method that reaches a day or an activity joins the owner in. There is deliberately no `day_by_id`. Asserted from both directions in `tests/test_api_daily.py::test_one_student_cannot_reach_another_students_records`. |

**Not implemented, and out of scope for a single-machine research prototype**

* **Authentication and authorisation.** There are no accounts. Anyone who can
  reach the port can read every synthetic result and create a profile. This is
  acceptable because the model data describes nobody, and unacceptable the
  moment real student data is ingested - which is why that gate is in
  `README.md` as a blocker rather than a nice-to-have.

  **Daily records raise the stakes of that gap and do not change its status.**
  Profile isolation is enforced *given* a `profile_id`; the id itself is
  unguessable (uuid4) but is not a credential, so the protection is against
  accidental cross-account reads, not against an attacker who has one. Binding
  to localhost remains the actual boundary until authentication exists.
* **Rate limiting** and **audit logging.**
* **Transport encryption.** Bind to localhost or put a TLS-terminating proxy in
  front. The application does not terminate TLS itself.
* **Consent enforcement.** `consent` is stored, not enforced.

---

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `STUDYTWIN_DB` | `data/studytwin.db` | SQLite path |
| `STUDYTWIN_WEB_DIR` | `web/` | Static frontend directory |
| `STUDYTWIN_SERVE_WEB` | `1` | Serve the frontend from this process |
| `STUDYTWIN_CORS_ORIGINS` | `http://127.0.0.1:8777,http://localhost:8777,http://127.0.0.1:8000,http://localhost:8000` | Comma-separated allowed origins |
| `STUDYTWIN_ALLOW_PROFILES` | `1` | Enable `POST /api/profiles` |
| `STUDYTWIN_MAX_PAGE_SIZE` | `500` | Hard cap on `limit` |
| `STUDYTWIN_LOG_LEVEL` | `INFO` | Python logging level |
