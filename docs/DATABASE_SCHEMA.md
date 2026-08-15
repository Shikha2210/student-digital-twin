# StudyTwin database schema

Engine: **SQLite** (stdlib `sqlite3`, no ORM).
Migrations: `src/student_twin/store/migrations/*.sql`, applied by
`python -m student_twin.store.migrate --db data/studytwin.db`.

```bash
# create or upgrade
python -m student_twin.store.migrate
# fill it with a real pipeline run
python scripts/ingest_run.py --students 250 --weeks 20
```

---

## Why this shape

**Why a database at all.** The research pipeline is stateless: it reads an
adapter, fits, filters and returns a `PipelineResult` in memory. That is right
for research and wrong for a product, because every page load would refit the
model - roughly 5 seconds of CPU to answer a question the model already
answered. The database is a **cache of a run**, not a second implementation.

**Why SQLite over Postgres.** Single-machine research prototype. No server to
run, the entire database is one file that can be attached to a release, and the
SQL is close enough to standard that the Postgres migration is mechanical
(see §7). A capstone team should not be operating a database server to see a
chart.

**Why no ORM.** Three reasons in order of weight:

1. The schema *is* the documentation. Reading `001_initial.sql` teaches you the
   data model; reading a declarative-base class hierarchy teaches you SQLAlchemy.
2. Every query here is a select over a composite key. An ORM's value is
   relationship management we do not need; its cost is a dependency plus an
   abstraction that hides exactly the SQL a reviewer wants to check.
3. `sqlite3` is stdlib, so persistence adds zero packages.

**Two invariants run through every table.**

1. **Every model-derived row carries `run_id`.** A number without a run has no
   seed, no model version and no code revision behind it, which makes it
   unreproducible and therefore not a result. `ON DELETE CASCADE` throughout
   means deleting a run removes everything it produced - asserted in
   `tests/test_store.py::test_deleting_a_run_removes_its_numbers`.
2. **Long format over wide.** The latent state has 1–3 dimensions and an adapter
   may supply any subset of the canonical channels. A wide table would need a
   migration every time that changed, and would have to store `NULL` where the
   honest answer is *"this dataset does not carry that channel"* - which is
   exactly the distinction `CoverageManifest` exists to preserve.

---

## 1. Entity-relationship diagram

```
                          ┌───────────────────┐
                          │    model_runs     │  ← root of all provenance
                          │  PK run_id        │
                          │  seed, version,   │
                          │  code_revision,   │
                          │  config_json,     │
                          │  params_json      │
                          └─────────┬─────────┘
             ┌──────────────┬───────┼────────┬──────────────┬─────────────┐
             │              │       │        │              │             │
       ┌─────▼──────┐ ┌─────▼────┐ │  ┌─────▼──────┐ ┌─────▼─────────┐ ┌─▼──────────┐
       │run_coverage│ │ contexts │ │  │  metrics   │ │negative_      │ │capability_ │
       │ PK(run,    │ │ PK(run,  │ │  │ PK(run,    │ │controls       │ │tests       │
       │    type)   │ │    ctx)  │ │  │    model)  │ │ PK(run,ctrl)  │ │PK(run,test)│
       └────────────┘ └─────┬────┘ │  └────────────┘ └───────────────┘ └────────────┘
                            │      │
                      ┌─────▼──────▼──────┐
                      │     students      │
                      │  PK(run_id, sid)  │
                      │  event_observed,  │
                      │  event_week       │
                      └─────────┬─────────┘
        ┌─────────────┬─────────┼─────────┬──────────────┬────────────────┐
        │             │         │         │              │                │
 ┌──────▼──────┐┌─────▼────┐┌───▼───────┐┌▼──────────┐┌──▼─────────────┐  │
 │observations ││ features ││twin_states││ baselines ││   hazards      │  │
 │ PK(run,sid, ││PK(run,sid││PK(run,sid,││PK(run,sid,││PK(run,sid,t)   │  │
 │    t,chan)  ││ ,t,feat) ││  t,dim)   ││    dim)   ││                │  │
 └─────────────┘└──────────┘└───────────┘└───────────┘└────────────────┘  │
                                                                          │
                                              ┌───────────────────────────▼┐
                                              │    attribution_steps       │
                                              │  PK(run,sid,t,dim)         │
                                              │  prior_mean, prior_sd,     │
                                              │  posterior_*, shift,       │
                                              │  residual                  │
                                              └────────────┬───────────────┘
                                                           │ 1..n
                                              ┌────────────▼───────────────┐
                                              │  attribution_components    │
                                              │  PK(run,sid,t,dim,channel) │
                                              └────────────────────────────┘

       ┌───────────────────┐
       │    scenarios      │  (run_id FK → model_runs)
       │  PK scenario_id   │
       └─────────┬─────────┘
     ┌───────────┼────────────┐
┌────▼──────┐┌───▼──────────┐┌▼──────────────┐
│ forecasts ││forecast_risk ││forecast_paths │
│PK(scen,   ││PK(scen,sid,h)││PK(scen,sid,   │
│  sid,h,   ││              ││  particle,h,  │
│  dim)     ││              ││  dim)         │
└───────────┘└──────────────┘└───────────────┘

       ┌───────────────────┐
       │     profiles      │  ← ISLAND. No FK to anything.
       │  PK profile_id    │     The only table that can hold a real name.
       └───────────────────┘
```

