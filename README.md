# StudyTwin

**A context-adaptive student digital twin.** A latent state-space model that
maintains a persistent, uncertainty-carrying estimate of one student's
condition, updates it weekly, explains its own movements, and can be run forward
to generate distributions over possible futures.

> **All data in this repository is SYNTHETIC.** The model has never been run on
> real student data. Nothing here is a finding about students. Scenario outputs
> are model-generated and are **not causal estimates**.

```bash
python -m student_twin.store.migrate                       # create the database
python scripts/ingest_run.py --students 250 --weeks 20     # run the model, store it
uvicorn student_twin.api.app:app --port 8000               # serve everything
# → http://127.0.0.1:8000            the product
# → http://127.0.0.1:8000/api/docs   the API, explorable
```

---

## 1. What it is

Conventional student analytics scores a student against a cohort, recomputes
that score every week from scratch, and cannot be run forward. StudyTwin asks a
different question: **how is this student doing relative to their own normal**,
and where might they go next?

The system is defined by four properties, each with a test it can fail:

| # | Property | Meaning | Test | Status |
|---|---|---|---|---|
| 1 | Persistence | the state carries the whole history; nothing is replayed | T1 | **PASS** — `0.00e+00` |
| 2 | Synchronization | it updates as observations arrive | structural | implemented |
| 3 | Generativity | it can be run forward with honest spread | T2 | **PASS** — 88.9% coverage, dispersion 1.63 |
| 4 | Intervenability | a hypothetical action is a model input, not a doctored observation | T3 | **NOT IMPLEMENTED** |
| — | Identifiability | the latent dimensions mean something stable | T4 | **NOT IMPLEMENTED** |

Because T4 has never run, the dimension names *engagement* and *capability* are
**labels of convenience, not validated constructs.**

## 2. Why it exists

A capstone research project asking whether a digital twin — a term used loosely
in education technology — can be given a definition strict enough to fail. Four
properties, four tests, and a rule that a failing test is a result rather than
something to tune away.

Two tests in `tests/test_recovery.py` deliberately **assert current
limitations**. If somebody improves the model, those tests fail. That is
intentional: a suite that only ever goes green cannot tell you when a known
weakness has been fixed.

---

## 3. Architecture

```
adapters ──► pipeline ──► PipelineResult          ← THE MODEL, exactly once
                              │
                              ▼   scripts/ingest_run.py
                       store/ingest.py            ← the ONLY writer of model data
                              ▼
                     SQLite (data/studytwin.db)
                              ▲▼
   a student's own days ──────┘│                  ← RAW input. Separate tables,
   api/routes_daily.py         │                    no run_id, no path into a
                               ▼                    model table.
                     store/repository.py          ← the ONLY reader
                              ▼
                        api/  FastAPI             ← shapes, never estimates
                              ▼
                        web/  vanilla JS          ← renders, never computes
```

**The one-model rule.** The backend does not fit, filter, simulate or score. It
stores what the pipeline produced and serves it. If a value is not in a
`PipelineResult` it does not get a database column, an API field, or a chart.

The daily-record layer is the one thing in the database that a `PipelineResult`
did not produce, and it is held to the mirror-image rule: it is **raw student
input**, it carries no `run_id`, and there is no path from it into a model table.
Weekly summaries over it are computed on read and labelled `derived`. Nothing in
it is consumed by the model, and `model_input: false` says so on every payload -
see [`docs/DAILY_RECORDS.md`](docs/DAILY_RECORDS.md) for why, specifically.

When the landing page needed the *uncertainty* of the prediction step, the
answer was migration `002` adding two columns — not re-implementing
`P_pred = F P Fᵀ + Q` in JavaScript.

---

## 4. Frontend

`web/` — zero dependencies, no build step, no framework. Charts are hand-built
SVG because every charting library treats uncertainty as an optional overlay you
can switch off, and here uncertainty **is** geometry: ribbon thickness *is* the
95% credible interval.

| Screen | Question it answers |
|---|---|
| Landing | What is a digital twin, and why measure against a personal baseline? |
| Twin Home | Where is this student relative to their own normal? |
| Timeline | What happened in a given week, and why did the state move? |
| Deep Dive | What *is* this student's normal? |
| Future Lab | Where might they go? |
| Intervention Lab | What if one model input changed? |
| Model & data | How good is this, and where does it fail? |
| Create your Twin | 10-step onboarding, honest about having zero observations |
| Daily journal | What actually happened each day, week by week — and it persists |

**Visual grammar, applied everywhere:**

| Encoding | Meaning |
|---|---|
| solid + ink | observed |
| dashed + hatched | model-generated |
| dashed amber | the student's own baseline θ |
| teal / coral | above / below θ — **direction, not verdict** |
| thickness | the 95% credible interval |

There is deliberately no green/red "good/bad" language. A student below their
own normal is a fact, not a failure.

**Offline fallback.** If the API is unreachable the frontend falls back to
`web/data.js`, a frozen export of a real run, and shows a non-dismissible banner
saying so. It never renders a placeholder number.

