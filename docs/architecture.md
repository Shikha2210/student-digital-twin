# Architecture

## Pipeline

```
raw dataset
    |  adapters/            the only place a dataset's own vocabulary appears
    v
canonical events + context metadata + outcomes + coverage manifest
    |  features/            tier 1 (self-relative) and tier 2 (context)
    v
weekly observations
    |  state/               fit -> recursive Laplace filter
    v
persistent per-student latent state  z_t  with covariance  P_t
    |
    +-- models/readout      discrete-time hazard  (prediction)
    +-- explain.py          per-channel attribution of the state shift
    +-- simulation/         forward particles, intervention vector  (scenarios)
```

**Dependency rule.** `state/`, `models/`, `simulation/` and `evaluation/` must not
import an adapter. That direction of dependency is what makes a second dataset an
adapter rather than a rewrite. There is no import from `adapters` in any of them.

## Canonical schema

```
event(student_id, context_id, t, channel, canonical_type, value)
```

`channel` ∈ behavior · assessment · enrolment · lifestyle · self_report
`canonical_type` ∈ content_view · forum · quiz_attempt · resource · admin ·
submission · score · register · withdraw · activity_log · perceived_load

`lifestyle` and `self_report` are declared but supplied by no current adapter —
see [assumptions A-07](assumptions.md#a-07).

**Why a validated DataFrame rather than pydantic models.** OULAD's clickstream is
~10.6M rows; one Python object per event is not viable. `EventTable` enforces the
contract at construction — required columns, dtypes, allowed categorical values,
channel/type agreement — and rejects extra columns so dataset-specific fields
cannot ride along. `CanonicalEvent` exists for documentation and fixtures.

### The coverage manifest

Every adapter must declare each canonical type available or unavailable;
`CoverageManifest` raises if any is unaccounted for. Without this a transfer
experiment cannot distinguish "this context differs" from "this dataset has no
forum channel", and every cross-dataset result is confounded by instrumentation.

## State model

For student *i*, week *t*, context *c*:

```
transition   z_{t+1} = z_t + alpha * (theta_i - z_t) + B u_t + C d_t + eps_t
observation  counts ~ NegBinomial(exp(b0 + load . z))        behaviour
             submit ~ Bernoulli(sigmoid(b0 + w . z))         assessment
             score  ~ Normal(b0 + w . z, sigma)  on logit    assessment  [A-04]
readout      hazard = sigmoid(gamma . z + gamma_u . u + gamma_0)
```

- `z` is 2-dimensional by default, 3 maximum. `StateConfig` **validates** this;
  it is not advisory.
- `theta_i` is the student's personal set point, an empirical-Bayes shrinkage of
  their own mean toward the context mean. This is the partial pooling that makes
  a new student behave like their cohort rather than like nothing.
- `d_t` is the intervention vector. Identically zero in all observed data.
- Identifiability is imposed structurally: behaviour loads on engagement only,
  score on capability only, submission on both. Without that the dimensions are
  exchangeable.

### Inference

| Track | Method | Status |
|---|---|---|
| Reference | Full-posterior MCMC | **Not implemented.** Interface exists |
| Production | Laplace-approximate Gaussian filter | **Implemented** |
| Simplification | Two-stage parameter fit | See [A-03](assumptions.md#a-03) |

The production filter solves for the mode of the one-step log-posterior by Newton
iteration and takes the negative inverse Hessian as covariance. Every state object
carries `InferenceMethod`, so a chart cannot silently mix methods.

## Explanation

For a Gaussian-approximate update the mean shift decomposes as

```
z_post - z_pred  ~=  P_post @ sum_c grad_c(z_pred)
```

so each channel's contribution is `P_post @ grad_c` — a quantity the filter
already computes. Nothing is fitted and no surrogate model is involved, so the
attribution cannot disagree with the model it explains. The residual (Newton's
higher-order correction) is reported rather than hidden.

## Evaluation

- **Forward-chained** splitting only. `random_split_LEAKY` exists to be reported
  at L0 as evidence of inflation, and is named to be hard to reach for by accident.
- **Baseline ladder** — majority, prior-assessment-only, rolling features, GBM —
  reported in every table alongside the twin.
- **Calibration** is first-class: Brier, ECE, reliability table.
- **Negative controls** — see below.

### Negative controls: a correction made during implementation

"AUC collapses to chance" is *not* the right expectation for every control.
`permute_time` shuffles weeks **within** a student, which preserves that
student's mean state exactly. A model whose signal is the overall engagement
*level* keeps nearly all its AUC — correctly, with no leakage. Treating that as a
leak is a false alarm.

So each control declares its own expectation, and the verdict is three-valued
(`COLLAPSED` / `SURVIVED` / `UNDEFINED`) with a control-specific interpretation.
The one genuine leakage test is `permute_student_identity`.


## Daily records

Added after the API and the frontend, and the only part of the system that
accepts input from a person rather than from an adapter.

**The decision that shaped it.** A day a student lived is not a model quantity,
so it must not live in a model table. Every model-derived table is keyed by
`run_id` and cascade-deletes with its run; a person's account of their Tuesday
that vanished on a re-ingest would be a data-loss bug dressed as provenance. So
the daily tables hang off `profiles` - the only run-independent, person-scoped,
writable table in the schema - and carry no `run_id` at all.

That single choice buys three properties without any further mechanism: the
history survives re-ingests, "delete a user" stays one `DELETE`, and every read
is reachable only through a `profile_id`, which makes cross-account access
structurally impossible rather than a rule to remember.

**Why the aggregation is a module and not a method.** `daily/aggregate.py` takes
plain dicts and returns plain dataclasses, importing nothing from `state/`,
`models/`, `simulation/`, `evaluation/` or any adapter. It is the seam a future
adapter would attach to, and keeping it free of both the store and the API is
what lets it be tested without either.

**Why the model does not consume it, and what would change that.** The filter's
emission models are fitted per channel; a weekly mean of a self-reported 1-5
scale has no fitted loading, no dispersion parameter and no place in
`TwinParameters`. Inventing those would be a fabricated result. The schema
already names the correct route - `Channel.LIFESTYLE` / `ACTIVITY_LOG` and
`Channel.SELF_REPORT` / `PERCEIVED_LOAD`, declared unavailable by every current
adapter - and A-07 already says what to do with it: "adding a survey instrument
later is a new adapter, not a schema migration". So the integration is a new
adapter plus a refit, not a shortcut out of the aggregation module.

**Rejected alternatives.**

| Considered | Rejected because |
|---|---|
| A `week_data` JSON column on a weekly table | Cannot be queried, indexed or constrained; one blob per student is the thing normalisation exists to prevent |
| One wide `day` table with a column per metric | Puts a plausible-looking number one careless `COALESCE` away, and needs a migration per metric. Long format keeps "not recorded" as an absent row |
| Storing the weekly rollup | A stored aggregate can silently disagree with the rows beneath it. Recomputing on read cannot |
| Free-text activity categories | Forty spellings of "studying" within a week, after which no aggregate means anything |
| A `localStorage` fallback for the journal | A write that "succeeds" while the server is down is the exact failure the feature exists to remove |
| A polymorphic owner (profile *or* model student) | A nullable-pair foreign key that no constraint can enforce, to serve a synthetic student who never lived a day |
| A generic `DataSource` plugin interface | Abstraction with one implementation and no second caller. A `source` enum on the row covers the real need |

Full treatment: [`DAILY_RECORDS.md`](DAILY_RECORDS.md).

## Dependencies

numpy, pandas, scipy, scikit-learn. Optional: streamlit + matplotlib
(dashboard), pytest (dev).

Deliberately absent, with reasons:

- **pydantic** — the transport type is a frame, not per-row objects (above).
- **PyYAML** — config is TOML via stdlib `tomllib`.
- **lightgbm / xgboost** — `HistGradientBoostingClassifier` is already in
  scikit-learn and adequate for the baseline.
- **pymc / numpyro / Stan** — needed for the MCMC reference track, which is
  Phase 1. Adding the dependency before the code would be cargo.
- **Airflow / Prefect** — scheduling nobody needs on a fixed dataset.
- ~~**FastAPI**~~ — **REVERSED, 2026-08-15.** The original reason was
  conditional and specific: "the `api/` package is an empty placeholder. Nothing
  consumes an HTTP API yet, and the dashboard imports the pipeline directly."
  That condition no longer holds. `web/` now consumes an HTTP API, and the
  alternative to a framework was hand-rolling routing, validation and error
  handling on `http.server` - writing a worse web framework rather than using
  one. FastAPI also generates `/api/docs` from the same models it validates
  against, which for a project that has to be explained to a panel is worth more
  than a hand-written endpoint list. Added with `uvicorn`.

- ~~**pydantic**~~ (at the HTTP boundary only) — **PARTIALLY REVERSED,
  2026-08-15.** The rejection above remains correct for its actual subject: the
  transport type *inside the pipeline* is a validated frame, not per-row
  objects, and instantiating an object per row for OULAD's 10.6M-row clickstream
  would be absurd. Validating a few dozen fields at an HTTP boundary is a
  different job, and it is the one job pydantic is unambiguously right for.
  `src/student_twin/api/schemas.py` is the machine-checked half of
  `docs/DATA_CONTRACT.md`; nothing inside `state/`, `models/`, `simulation/` or
  `evaluation/` imports it.

- **SQLAlchemy / Alembic** — persistence is stdlib `sqlite3` with numbered SQL
  migrations. The schema is the documentation, every query is a select over a
  composite key, and an ORM would hide exactly the SQL a reviewer wants to
  check. See `docs/DATABASE_SCHEMA.md` for the full argument and the Postgres
  migration path.