---

## 2. Table reference

### 2.1 `model_runs` — provenance root

**Purpose.** One row per pipeline execution. Everything else hangs off this.

| Column | Type | Null | Notes |
|---|---|---|---|
| `run_id` | TEXT | PK | uuid4 hex |
| `created_at` | TEXT | no | ISO-8601 UTC |
| `dataset` | TEXT | no | `synthetic` \| `oulad` \| … |
| `synthetic` | INTEGER | no | 0/1, `CHECK IN (0,1)`. Travels with the run, never with the reader's memory. |
| `seed` | INTEGER | no | master seed; all others derive via `rng_for` |
| `model_version` | TEXT | no | `student_twin.__version__` |
| `code_revision` | TEXT | **yes** | git short SHA, or `NULL`. Null is honest; a fake sha is not. |
| `inference_method` | TEXT | no | `laplace_approximate` |
| `n_dims` | INTEGER | no | `CHECK BETWEEN 1 AND 3` — mirrors `StateConfig` |
| `dim_names` | TEXT | no | JSON array, **ordered**. Source of truth for the primary dimension. |
| `config_json` | TEXT | no | full resolved `Config`. Without it a run cannot be reproduced. |
| `params_json` | TEXT | yes | fitted `alpha`, `diag(Q)`, `mu0`, loadings, dispersions, shrinkage |
| `n_students`, `n_person_periods`, `n_events` | INTEGER | no | denormalised counts for the manifest strip |
| `notes` | TEXT | yes | free text |

**Indexes:** `(created_at DESC)`, `(dataset, created_at DESC)`.
**Lifecycle:** insert-only. Deleting cascades to every dependent row.

The `n_dims` CHECK is deliberate duplication of the Python constraint. The
1–3 dimension limit is a research decision that a stray script must not be able
to route around by writing to the database directly.

---

### 2.2 `run_coverage` — the channel declaration

| Column | Type | Notes |
|---|---|---|
| `run_id` | TEXT | FK → `model_runs`, CASCADE |
| `canonical_type` | TEXT | PK part |
| `available` | INTEGER | 0/1 |

**Why it exists.** `CoverageManifest` raises unless *every* canonical type is
declared available or unavailable. Storing only the available ones would let
absence mean "unknown", which is the ambiguity the manifest was built to remove.
`tests/test_store.py` asserts `count == len(available) + len(unavailable)`.

Physiological and multimodal sensing appear here as permanently `available = 0`.

---

### 2.3 `contexts` / `students`

`contexts`: PK `(run_id, context_id)`, plus `n_students`, `n_weeks`.

`students`: PK `(run_id, student_id)`. A student **as observed in one run** —
the same person re-run under a new seed is a different row, because the
estimates attached to them differ.

| Column | Notes |
|---|---|
| `external_id` | the adapter's identifier; the only link back to source data |
| `event_observed` | 0/1 |
| `event_week` | **nullable — `NULL` means censored, not zero** |

`event_week IS NULL` is the single most important nullable in the schema.
Treating censored students as negatives inflates every metric, so the type
system is made to carry the distinction.

---

### 2.4 `observations` — inputs

PK `(run_id, student_id, t, channel)`; `value REAL NOT NULL`.
Index `(run_id, student_id, t)`.

Long format. A dataset that does not carry `forum` has **no forum rows**; it
does not have zeros. Re-derived at ingest from the stored events by
`features.tier1.observation_frame` — a deterministic reshape of the input, not
a recomputation of any model quantity.

### 2.5 `features` — tier-1 only

PK `(run_id, student_id, t, feature)`.

There is deliberately **no tier-3 table**, mirroring the absence of a tier-3
feature builder in the codebase. The absence is the enforcement.

---

### 2.6 `twin_states` — the filtered posterior

PK `(run_id, student_id, t, dim_name)`.

| Column | Notes |
|---|---|
| `mean`, `sd` | marginal posterior `p(z_t \| y_{1:t})`; `CHECK sd >= 0` |
| `method` | `InferenceMethod` — a plot mixing methods without saying so is a misreport |
| `n_observations` | how much evidence has been absorbed by week `t` |

**Why `sd` and not the full covariance.** The product shows marginal intervals.
Storing a 2×2 per week per student for a quantity nothing reads is storage
without a consumer. If a cross-dimension view is ever built, that is a migration.

