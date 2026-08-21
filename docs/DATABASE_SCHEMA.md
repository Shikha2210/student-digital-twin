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

**Two invariants run through every MODEL table.** The daily-record tables
added in `003` are raw student input rather than model output and follow a
third rule instead - see §2.13 and [`DAILY_RECORDS.md`](DAILY_RECORDS.md).

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
       │     profiles      │  ← THE PERSON. No FK to any model table.
       │  PK profile_id    │     The only table that can hold a real name,
       │  term_start       │     and the only one a student can write to.
       └─────────┬─────────┘
                 │ 1..n          ← RAW student input. No run_id anywhere below.
       ┌─────────▼─────────┐
       │    day_records    │
       │  PK day_id        │
       │  UQ(profile,date) │
       │  week_index,      │
       │  day_of_week      │
       └─────────┬─────────┘
     ┌───────────┼────────────────┐
┌────▼──────────┐┌▼──────────────┐┌▼───────────────┐
│day_activities ││day_observations││day_reflections │
│PK activity_id ││PK(day_id,      ││PK(day_id,      │
│  seq, title,  ││   metric)      ││   prompt)      │
│  category,    ││                ││                │
│  minutes ...  ││   LONG format  ││   LONG format  │
└───────────────┘└────────────────┘└────────────────┘
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
*model* observations, and the API returns `model_input: false` alongside it.

Migration `003` adds `term_start TEXT` (nullable): the Monday that anchors week
numbering for this person's daily records, normalised to a Monday on write.
`NULL` is honest — a profile that has declared no study period has no week 1 to
be relative to, and the timeline reports `term_start_declared: false` rather than
presenting an invented one as settled.

**It is no longer an island in one direction only.** Nothing model-derived points
at it, which is the property that mattered; the daily tables in §2.13 point *at*
it and cascade from it, which is the same property from the other side — erasing
a person still erases everything about them in one `DELETE`.


### 2.13 `day_records` / `day_activities` / `day_observations` / `day_reflections`

Added by migration `003_daily_records`. Full reasoning:
[`DAILY_RECORDS.md`](DAILY_RECORDS.md).

**The one thing to notice first: no table in this group carries `run_id`.**
Every model-derived table in this schema does, because a number without a seed
and a code revision is unreproducible. A day a student lived is the opposite
kind of fact - it is RAW INPUT, derived from nothing, and it must survive a
re-ingest. Hanging these off `model_runs` would make a person's history cascade
away when somebody re-ran the pipeline.
`tests/test_daily.py::test_daily_records_do_not_hang_off_a_model_run` asserts the
column was never quietly added.

The owner is a **profile**, not a `students` row. `students` is "a student as
observed in one run" and is re-created under a new `run_id` every ingest;
`profiles` is the only run-independent, person-scoped, writable table in the
schema. That choice does three things at once: the days survive re-ingests, they
cascade away with the same `DELETE` that erases the person, and every read is
reachable only through a `profile_id` - which is what makes cross-account access
structurally impossible rather than a rule somebody has to remember.

`profiles` gains one column: `term_start TEXT` (nullable), the Monday that
anchors week numbering.

#### `day_records` — one student, one calendar date

| Column | Type | Notes |
|---|---|---|
| `day_id` | TEXT | PK, uuid4 hex |
| `profile_id` | TEXT | FK → `profiles`, CASCADE |
| `date` | TEXT | ISO-8601 calendar date |
| `week_index` | INTEGER | 1-based, **derived from `date`**, never accepted from a client |
| `day_of_week` | INTEGER | ISO: 1 = Monday … 7 = Sunday |
| `source` | TEXT | `student` \| `system` \| `import` \| `other` |
| `created_at`, `updated_at` | TEXT | ISO-8601 UTC |

**`UNIQUE (profile_id, date)`.** Without it a save that retries on a flaky
connection silently splits one day in two and the week view shows Thursday
twice. The route translates the integrity error into `409`, rather than
pre-checking with a `SELECT` - check-then-insert is a race.

**`CHECK (date IS strftime('%Y-%m-%d', date))`.** `IS` rather than `=` because
`strftime` returns `NULL` for garbage, and a `NULL` comparison would *satisfy* a
`CHECK`. `2026-02-30` is rejected in the database, not only in pydantic.

