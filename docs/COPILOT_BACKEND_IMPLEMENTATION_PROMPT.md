# Implementation prompt — StudyTwin backend

> **How to use this file.** Paste it (or point an agent at it) as the complete
> specification for the StudyTwin backend. It is written so another coding agent
> can implement or extend the backend without asking architectural questions.
>
> **The backend described here already exists and passes its tests.** Use this
> document to (a) re-implement it on a different stack, (b) extend it, or
> (c) verify the existing implementation against a written spec. Section 14
> lists what is genuinely unbuilt.

---

## 1. Project context

StudyTwin is a **context-adaptive student digital twin**: a latent state-space
model that maintains a per-student estimate of a hidden state, updates it weekly,
explains its own movements, and simulates possible futures.

The research pipeline is **already implemented and is the source of truth**:

```
src/student_twin/
  adapters/     synthetic + oulad → canonical EventTable
  features/     tier-1 self-relative features, context covariates
  state/        fit.py, filter.py (Laplace), emissions.py, model.py
  models/       readout.py — discrete-time hazard
  simulation/   forward.py — particle simulation, intervention.py
  evaluation/   metrics, negative controls, twin tests T1-T4
  explain.py    structural attribution
  pipeline.py   run_pipeline() → PipelineResult
```

### Non-negotiable rules

1. **DO NOT DUPLICATE MODEL LOGIC.** The backend never fits, filters, simulates
   or scores. It stores what `run_pipeline()` produced and serves it. If a
   number is not in a `PipelineResult` or a `SimulationResult`, it does not exist.
2. **DO NOT FABRICATE DATA.** No placeholder values, no synthesised fallbacks, no
   interpolation between two stored simulations. Missing → `404` with a `hint`.
3. **PROVENANCE IS MANDATORY.** Every model-derived row carries `run_id`. Every
   payload carrying a model number carries a `provenance` block including
   `synthetic: bool`.
4. **NEVER STORE A TEST THAT DID NOT RUN.** T3 and T4 raise
   `NotImplementedError`. They must be **absent** from `capability_tests` and
   named in a `not_implemented` list.
5. **THE RESIDUAL IS NEVER NORMALISED AWAY.**
   `shift == Σ contributions + residual` must hold end to end.
6. **ASCII source files.** The Windows console renders em dashes as mojibake.

---

## 2. Backend stack

| Concern | Choice | Rationale |
|---|---|---|
| Language | **Python 3.13** (`py -3.13`) | matches the pipeline |
| Web framework | **FastAPI** | auto OpenAPI, response validation, DI |
| ASGI server | **uvicorn** | standard |
| Validation | **pydantic v2** | request + response models |
| Database | **SQLite** via stdlib `sqlite3` | single file; no server |
| ORM | **NONE** | the schema is the documentation; queries are trivial |
| Migrations | numbered `.sql` + checksum ledger | forward-only |
| Tests | **pytest** + `fastapi.testclient` | |

**Do not add:** SQLAlchemy, Alembic, Celery, Redis, Docker, an auth library.
Each was considered; none is justified by a single-machine research prototype
serving synthetic data. `docs/architecture.md` records the reasoning.

---

## 3. Project structure

```
src/student_twin/
├── store/
│   ├── __init__.py
│   ├── db.py                     Database, connect(), transaction()
│   ├── migrate.py                migrate(), applied_migrations()
│   ├── migrations/
│   │   ├── 001_initial.sql
│   │   └── 002_prior_uncertainty.sql
│   ├── ingest.py                 ingest_run()          ← ONLY writer
│   └── repository.py             Repository            ← ONLY reader
└── api/
    ├── __init__.py
    ├── settings.py               Settings, get_settings() (lru_cache)
    ├── schemas.py                every pydantic model
    ├── deps.py                   get_db, get_repo, resolve_run
    ├── services.py               rows → payloads
    ├── routes.py                 APIRouter(prefix="/api")
    └── app.py                    create_app(), lifespan, CORS, static

scripts/ingest_run.py             run the pipeline and persist it
tests/test_store.py               persistence
tests/test_api.py                 HTTP
web/api.js                        frontend data layer
```

---

## 4. Database schema

Authoritative DDL: `src/student_twin/store/migrations/001_initial.sql`.
Full prose reference: `docs/DATABASE_SCHEMA.md`.

### Tables