---

### 2.7 `baselines` — the personal set point θ

PK `(run_id, student_id, dim_name)`.

| Column | Notes |
|---|---|
| `theta` | empirical-Bayes set point |
| `shrinkage_k` | `σ²_within / τ²_between`, **estimated** per dimension |
| `context_mean` | what θ was shrunk toward |
| `n_obs` | weeks of history behind it |

**There is no `theta_sd` column.** The two-stage estimator returns a point
estimate. A nullable column that is always `NULL` invites somebody to fill it
with something plausible, so it does not exist.

---

### 2.8 `hazards`

PK `(run_id, student_id, t)`. `CHECK hazard BETWEEN 0 AND 1`, `CHECK y IN (0,1)`.

Rows exist **only for weeks the student was at risk**. Weeks after withdrawal
are absent, not zero. The CHECK constraints are cheap insurance against a future
writer storing a log-odds where a probability belongs.

---

### 2.9 `attribution_steps` / `attribution_components`

Two tables because the relationship is genuinely 1→n: *one selected week has
many attribution components*.

`attribution_steps` PK `(run_id, student_id, t, dim_name)`:

| Column | Notes |
|---|---|
| `prior_mean`, `prior_sd` | the PREDICT step. `prior_sd` added in migration `002`. |
| `posterior_mean`, `posterior_sd` | the UPDATE step |
| `shift` | `posterior_mean - prior_mean` |
| `residual` | the higher-order term the decomposition cannot assign |

`attribution_components` PK `(…, channel)`, FK → `attribution_steps` CASCADE:
`contribution`, `observed_value` (nullable — `NULL` = channel not observed).

**Invariant:** `shift = Σ contribution + residual`. Asserted in
`tests/test_store.py` and again in `tests/test_api.py`.

`residual` is a column, not a rounding error. Normalising it away so the
components sum to 100% is the commonest dishonesty in explainable dashboards,
and the schema makes it structurally awkward to do.

**Why migration `002` exists.** `001` stored only the prior *mean*. The claim
"predict widens the uncertainty, update narrows it" is central to the product,
and without `prior_sd` the only way to draw it was to recompute
`P_pred = F P Fᵀ + Q` in JavaScript. Reimplementing a model equation in the
browser in order to illustrate that equation is exactly the duplication this
architecture exists to prevent, so the column was added instead.

---

### 2.10 `scenarios` / `forecasts` / `forecast_risk` / `forecast_paths`

`scenarios` PK `scenario_id`: `label`, `interventions_json`,
`is_counterfactual`, `horizon`, `n_particles`, `seed_purpose`.

Storing `seed_purpose` means the exact particle cloud can be regenerated:
`rng_for(config, purpose)`.

| Table | PK | Holds |
|---|---|---|
| `forecasts` | `(scenario_id, student_id, h, dim_name)` | `q05`, `q50`, `q95`, `mean` |
| `forecast_risk` | `(scenario_id, student_id, h)` | `cum_risk`, `CHECK 0..1` |
| `forecast_paths` | `(scenario_id, student_id, particle_ix, h, dim_name)` | individual particles |

**Why `forecast_paths` exists at all.** So the fan chart can draw real
trajectories. A fan interpolated between `q05` and `q95` would be a picture of a
band pretending to be a set of outcomes. 40 paths per student per scenario is
the compromise between honesty and file size (`N_RETAINED_PATHS`).

**Each slider stop is its own row set.** Seven magnitudes → seven scenarios →
seven independent 600-particle simulations. The Intervention Lab never
interpolates.

---

### 2.11 `metrics` / `negative_controls` / `capability_tests`

| Table | PK | Note |
|---|---|---|
| `metrics` | `(run_id, model_name)` | includes baselines the twin can lose to |
| `negative_controls` | `(run_id, control)` | `CHECK verdict IN ('COLLAPSED','SURVIVED','UNDEFINED')` |
| `capability_tests` | `(run_id, test_id)` | **only tests that ran** |

T3 and T4 raise `NotImplementedError` upstream, so they are **absent** here.
An absent row and a failing row are both honest; a fabricated pass is not.

---

### 2.12 `profiles` — the PII island

PK `profile_id`. `display_name`, `consent`, `payload_json`, `observations`,
`created_at`, `updated_at`.

**No foreign key connects this table to any model table.** That is the point:
"drop all model data" and "delete a user" must be different operations.
`observations` is `0` and stays `0` — there is no ingestion path for personal
observations, and the API returns `model_input: false` alongside it.

---

## 3. Indexes

