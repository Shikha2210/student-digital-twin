# StudyTwin data contract

What the frontend receives, field by field, and what each field is allowed to
claim. The authoritative machine-checked version is
`src/student_twin/api/schemas.py`: FastAPI validates every response against
those models, so a route that starts returning a different shape fails at the
server rather than silently in a browser.

**The rule this document exists to enforce:** the frontend renders. It does not
estimate. Every number below was produced by the research pipeline, written to
the database by `store/ingest.py`, and read back unchanged.

---

## 1. The two producers

The frontend has ONE internal shape - the *view model* - and two producers for
it, both in `web/api.js`:

| Producer | Source | When |
|---|---|---|
| `fromApi(twin, extras)` | `GET /api/students/{id}/twin` and friends | normal |
| `fromSnapshot(D)` | `web/data.js`, a frozen export | API unreachable |

Both emit the identical structure, so no screen knows which it got. When the
snapshot is used, the UI says so in a banner at the top of every screen and in
the sidebar (`Source: snapshot`). A snapshot that silently stands in for live
data is the one failure this layer exists to prevent.

---

## 2. `provenance` - read this before reading anything else

Attached to every payload that carries a model number.

```jsonc
{
  "run_id":           "f7bf16bed5a04444aebe63f2fe0de84c",
  "dataset":          "synthetic",
  "synthetic":        true,
  "seed":             20260813,
  "model_version":    "0.1.0",
  "code_revision":    "1117b83",      // null if git is unavailable - never faked
  "inference_method": "laplace_approximate",
  "created_at":       "2026-08-15T09:12:44+00:00",
  "note":             "SYNTHETIC DATA. Generated from a known latent process..."
}
```

| Field | Meaning | Consequence for the UI |
|---|---|---|
| `synthetic` | No real student is described | Must show the SYNTHETIC chip. Not optional. |
| `run_id` | Which pipeline execution | Every number on screen belongs to exactly one run |
| `seed` | Master seed; all others derive from it | Reproducibility claim |
| `inference_method` | How the state was produced | `laplace_approximate` is an approximation and is labelled |
| `code_revision` | Git short SHA, or `null` | `null` is honest; a placeholder sha would not be |

---

## 3. `TwinPayload` - the composite the dashboard boots from

One request paints one screen. Six round trips would be a worse contract than
one whose shape is documented and validated.

```
GET /api/students/{student_id}/twin
```

```jsonc
{
  "provenance":  { ... },              // section 2
  "student":     { "student_id": "S000021", "context_id": "SYN0_2026A",
                   "n_weeks": 20, "event_observed": false, "event_week": null },
  "dim_names":   ["engagement", "capability"],   // MODEL order, not alphabetical
  "state":       [ StateSeries, ... ],
  "baseline":    [ BaselineEstimate, ... ],
  "hazard":      [ HazardPoint, ... ],
  "observations":[ WeekObservations, ... ],
  "attribution": [ AttributionStep, ... ],
  "scenarios":   [ ScenarioForecast, ... ],
  "own_distribution": [ OwnDistribution, ... ],
  "cohort_theta": [ 0.28, -1.31, 1.15, ... ]
}
```

### 3.1 `dim_names` is ordered

`state[0]`, `baseline[0]` and `own_distribution[0]` are the model's **first**
dimension. This is not cosmetic: an earlier version let SQLite order the rows,
which is alphabetical, so `capability` became `state[0]` and every chart that
took the first series plotted the wrong one. The API now sorts by the run's
declared `dim_names` and `tests/test_api.py` asserts it.

### 3.2 `StateSeries` - INFERRED

```jsonc
{ "dim_name": "engagement", "t": [0,1,...,19],
  "mean": [ ... ], "sd": [ ... ], "method": "laplace_approximate" }
```

* `mean` / `sd` are the marginal filtered posterior `p(z_t | y_{1:t})`.
* `sd` is a standard deviation. Multiply by 1.96 for a nominal 95% interval.
* **This is not the student's knowledge or motivation.** The construct-validity
  test (T4) has never run, so the dimension names are conventions.
* Nominal 95% intervals covered **72.7%** (engagement) and **88.2%**
  (capability) of the true latent state in synthetic validation. The model is
  over-confident and the UI says so beside the chart.

### 3.3 `BaselineEstimate` - the personal set point

```jsonc
{ "dim_name": "engagement", "theta": 0.279, "shrinkage_k": 0.4325,
  "context_mean": 0.031, "n_obs": 20 }
```

There is deliberately **no interval on `theta`**. The two-stage estimator
returns a point estimate; a nullable column that is always null invites somebody
to fill it with something plausible. The Deep Dive screen states this in place
of the row.

### 3.4 `HazardPoint` - a readout, not a verdict

```jsonc
{ "t": 19, "hazard": 0.0734, "cum_risk": 0.4597, "y": 0 }
```

Rows exist only for weeks the student was **at risk**. Weeks after withdrawal
are absent, not zero - treating post-event weeks as negatives is a standard and
serious error that inflates every metric.

### 3.5 `WeekObservations` - inputs