| Table | Primary key | Purpose |
|---|---|---|
| `model_runs` | `run_id` | provenance root; one per pipeline execution |
| `run_coverage` | `(run_id, canonical_type)` | every canonical type declared available/unavailable |
| `contexts` | `(run_id, context_id)` | course presentations |
| `students` | `(run_id, student_id)` | a student as observed in one run |
| `observations` | `(run_id, student_id, t, channel)` | canonical inputs, long format |
| `features` | `(run_id, student_id, t, feature)` | tier-1 features |
| `twin_states` | `(run_id, student_id, t, dim_name)` | filtered posterior mean + sd |
| `baselines` | `(run_id, student_id, dim_name)` | θ, shrinkage k, context mean |
| `hazards` | `(run_id, student_id, t)` | weekly hazard + cumulative risk |
| `attribution_steps` | `(run_id, student_id, t, dim_name)` | prior/posterior mean+sd, shift, residual |
| `attribution_components` | `(…, channel)` | per-channel contribution |
| `scenarios` | `scenario_id` | one simulated intervention magnitude |
| `forecasts` | `(scenario_id, student_id, h, dim_name)` | q05/q50/q95/mean |
| `forecast_risk` | `(scenario_id, student_id, h)` | cumulative simulated risk |
| `forecast_paths` | `(scenario_id, student_id, particle_ix, h, dim_name)` | real particle paths |
| `metrics` | `(run_id, model_name)` | AUC/Brier/ECE incl. baselines |
| `negative_controls` | `(run_id, control)` | verdicts |
| `capability_tests` | `(run_id, test_id)` | **only tests that ran** |
| `profiles` | `profile_id` | onboarding data; **no FK to anything** |

### Relationships

```
model_runs 1─n contexts 1─n students 1─n {observations, features, twin_states,
                                          baselines, hazards, attribution_steps}
attribution_steps 1─n attribution_components
model_runs 1─n scenarios 1─n {forecasts, forecast_risk, forecast_paths}
model_runs 1─n {metrics, negative_controls, capability_tests, run_coverage}
profiles  — island, no relationships
```

All model FKs are `ON DELETE CASCADE`.

### Constraints that must be enforced by the database, not only by Python

```sql
CHECK (synthetic IN (0,1))
CHECK (n_dims BETWEEN 1 AND 3)                   -- mirrors StateConfig
CHECK (sd >= 0)
CHECK (hazard >= 0 AND hazard <= 1)
CHECK (cum_risk >= 0 AND cum_risk <= 1)
CHECK (y IN (0,1))
CHECK (verdict IN ('COLLAPSED','SURVIVED','UNDEFINED'))
CHECK (available IN (0,1))
CHECK (is_leakage_test IN (0,1))
CHECK (consent IN (0,1))
CHECK (passed IN (0,1))
```

### Nullable columns and what NULL means

| Column | `NULL` means |
|---|---|
| `students.event_week` | **censored** — never withdrew. NOT zero. |
| `model_runs.code_revision` | git unavailable. Never fabricate a SHA. |
| `attribution_components.observed_value` | channel not observed that week |
| `attribution_steps.prior_sd` | run predates migration 002 |

### Indexes

```sql
ix_runs_created         model_runs (created_at DESC)
ix_runs_dataset         model_runs (dataset, created_at DESC)
ix_students_context     students (run_id, context_id)
ix_obs_student_week     observations (run_id, student_id, t)
ix_feat_student_week    features (run_id, student_id, t)
ix_state_student_week   twin_states (run_id, student_id, t)
ix_scen_run             scenarios (run_id)
ix_profiles_created     profiles (created_at DESC)
```

### Connection pragmas — required

```sql
PRAGMA foreign_keys = ON;    -- SQLite defaults OFF; every CASCADE depends on it
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
```

---

## 5. API endpoints

Prefix `/api`. Full spec: `docs/API_SPEC.md`.

