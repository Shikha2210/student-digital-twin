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

**Validation:** `display_name` ≤ 120 chars. `payload` is stored verbatim as JSON.
**Disabled** with `403 profiles_disabled` when `STUDYTWIN_ALLOW_PROFILES=0`.

### `GET|PUT|DELETE /api/profiles/{id}`

`404 profile_not_found` when absent. `DELETE` returns `204` and is the only
destructive route in the API.

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
| Destructive-write surface | Exactly one route: `DELETE /api/profiles/{id}`. |

**Not implemented, and out of scope for a single-machine research prototype**

* **Authentication and authorisation.** There are no accounts. Anyone who can
  reach the port can read every synthetic result and create a profile. This is
  acceptable because the model data describes nobody, and unacceptable the
  moment real student data is ingested - which is why that gate is in
  `README.md` as a blocker rather than a nice-to-have.
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