**The Daily journal has no fallback, deliberately.** A write that "succeeds" into
`localStorage` while the server is down is exactly the failure that screen exists
to remove — the student closes the tab believing their week is saved. So it
reports the failure, keeps everything typed in the form, and renders nothing it
did not receive.

---

## 5. Backend

FastAPI over SQLite, no ORM. 27 routes under `/api`, all documented at
`/api/docs` (generated from the same pydantic models the responses are validated
against, so it cannot drift).

Sixteen of them serve model output and are read-only. The other eleven are the
daily-record layer, the only part of the API a student writes to, kept in its own
module so "what can this application change" is answerable by opening one file.

Full reference: [`docs/API_SPEC.md`](docs/API_SPEC.md).
Never done backend work? Start with
[`docs/BACKEND_EXPLAINED.md`](docs/BACKEND_EXPLAINED.md), which assumes nothing.

---

## 6. Database

SQLite, single file, 23 tables. Three invariants:

1. **Every model-derived row carries `run_id`.** A number without a run has no
   seed, no model version and no code revision, so it is unreproducible and
   therefore not a result. `ON DELETE CASCADE` throughout.
2. **Long format over wide**, so an adapter that lacks a channel has *no rows*
   for it rather than zeros — preserving the distinction `CoverageManifest`
   exists to enforce. The daily tables follow the same rule: a metric a student
   did not record has no row, so nothing can render it as a zero.
3. **Raw student input carries no `run_id` and hangs off a person, not a run.**
   The four `day_*` tables belong to a `profile`. They survive a re-ingest, they
   are erased by the same `DELETE` that erases the person, and no foreign key
   connects them to anything the model produced.

Full reference: [`docs/DATABASE_SCHEMA.md`](docs/DATABASE_SCHEMA.md),
[`docs/DAILY_RECORDS.md`](docs/DAILY_RECORDS.md).

---

## 7. The model

$$z_{t+1} = z_t + \alpha \odot (\theta_i - z_t) + B u_t + C d_t + \varepsilon_t$$

Two latent dimensions (three maximum, validated in code). Negative-binomial
counts, Bernoulli submission, Gaussian-on-logit score. Laplace-approximate
Gaussian filter — Newton to the posterior mode, `−H⁻¹` as covariance. Personal
set point by empirical Bayes with an **estimated** shrinkage constant.
Discrete-time hazard readout on a person-period risk set with censoring.

Complete treatment, with every formula tied to the file that implements it:
[`docs/STUDYTWIN_ML_TECHNICAL_REPORT.md`](docs/STUDYTWIN_ML_TECHNICAL_REPORT.md).

---

## 8. Running locally

**Prerequisites:** Python 3.13 (`py -3.13`). The bare `python` on PATH may be
3.11 and lacks scikit-learn.

```bash
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev,dashboard]"
.venv\Scripts\python -m pip install fastapi uvicorn httpx
```

```bash
# 1. database
.venv\Scripts\python -m student_twin.store.migrate

# 2. run the model and persist it   (~30 s)
.venv\Scripts\python scripts\ingest_run.py --students 250 --weeks 20

# 3. serve the API and the frontend together
.venv\Scripts\python -m uvicorn student_twin.api.app:app --port 8000
```

Open <http://127.0.0.1:8000>.

**Frontend only, no backend:** serve `web/` on any static server. The offline
snapshot is used and the UI labels it as such.

---

## 9. Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `STUDYTWIN_DB` | `data/studytwin.db` | SQLite path |
| `STUDYTWIN_WEB_DIR` | `web/` | static frontend directory |
| `STUDYTWIN_SERVE_WEB` | `1` | serve the frontend from the API process |
| `STUDYTWIN_CORS_ORIGINS` | localhost 8777 + 8000 | comma-separated; never `*` |
| `STUDYTWIN_ALLOW_PROFILES` | `1` | enable `POST /api/profiles` |
| `STUDYTWIN_MAX_PAGE_SIZE` | `500` | hard cap on `limit` |
| `STUDYTWIN_LOG_LEVEL` | `INFO` | logging level |

No secret, credential or connection string is hard-coded anywhere.

---

## 10. Tests

```bash
.venv\Scripts\python -m pytest              # everything
.venv\Scripts\python -m pytest tests/test_store.py tests/test_api.py -v
.venv\Scripts\python -m pytest tests/test_recovery.py -v
```

| File | Covers |
|---|---|
| `test_schema.py` | canonical schema, coverage manifest |
| `test_adapters.py` | adapter contracts; OULAD raises rather than falling back |
| `test_features.py` | tier-1 features, at-risk truncation |
| `test_state.py` | filter, predict/update, smoother |
| `test_recovery.py` | ground-truth recovery **and asserted limitations** |
| `test_prediction_and_simulation.py` | forward simulation, T1, T2 |
| `test_readout_regimes.py` | hazard under different signal regimes |
| `test_store.py` | migrations, constraints, ingest atomicity, cascades |
| `test_api.py` | routes, contract shape, errors, honesty guarantees |
| `test_daily.py` | daily storage, week arithmetic, aggregation, student isolation |
| `test_api_daily.py` | daily routes, validation, isolation, no-fabrication guarantees |

---

## 11. Loading data