| Method | Path | Response model | Errors |
|---|---|---|---|
| GET | `/health` | `Health` | — |
| GET | `/runs?limit=` | `RunSummary[]` | 422 |
| GET | `/runs/{run_id}` | `RunDetail` | 404 |
| GET | `/evaluation?run_id=` | `EvaluationPayload` | 404, 503 |
| GET | `/cohort?run_id=&limit=` | `CohortPoint[]` | 404, 503 |
| GET | `/contrast?run_id=` | `ContrastPair` | 404 |
| GET | `/students?run_id=&limit=&offset=` | `StudentPage` | 404, 422 |
| GET | `/students/demo` | `StudentSummary` | 404 |
| GET | `/students/{id}` | `StudentSummary` | 404 |
| GET | `/students/{id}/twin` | `TwinPayload` | 404 |
| GET | `/students/{id}/state` | `StateSeries[]` | 404 |
| GET | `/students/{id}/forecast` | `ScenarioForecast[]` | 404 |
| POST | `/profiles` | `ProfileOut` (201) | 403 |
| GET | `/profiles/{id}` | `ProfileOut` | 404 |
| PUT | `/profiles/{id}` | `ProfileOut` | 404 |
| DELETE | `/profiles/{id}` | — (204) | 404 |

**Route ordering:** `/students/demo` must be declared **before**
`/students/{student_id}`, otherwise `demo` is captured as an id.

### `run_id` resolution

A shared dependency:

* explicit `?run_id=` → validate it exists, else `404`
* omitted → newest run by `created_at`
* no runs at all → `503` with
  `hint: "Run: python scripts/ingest_run.py --students 250 --weeks 20"`

### Key request/response JSON

`GET /api/students/S000021/twin`:

```jsonc
{
  "provenance": { "run_id": "...", "dataset": "synthetic", "synthetic": true,
                  "seed": 20260813, "model_version": "0.1.0",
                  "code_revision": "1117b83", "inference_method": "laplace_approximate",
                  "created_at": "...", "note": "SYNTHETIC DATA. ..." },
  "student": { "student_id": "S000021", "context_id": "SYN0_2026A",
               "n_weeks": 20, "event_observed": false, "event_week": null },
  "dim_names": ["engagement", "capability"],
  "state": [ { "dim_name": "engagement", "t": [...], "mean": [...], "sd": [...],
               "method": "laplace_approximate" } ],
  "baseline": [ { "dim_name": "engagement", "theta": 0.279, "shrinkage_k": 0.4325,
                  "context_mean": 0.031, "n_obs": 20 } ],
  "hazard": [ { "t": 0, "hazard": 0.0067, "cum_risk": 0.0067, "y": 0 } ],
  "observations": [ { "t": 0, "channels": {...}, "features": {...} } ],
  "attribution": [ { "t": 19, "dim_name": "engagement",
                     "prior_mean": 0.113, "prior_sd": 0.577,
                     "posterior_mean": -0.774, "posterior_sd": 0.315,
                     "shift": -0.887, "residual": -0.240,
                     "components": [ { "channel": "content_view",
                                       "contribution": -0.659,
                                       "observed_value": 3 } ] } ],
  "scenarios": [ { "scenario_id": "...", "label": "Support +1.00",
                   "interventions": [ { "name": "engagement_support",
                                        "magnitude": 1.0 } ],
                   "is_counterfactual": true, "horizon": 8, "n_particles": 600,
                   "quantiles": [ { "dim_name": "engagement", "h": [...],
                                    "t": [...], "q05": [...], "q50": [...],
                                    "q95": [...], "mean": [...] } ],
                   "cum_risk": [...], "paths": [[...]],
                   "disclaimer": "MODEL-GENERATED SCENARIO. NOT A CAUSAL ESTIMATE. ..." } ],
  "own_distribution": [ { "dim_name": "engagement", "mean": 0.156, "sd": 0.489,
                          "n": 20, "weeks_below_theta": 10,
                          "longest_run_below": 6, "current_run_below": 3 } ],
  "cohort_theta": [ 0.28, -1.31, ... ]
}
```

`POST /api/profiles`:

```jsonc
// request
{ "display_name": "Sid", "consent": true, "payload": { "courses": ["ML"] } }
// response 201
{ "profile_id": "...", "created_at": "...", "updated_at": "...",
  "display_name": "Sid", "consent": true, "observations": 0,
  "payload": {...}, "model_input": false }
```

`model_input: false` and `observations: 0` are **required fields**. The
inference model learns from weekly behavioural observations; nothing a user
types is model input, and a client must receive that fact rather than infer it.

Error envelope:

```jsonc
{ "detail": { "error": "student_not_found",
              "detail": "student 'X' is not in run 'Y'",
              "hint": "optional" } }
```

---

## 6. Model integration

**Exactly one integration point:** `scripts/ingest_run.py`.

```python
result = run_pipeline(cfg, adapter_name="synthetic",
                      adapter_kwargs=dict(n_students=250, n_weeks=20))
run_id = ingest_run(db, result, config=cfg, scenarios=DEFAULT_SCENARIOS,
                    horizon=8, n_particles=600, max_students=40)
```