| Index | Table | Why |
|---|---|---|
| `ix_runs_created` | `model_runs (created_at DESC)` | "latest run" is the hot path |
| `ix_runs_dataset` | `model_runs (dataset, created_at DESC)` | latest synthetic vs latest OULAD |
| `ix_students_context` | `students (run_id, context_id)` | cohort queries |
| `ix_obs_student_week` | `observations (run_id, student_id, t)` | timeline rail |
| `ix_feat_student_week` | `features (run_id, student_id, t)` | timeline rail |
| `ix_state_student_week` | `twin_states (run_id, student_id, t)` | every chart |
| `ix_profiles_created` | `profiles (created_at DESC)` | listing |

Composite primary keys already index the leading columns, so these cover the
access patterns the primary keys do not.

---

## 4. Connection pragmas

Set per connection in `store/db.py`:

```sql
PRAGMA foreign_keys = ON;    -- OFF by default in SQLite!
PRAGMA journal_mode = WAL;   -- API can read while an ingest writes
PRAGMA synchronous = NORMAL;
```

`foreign_keys` is not optional here. SQLite defaults it OFF, which silently
turns every `ON DELETE CASCADE` in the schema into a no-op — the provenance
guarantee would be documented and unenforced.
`tests/test_store.py::test_foreign_keys_are_enforced` fails if it is ever
dropped.

---

## 5. Example records

```sql
-- one run
INSERT INTO model_runs VALUES (
  'f7bf16bed5a04444aebe63f2fe0de84c', '2026-08-15T09:12:44+00:00',
  'synthetic', 1, 20260813, '0.1.0', '1117b83', 'laplace_approximate',
  2, '["engagement","capability"]', '{...}', '{...}', 40, 3325, 138, NULL);

-- week 19 of one student, first dimension
INSERT INTO twin_states VALUES
  ('f7bf16…','S000021',19,'engagement', -0.7742, 0.3153, 'laplace_approximate', 120);

-- that student's set point
INSERT INTO baselines VALUES
  ('f7bf16…','S000021','engagement', 0.2790, 0.4325, 0.0310, 20);

-- why the state moved that week
INSERT INTO attribution_steps VALUES
  ('f7bf16…','S000021',19,'engagement', 0.1130, -0.7742, -0.8872, -0.2400,
   0.5770, 0.3153);
INSERT INTO attribution_components VALUES
  ('f7bf16…','S000021',19,'engagement','content_view', -0.6590, 3.0);
```

## 6. Lifecycle

| Table group | Written by | Read by | Deleted |
|---|---|---|---|
| everything with `run_id` | `store/ingest.py` only | `store/repository.py` only | cascade from `model_runs` |
| `scenarios` + forecasts | `store/ingest.py` | `repository.py` | cascade |
| `profiles` | `api/routes.py` | `api/routes.py` | `DELETE /api/profiles/{id}` |
| `schema_migrations` | `store/migrate.py` | `migrate.py`, `/api/health` | never |

Ingest is wrapped in a single transaction. A half-written run looks like a
result and is not one; `tests/test_store.py::test_ingest_is_atomic` injects a
failure mid-ingest and asserts nothing was left behind.

---

## 7. Migration strategy

**Forward-only, numbered SQL files.** Each is applied once and recorded in
`schema_migrations` with a SHA-256 prefix. Editing a migration that has already
run raises:

```
migration 001_initial has already been applied but its contents changed
(stored a1b2…, now c3d4…). Add a new migration instead of editing an applied one.
```

That check is why two environments cannot silently diverge, and it is tested.

**No downgrade path.** A downgrade that drops a table containing model results
destroys provenance. For a single-file database, "copy the file first" is both
simpler and safer.

**Moving to Postgres** — the SQL was kept close to standard, so:

| SQLite | Postgres |
|---|---|
| `TEXT` primary keys | `UUID` or keep `TEXT` |
| `INTEGER` 0/1 + `CHECK` | `BOOLEAN` |
| `TEXT` ISO timestamps | `TIMESTAMPTZ` |
| `TEXT` JSON columns | `JSONB` |
| `PRAGMA foreign_keys` | on by default |
| `PRAGMA journal_mode=WAL` | not needed (MVCC) |

`store/db.py` is the only file that would change; `repository.py` is plain
parameterised SQL and ports as-is. This is the reason there is no ORM to unwind.

---

## 8. How the frontend, backend, model and database connect

```
adapters ──► pipeline ──► PipelineResult (in memory)
                                │
                                │  scripts/ingest_run.py
                                ▼
                        store/ingest.py  ── the ONLY writer
                                │
                                ▼
                         SQLite (this schema)
                                │
                                │  store/repository.py  ── the ONLY reader
                                ▼
                        api/services.py  (shape, never estimate)
                                │
                                ▼
                         api/routes.py  → JSON, response_model validated
                                │
                                ▼
                        web/api.js  → view model
                                │
                                ▼
                    web/app.js + charts.js  → pixels
```

The model appears exactly once, on the top line. Everything below it is
transport.