**Why `week_index` is stored at all.** It is a cached derivation, kept so "give
me week 8" is one indexed range scan. Because it is a cache it is re-derived
whenever the anchor moves — `Repository.set_term_start` rewrites every row in one
transaction, through `daily.calendar.week_index` rather than SQL date
arithmetic, so there is never a second implementation of week numbering and
never a row whose stored week disagrees with its date.

A row exists because the student **opened** the day, even if they recorded
nothing in it. An opened-and-empty day and an absent day are different facts.

**Index:** `ix_day_profile_week (profile_id, week_index, day_of_week)` for the
week view. `(profile_id, date)` is already indexed by the `UNIQUE` constraint,
which covers single-day and date-range reads.

#### `day_activities` — many per day

PK `activity_id`, FK → `day_records` CASCADE. `seq` keeps a stable order for the
activities with no clock time, which is most of them when a day is logged from
memory.

| Column | Notes |
|---|---|
| `title` | `CHECK length(trim(title)) > 0` |
| `category` | closed vocabulary, `CHECK IN (...)` — same list as `daily.vocab.ACTIVITY_CATEGORIES` |
| `detail`, `subject` | free text; `NULL` = not written |
| `start_time`, `end_time` | `'HH:MM'`, `GLOB '[0-2][0-9]:[0-5][0-9]'`. `NULL` = no clock time recorded |
| `minutes` | `NULL` = **unknown**, never 0-for-unknown |
| `importance` | 1–5 or `NULL` |
| `status` | `done` \| `partial` \| `pending` \| `missed`, or `NULL` |

**Why `category` is a closed vocabulary.** Free text becomes forty spellings of
"studying" within a week, and no aggregate over it means anything afterwards.
The cost is that adding a category is a migration; that cost is correct, because
adding one changes what a weekly summary counts.

**Why `minutes` is nullable rather than defaulted.** A duration of `0` would be
summed into a weekly total as though it were a measurement. `NULL` is excluded
from the total and counted separately as `activities_without_duration`, so a
partial sum cannot be read as a complete one.

**Index:** `ix_dayact_day (day_id, seq)`.

#### `day_observations` — structured scales, long format

PK `(day_id, metric)`, `value REAL NOT NULL`.

Nine metrics: `mood`, `energy`, `focus`, `motivation`, `stress`, `workload`,
`productivity`, `sleep_quality` (all 1–5) and `sleep_hours` (0–24). The range is
enforced per metric by one `CHECK` with a `CASE`-style disjunction, which also
closes the metric vocabulary.

**Long format, for the same reason `observations` is.** A student who rated
their mood and skipped everything else has **one row**. There is no
representation of "focus = 0 because the form wanted a number", because there is
no focus row. The wide alternative — nine nullable columns — puts a
plausible-looking number one careless `COALESCE` away.

The range `CHECK` deliberately duplicates `daily.vocab.check_metric`, in the same
spirit as `model_runs.n_dims`: a stray script writing to the file directly must
not be able to route around a stated constraint.

#### `day_reflections` — free text, long format

PK `(day_id, prompt)`, `CHECK prompt IN ('difficult','learned','went_well',
'went_badly','events','notes')`, `CHECK length(trim(body)) > 0`.

An unanswered prompt has **no row**, so "what did you find difficult?" renders as
unanswered rather than as an empty quotation. The non-empty `CHECK` is what keeps
"unanswered" and "answered with nothing" distinguishable.

#### What is deliberately absent

* **No `week_data` JSON blob**, and no JSON column anywhere in this group. A
  student's history in one document cannot be queried, cannot be indexed, and
  cannot be constrained.
* **No stored weekly aggregate.** Rollups are computed on read by
  `daily/aggregate.py`. A stored aggregate can silently disagree with the rows
  beneath it; a recomputed one cannot.
* **No `run_id`, and no FK to any model table.** See above.

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
| `ix_day_profile_week` | `day_records (profile_id, week_index, day_of_week)` | the week view, the daily layer's hot path |
| `ix_dayact_day` | `day_activities (day_id, seq)` | a day's activities, in display order |
| *(implicit)* | `day_records (profile_id, date)` via `UNIQUE` | one day, and date-range reads |

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
| `day_*` | `repository.py`, via `api/routes_daily.py` | `repository.py` | per-day, or cascade from the profile |
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