`ingest_run` must:

1. insert `model_runs` with seed, model version, git SHA (or `NULL`),
   `config_json`, `params_json`;
2. insert `run_coverage` for **every** canonical type;
3. insert contexts, students (with `event_week = NULL` when censored);
4. re-derive observations via `features.tier1.observation_frame` — a
   deterministic reshape of the input, **not** a recomputation;
5. insert tier-1 features from `result.features`;
6. insert states from `traj.states`, and `prior_sd` from `traj.predicted_covs`;
7. insert baselines from `params.student_setpoints` + `params.setpoint_shrinkage`;
8. insert hazards from `result.readout.cumulative_risk(person_period)`;
9. insert attribution from `explain.explain_trajectory`;
10. for each scenario magnitude, call `simulate_forward` **separately** and
    store quantiles, cumulative risk and `N_RETAINED_PATHS = 40` particle paths;
11. insert metrics and negative controls;
12. wrap all of it in **one transaction**.

**Never interpolate between two scenarios.** Each magnitude is its own
simulation with its own `rng_for(config, purpose)` seed.

---

## 7. Validation

| Layer | Mechanism |
|---|---|
| Query params | pydantic via FastAPI (`Query(..., ge=1, le=500)`) |
| Path params | typed function signature |
| Request bodies | pydantic models (`ProfileCreate`, `max_length=120`) |
| Responses | `response_model=` on **every** route |
| Domain | SQL `CHECK` constraints (section 4) |

A response that does not match its declared model must raise server-side. Never
disable response validation for convenience.

---

## 8. Error handling

| Status | When |
|---|---|
| 200 / 201 / 204 | success |
| 403 | `STUDYTWIN_ALLOW_PROFILES=0` and a profile write was attempted |
| 404 | run, student, states, forecast, contrast pair or profile absent |
| 422 | parameter or body validation |
| 500 | unhandled — **logged server-side, generic body returned** |
| 503 | database migrated but empty; include the ingest command as `hint` |

A `500` must never return a stack trace: it is a security problem and a bad user
experience. Log it, return a sentence.

---

## 9. Authentication

**None, deliberately.** There are no accounts. The model data is synthetic and
describes nobody.

This is acceptable **only** while no real student data is in the database. When
OULAD or any real cohort is ingested, authentication becomes a hard blocker. Do
not add a placeholder auth layer now: an unenforced auth system is worse than a
documented absence, because it looks like protection.

---

## 10. Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `STUDYTWIN_DB` | `data/studytwin.db` | SQLite path |
| `STUDYTWIN_WEB_DIR` | `web/` | static frontend directory |
| `STUDYTWIN_SERVE_WEB` | `1` | serve the frontend from this process |
| `STUDYTWIN_CORS_ORIGINS` | localhost 8777 + 8000 | comma-separated; **never `*`** |
| `STUDYTWIN_ALLOW_PROFILES` | `1` | enable profile writes |
| `STUDYTWIN_MAX_PAGE_SIZE` | `500` | hard cap on `limit` |
| `STUDYTWIN_LOG_LEVEL` | `INFO` | logging level |

No secret, credential or connection string may be hard-coded.

---

## 11. Migrations

* numbered `NNN_name.sql`, applied in filename order,
* recorded in `schema_migrations (version, applied_at, checksum)`,
* checksum = first 16 hex chars of SHA-256 of the file,
* re-running is a no-op,
* **editing an applied migration must raise** with a message telling the caller
  to add a new one instead,
* **no downgrade path** — a downgrade that drops a table containing model
  results destroys provenance,
* migrations run automatically on app startup (`lifespan`), idempotently.

---

## 12. Testing

`tests/test_store.py` — persistence:

* migrations idempotent; editing an applied migration raises
* foreign keys enforced (insert with a bogus `run_id` → `IntegrityError`)
* `n_dims` CHECK rejects 7; hazard CHECK rejects 1.4; verdict CHECK rejects junk
* ingest populates every output table
* `run_coverage` count == available + unavailable
* stored states equal `PipelineResult` states to 1e-9
* `shift == Σ contributions + residual`; not every residual is zero
* two scenarios produce different medians
* run records seed, model version, config, fitted params
* deleting a run cascades everything away
* ingest is atomic (inject a failure mid-ingest → nothing persisted)
* profiles isolated from model data