```jsonc
{ "t": 7,
  "channels": { "content_view": 41, "resource": 6, "submission": 1 },
  "features": { "engagement_ratio": 0.62, "inactive_streak": 0, ... } }
```

A **missing key means the dataset does not carry that channel**, not that the
value was zero. That distinction is the whole point of `CoverageManifest` and it
survives into the API.

### 3.6 `AttributionStep` - association, not cause

```jsonc
{ "t": 19, "dim_name": "engagement",
  "prior_mean": 0.113, "prior_sd": 0.577,
  "posterior_mean": -0.774, "posterior_sd": 0.315,
  "shift": -0.887, "residual": -0.240,
  "components": [ { "channel": "content_view", "contribution": -0.659,
                    "observed_value": 3 }, ... ] }
```

**Invariant, asserted in `tests/test_api.py`:**

```
shift == sum(components[i].contribution) + residual
```

`residual` is the higher-order term the first-order decomposition cannot assign.
It is a first-class field and is rendered as its own bar. Normalising it away so
the components sum to 100% is the commonest dishonesty in this genre and the
contract forbids it.

`prior_sd` / `posterior_sd` are what make the "predict widens, update narrows"
claim checkable rather than illustrative. For the demo student, week 19:
predict ±1.131, update ±0.618. Runs ingested before migration `002` have `null`
here; the UI degrades to the posterior SD and prints
`prediction interval not stored for this run` rather than inventing one.

### 3.7 `ScenarioForecast` - MODEL-GENERATED

```jsonc
{ "scenario_id": "...", "label": "Support +1.00",
  "interventions": [ { "name": "engagement_support", "magnitude": 1.0 } ],
  "is_counterfactual": true, "horizon": 8, "n_particles": 600,
  "quantiles": [ { "dim_name": "engagement", "h": [...], "t": [...],
                   "q05": [...], "q50": [...], "q95": [...], "mean": [...] } ],
  "cum_risk": [ 0.020, 0.040, ... ],
  "paths": [ [ ... 8 values ... ], ... 40 paths ... ],
  "disclaimer": "MODEL-GENERATED SCENARIO. NOT A CAUSAL ESTIMATE. ..." }
```

* `disclaimer` is a **required field**, not a UI string. A client cannot render
  a forecast without receiving the sentence that qualifies it.
* `paths` are real individual simulated particles. A fan interpolated between
  `q05` and `q95` would be a picture of a band pretending to be a set of
  outcomes, and the schema documents that it is not one.
* Each magnitude in the slider sweep is a **separate stored simulation**. The
  Intervention Lab never interpolates between two of them.

### 3.8 `OwnDistribution` - arithmetic over inferred values

```jsonc
{ "dim_name": "engagement", "mean": 0.156, "sd": 0.489, "n": 20,
  "weeks_below_theta": 10, "longest_run_below": 6, "current_run_below": 3 }
```

The only place the API does arithmetic the pipeline did not. It is a mean, a
standard deviation and three run-length counts over states the model already
produced, and the docstring in `services.py` says so.

---

## 4. Other payloads

| Route | Model | Notes |
|---|---|---|
| `GET /api/evaluation` | `EvaluationPayload` | metrics, controls, capability tests, `not_implemented` |
| `GET /api/cohort` | `CohortPoint[]` | per-student mean state, theta, last state |
| `GET /api/contrast` | `ContrastPair` | two students whose set points genuinely differ |
| `GET /api/runs/{id}` | `RunDetail` | config + fitted parameters + coverage |
| `GET /api/health` | `Health` | what the database actually contains |

### 4.1 `not_implemented` is a field

```jsonc
"not_implemented": [
  "T3 (intervention stability) - NOT IMPLEMENTED. Requires refitting across seeds...",
  "T4 (identifiability / construct validity) - NOT IMPLEMENTED. Until it runs..."
]
```

`capability_tests` contains only tests that **ran**. A test that never ran is
absent from that array and named in `not_implemented`. An empty row could be
read as a pass; a sentence saying NOT IMPLEMENTED cannot.

---

## 5. What the frontend is forbidden to do

1. **Compute a model quantity.** No filtering, no fitting, no simulation, no
   re-deriving `P_pred = F P Fᵀ + Q`. Migration `002` exists precisely because
   the alternative was recomputing that in JavaScript.
2. **Invent a value for a missing field.** Absent renders as an empty state that
   names what is missing and how to regenerate it.
3. **Show a forecast without its disclaimer.**
4. **Drop `synthetic`.** If the flag is true the label is mandatory.
5. **Present a snapshot as live.** The banner is not dismissible.

## 6. What is deliberately absent

| Absent | Why |
|---|---|
| Credible interval on `theta` | The estimator does not produce one |
| T3 / T4 results | Never implemented |
| Any real-student field | The model has never run on real data |
| Causal effect of an intervention | `C` is assumed, not fitted (A-08) |
| Physiological / multimodal channels | Permanently out of scope; declared unavailable |
| Real-time anything | The replay is retrospective and weekly (A-12) |