**Synthetic** (default) — generated from a known process, which is the only
reason validation is possible at all.

**OULAD** — download to `data/raw/oulad/` per `data/README.md`, then:

```bash
.venv\Scripts\python scripts\ingest_run.py --adapter oulad
```

If the files are absent the adapter **raises**. It never silently falls back to
synthetic data.

**⚠️ OULAD has never been run.** Four adapter defects remain unfixed: the `'?'`
missing-value sentinel; 3,538 students colliding on `student_id` across
presentations; negative `date_unregistration`; and the unmapped `ouelluminate`
activity type.

---

## 12. Known limitations

Ranked by how much each should change what you say about the system.

1. **Never run on real data.** Every number describes an estimator's behaviour
   on data generated from a known process.
2. **`C` is assumed, not fitted.** No intervention exists in any dataset here.
   Scenario differences are properties of a declared sensitivity matrix and are
   **not causal evidence**.
3. **T4 has not run** — the dimension names are conventions.
4. **T3 has not run** — the intervention mechanism works; its stability is untested.
5. **Intervals are over-confident.** Nominal 95% covers **72.7%** (engagement).
   Parameter and transfer uncertainty are not modelled at all.
6. **Level dominates trajectory.** Trajectory share 0.364 — "MIXED".
7. **The two-stage fit inflates α and Q.** Fitted α = [0.79, 0.28] vs true
   [0.35, 0.18]. EM is implemented and disabled by default.
8. **The twin loses on calibration.** Its ECE (0.0151) is worse than three of
   four baselines. That row is in the product UI.
9. **No confidence intervals on any metric.** 26 events is a small sample.
10. **No fairness or subgroup analysis.**
11. **No authentication.** Acceptable only while all model data is synthetic; a
    hard blocker before any real cohort is ingested. Daily records raise the
    stakes: they are a real person's own account of their life, kept in a
    database anyone who can reach the port can read given a profile id. Profile
    isolation is enforced on every route and asserted by tests, but a uuid is
    not a credential — binding to localhost is the actual boundary until
    authentication exists.
12. **Daily records feed no model.** They are persisted, aggregated into weekly
    summaries and displayed. Consuming them properly means a new adapter that
    declares the `lifestyle` and `self_report` channels available and is
    refitted (A-07); inventing an emission loading for a self-reported scale
    would be a fabricated result. Stated in the payload as `model_input: false`.

---

## 13. Synthetic vs real data

| | Synthetic | OULAD |
|---|---|---|
| Status | every result here | **NEVER RUN** |
| Ground truth for `z` | yes | impossible — no such column exists |
| Students | 150–250 | 28,785 unique |
| Withdrawal rate | ~4% | 31.2% |
| What results mean | describe the **estimator** | would describe **students** |

The provenance flag travels with the run: `model_runs.synthetic` → API
`provenance.synthetic` → a mandatory chip in the UI. It cannot be dropped
without a test failing.

---

## 14. Research status

**Prototype 1.** Runs end to end on the synthetic fixture. T1 and T2 pass; T3
and T4 are unimplemented. The most important open question is raising the
trajectory share — the twin is still substantially a level detector, which is
Gate 1 weakness 1.

`docs/assumptions.md` is normative for anything the code does (A-01 … A-17,
plus ten forbidden claims). Where this README and that document disagree, that
document wins.

---

## 15. Documentation

| Document | For |
|---|---|
| [`STUDYTWIN_ML_TECHNICAL_REPORT.md`](docs/STUDYTWIN_ML_TECHNICAL_REPORT.md) | the complete model: maths, validation, limits |
| [`DATABASE_SCHEMA.md`](docs/DATABASE_SCHEMA.md) | every table, key, index and constraint |
| [`API_SPEC.md`](docs/API_SPEC.md) | every route, error and security control |
| [`DAILY_RECORDS.md`](docs/DAILY_RECORDS.md) | the daily layer: raw vs derived vs model, and why it feeds no model |
| [`DATA_CONTRACT.md`](docs/DATA_CONTRACT.md) | exactly what the frontend receives |
| [`BACKEND_EXPLAINED.md`](docs/BACKEND_EXPLAINED.md) | backend from zero, no assumed knowledge |
| [`COPILOT_BACKEND_IMPLEMENTATION_PROMPT.md`](docs/COPILOT_BACKEND_IMPLEMENTATION_PROMPT.md) | a spec another agent can implement from |
| [`architecture.md`](docs/architecture.md) | design decisions, including rejected dependencies |
| [`assumptions.md`](docs/assumptions.md) | **normative.** A-01 … A-17 and the forbidden claims |

---

## 16. Forbidden claims

Reproduced from `docs/assumptions.md` because they matter more than anything
else in this file:

* Never claim a causal intervention effect. `C` is assumed (A-08).
* Never call the replay real-time. It is retrospective and weekly (A-12).
* Never call digital traces physiological or multimodal sensing. Permanently out
  of scope.
* Never claim the latent state is the student's real knowledge or motivation.
  T4 has not run (A-06).
* Never report a synthetic number as a finding about students.
* Never fabricate a result. If OULAD is absent, the adapter raises.