`tests/test_api.py` — HTTP:

* health reports real contents
* OpenAPI documents every route
* twin payload has the documented shape
* `state[0].dim_name == dim_names[0]`
* attribution invariant holds over HTTP
* every forecast contains `NOT A CAUSAL ESTIMATE`
* scenarios differ from one another
* `not_implemented` names T3 and T4; neither appears in `capability_tests`
* every model payload carries provenance; `synthetic` is boolean
* profile reports `model_input: false`
* 404 for unknown student/run; 422 for bad pagination
* **SQL injection in a path parameter is inert**

Use a temp-directory database and `TestClient`. Never touch the developer's real
database.

---

## 13. Frontend integration

`web/api.js` owns the boundary and defines ONE internal *view model* with two
producers: `fromApi()` and `fromSnapshot()`. Both emit identical structures.

Requirements:

1. Try the API. On failure (or 6 s timeout) fall back to `web/data.js`.
2. When the snapshot is used, show a **non-dismissible banner** and a sidebar
   `Source: snapshot` row.
3. If both fail, render an error naming what failed. **Never a placeholder
   number.**
4. Show a real loading state — heading, explanation, progress bar.
5. The frontend must not compute a model quantity. If a chart needs a model
   value, **add a column** (as migration 002 did for `prior_sd`); do not
   re-implement the equation in JavaScript.

---

## 14. Implementation order

1. `store/db.py` — connect, pragmas, `transaction()`
2. `store/migrations/001_initial.sql`
3. `store/migrate.py` — ledger + checksum guard
4. `store/repository.py` — reads
5. `store/ingest.py` — writes
6. `scripts/ingest_run.py`
7. `tests/test_store.py` — **must pass before any HTTP work**
8. `api/settings.py`, `api/schemas.py`, `api/deps.py`
9. `api/services.py`
10. `api/routes.py`
11. `api/app.py`
12. `tests/test_api.py`
13. `web/api.js` + frontend loading/error/snapshot states
14. `store/migrations/002_prior_uncertainty.sql`

### Genuinely unbuilt — safe extension work

| Item | Notes |
|---|---|
| `POST /api/runs` to trigger ingestion over HTTP | needs a job queue; ingest takes ~30 s. Currently CLI-only, deliberately. |
| Confidence intervals on metrics | requires a pipeline change first, not an API change |
| Authentication | **blocker before real student data**, not before |
| Postgres backend | `store/db.py` is the only file that changes; see `DATABASE_SCHEMA.md` §7 |
| Cohort triage endpoint | list students ranked by deviation from own θ |
| `GET /api/students/{id}/timeline` | narrower read than `/twin` |

---

## 15. Acceptance criteria

The implementation is complete when **all** of the following hold:

- [ ] `python -m student_twin.store.migrate` creates the schema; running it twice applies nothing
- [ ] Editing an applied migration raises with a message naming the checksum change
- [ ] `python scripts/ingest_run.py --students 250 --weeks 20` prints a `run_id` and non-zero counts for every output table
- [ ] `uvicorn student_twin.api.app:app --port 8000` starts and `/api/health` returns `status: "ok"`
- [ ] `/api/docs` lists all 16 routes
- [ ] `GET /api/students/demo` returns a student chosen from stored states, not a hard-coded id
- [ ] `GET /api/students/{id}/twin` matches `TwinPayload` exactly
- [ ] `state[0].dim_name == dim_names[0]` (model order, not alphabetical)
- [ ] `shift == Σ contributions + residual` for every attribution step
- [ ] Every forecast contains `NOT A CAUSAL ESTIMATE`
- [ ] `not_implemented` names T3 and T4; neither is in `capability_tests`
- [ ] Every model payload carries `provenance.synthetic` as a boolean
- [ ] `POST /api/profiles` returns `model_input: false` and `observations: 0`
- [ ] Unknown student → `404`; `limit=0` → `422`; SQL injection in a path parameter → inert `404`
- [ ] Deleting a run removes every row it produced
- [ ] A failure mid-ingest leaves the database untouched
- [ ] `pytest tests/test_store.py tests/test_api.py` passes with zero failures
- [ ] Existing ML tests still pass unchanged
- [ ] Frontend renders from the API; with the API stopped it renders from the snapshot **and says so**
- [ ] No hard-coded secret, credential, path or origin anywhere
- [ ] No model logic exists in `store/`, `api/` or `web/`
