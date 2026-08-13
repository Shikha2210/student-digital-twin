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
- **FastAPI** — the `api/` package is an empty placeholder. Nothing consumes an
  HTTP API yet, and the dashboard imports the pipeline directly.
