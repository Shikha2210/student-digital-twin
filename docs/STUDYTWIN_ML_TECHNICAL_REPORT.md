# StudyTwin — complete ML / AI technical report

**Version** 0.1.0 · **Report date** 2026-08-15 · **Status** Prototype 1

> **Read this first.** Every quantitative result in this document was produced
> on **SYNTHETIC** data generated from a known process. The model has **never
> been run on real student data**. No claim here is a finding about students,
> about OULAD, or about any real cohort. Where a component is unimplemented this
> report says **NOT IMPLEMENTED** rather than describing what it would do.

All numbers below come from one reproducible run unless stated otherwise:

```
seed 20260813 · 150 students × 20 weeks × 2 contexts · synthetic adapter
python scripts/run_prototype.py --out outputs/synthetic
```

---

## Table of contents

1. [Executive summary](#1-executive-summary)
2. [Problem definition](#2-problem-definition)
3. [Why conventional student analytics is limited](#3-why-conventional-student-analytics-is-limited)
4. [The StudyTwin concept](#4-the-studytwin-concept)
5. [System architecture](#5-system-architecture)
6. [End-to-end data flow](#6-end-to-end-data-flow)
7. [Input data](#7-input-data)
8. [Data preprocessing](#8-data-preprocessing)
9. [Feature engineering](#9-feature-engineering)
10. [Personal baseline estimation](#10-personal-baseline-estimation)
11. [State representation](#11-state-representation)
12. [The prediction step](#12-the-prediction-step)
13. [The update step](#13-the-update-step)
14. [Recursive state estimation](#14-recursive-state-estimation)
15. [Uncertainty modelling](#15-uncertainty-modelling)
16. [Risk calculation](#16-risk-calculation)
17. [Future simulation](#17-future-simulation)
18. [Attribution and explainability](#18-attribution-and-explainability)
19. [Validation](#19-validation)
20. [Leakage testing](#20-leakage-testing)
21. [Recursive consistency testing](#21-recursive-consistency-testing)
22. [Uncertainty calibration](#22-uncertainty-calibration)
23. [Assumptions](#23-assumptions)
24. [Limitations](#24-limitations)
25. [Synthetic vs real data](#25-synthetic-vs-real-data)
26. [Causal interpretation limits](#26-causal-interpretation-limits)
27. [Mathematical formulation](#27-mathematical-formulation)
28. [Computational complexity](#28-computational-complexity)
29. [Backend integration](#29-backend-integration)
30. [API data flow](#30-api-data-flow)
31. [Database design](#31-database-design)
32. [Worked example: one student end to end](#32-worked-example-one-student-end-to-end)
33. [Glossary](#33-glossary)
34. [Future research directions](#34-future-research-directions)

---

## 1. Executive summary

StudyTwin is a **context-adaptive student digital twin**: a latent state-space
model that maintains a persistent, uncertainty-carrying estimate of one
student's condition, updates it weekly, explains its own movements, and can be
run forward to generate distributions over possible futures.

The central design commitment is that a student is compared **to themselves**,
not to a cohort. Every judgement is made against θ, a personal set point fitted
from that student's own history.

**What is validated (on synthetic data with known ground truth):**

| Property | Test | Result |
|---|---|---|
| Persistence | T1 — recursive equals full replay | **PASS**, max difference `0.00e+00` |
| Generativity | T2 — posterior predictive coverage + dispersion | **PASS**, 88.9% coverage, dispersion 1.63 |
| State recovery | correlation with true latent engagement | r = **0.923** |
| Set-point recovery | correlation with true θ | r = **0.935** |
| Absence of leakage | identity permutation | AUC collapses 0.694 → **0.493** |

**What is not:**

| Gap | Status |
|---|---|
| Real student data | **NOT RUN.** OULAD is prepared; four adapter defects remain unfixed |
| T3 intervention stability | **NOT IMPLEMENTED** |
| T4 construct validity | **NOT IMPLEMENTED** — dimension names are conventions |
| Uncertainty calibration | Nominal 95% intervals cover **72.7%** (engagement). Over-confident. |
| Trajectory signal | Week-to-week change recovers at r = **0.558**; level recovers at 0.923 |
| Causal effects | `C` is **assumed**, not fitted. No intervention exists in the data. |

**Headline discrimination** (forward-chained, n = 752 person-periods, 26 events):
twin AUC **0.694** vs prior-assessment 0.608, rolling-features 0.561,
gradient boosting 0.541, majority 0.500. The twin does **not** win on
calibration: its ECE (0.0151) is worse than three of the four baselines.

---

## 2. Problem definition

**Task.** Given a stream of weekly digital-trace observations for a student
enrolled in a course presentation, maintain an estimate of their latent
condition, quantify how far it has departed from their own normal, produce a
per-week probability of a modelled adverse event (withdrawal), and simulate how
the coming weeks could unfold under hypothetical changes.

**Formally.** For student *i* in context *c* at week *t*, given observations
`y_{i,1:t}`, produce:

* a posterior over a latent state, `p(z_{i,t} | y_{i,1:t})`
* a personal set point `θ_i`
* a hazard `h_{i,t} = P(event in week t | survived to t, z_{i,t})`
* a distribution over future trajectories `p(z_{i,t+1:t+K} | y_{i,1:t}, d)` for
  a hypothetical intervention vector `d`
* an attribution: which observation channels moved the state this week

**Why the target is a hazard and not a label.** Dropout is a *timing* problem.
A single end-of-course label discards when a student left and forces students
still enrolled at the cutoff to be scored as negatives, which they are not —
they are **censored**. Person-period framing with censoring handles this
correctly; treating censored students as negatives is a standard and serious
error that inflates every metric.

---

## 3. Why conventional student analytics is limited

A conventional early-warning system computes features over a trailing window and
feeds them to a classifier, once per week, from scratch.

Four specific consequences:

**1. No memory.** Week *t*'s prediction has no formal relationship to week
*t−1*'s. The system cannot say *"this student's estimate moved"* because it has
no previous estimate — only a previous output.

**2. Cohort-relative meaning.** "Twelve logins" is scored against the cohort
distribution. But twelve logins is an ordinary week for one student and a
collapse for another. Measured on this run's cohort, average activity and
deviation-from-own-baseline are close to unrelated — a cohort-relative system
looking at a student who has halved their own activity sees nothing worth
flagging if they started high.

**3. Not generative.** A classifier maps features → probability. It cannot be
run forward, so it cannot answer "what might the next eight weeks look like".

**4. No structural place for an action.** A "what if we intervened" question has
to be simulated by editing an input feature, which is indistinguishable from
fabricating an observation. There is no type-level difference between *what
happened* and *what we are hypothesising*.

StudyTwin's four properties exist to address exactly these four gaps, and each
has a test attached that it can fail.

---

## 4. The StudyTwin concept

A digital twin is a **claim**, not a name. Ours is defined by four properties,
each with a falsification test:

| # | Property | Claim | Test |
|---|---|---|---|
| 1 | **Persistence** | The state carries the full history; nothing is replayed | T1 |
| 2 | **Synchronization** | It updates as observations arrive | (structural) |
| 3 | **Generativity** | It can be run forward with honest spread | T2 |
| 4 | **Intervenability** | A hypothetical action is a model input, structurally separate from an observation | T3 (**NOT IMPLEMENTED**) |

Plus a fifth requirement that is not a property but a precondition:

| 5 | **Identifiability** | The latent dimensions mean something stable | T4 (**NOT IMPLEMENTED**) |

Because T4 has never run, **the names "engagement" and "capability" are labels
of convenience, not validated constructs.** This is stated in the product UI,
in the API (`not_implemented`), and here.

---

## 5. System architecture

```
                    ┌──────────────────────────────────────┐
   RAW DATA         │  adapters/  (synthetic | oulad)      │
   ───────────────► │  → canonical EventTable              │
                    │  → CoverageManifest (total function) │
                    └───────────────┬──────────────────────┘
                                    ▼
                    ┌──────────────────────────────────────┐
   PREPROCESSING    │  schema.py    weekly_pivot           │
                    │  features/tier1.py  at-risk grid     │
                    └───────────────┬──────────────────────┘
                     ┌──────────────┴──────────────┐
                     ▼                             ▼
        ┌────────────────────────┐   ┌────────────────────────────┐
        │ features/tier1.py      │   │ features/context.py        │
        │ 8 self-relative feats  │   │ transition covariates u_t  │
        └───────────┬────────────┘   └─────────────┬──────────────┘
                    ▼                              │
        ┌────────────────────────────────────────┐ │
        │ state/fit.py                           │ │
        │  proxies → emissions → θ_i → α, Q, B   │◄┘
        └───────────┬────────────────────────────┘
                    ▼
        ┌────────────────────────────────────────┐
        │ state/filter.py   TwinFilter           │
        │  predict → update  (Laplace)           │
        │  + RTS smoother                        │
        └───────────┬────────────────────────────┘
                    │  z_{i,t}, P_{i,t}
       ┌────────────┼─────────────────┬─────────────────────┐
       ▼            ▼                 ▼                     ▼
┌─────────────┐┌──────────────┐┌───────────────┐┌──────────────────────┐
│models/      ││explain.py    ││simulation/    ││evaluation/           │
│readout.py   ││attribution   ││forward.py     ││metrics, controls,    │
│hazard h_t   ││+ residual    ││600 particles  ││twin_tests T1..T4     │
└──────┬──────┘└──────┬───────┘└───────┬───────┘└──────────┬───────────┘
       └──────────────┴───────────────┬┴───────────────────┘
                                      ▼
                       ┌──────────────────────────────┐
                       │ store/ingest.py  (only writer)│
                       │            SQLite             │
                       │ store/repository.py (only reader)
                       └──────────────┬───────────────┘
                                      ▼
                       ┌──────────────────────────────┐
                       │ api/  FastAPI, response_model │
                       └──────────────┬───────────────┘
                                      ▼
                       ┌──────────────────────────────┐
                       │ web/  api.js → app.js/charts  │
                       └──────────────────────────────┘
```

**Enforced architectural constraints** (not merely documented):

* `state/`, `models/`, `simulation/`, `evaluation/` must not import an adapter.
* `EventTable` rejects extra columns, so dataset-specific fields cannot leak
  through the schema.
* `CoverageManifest` raises unless every canonical type is accounted for.
* `StateConfig` raises if `n_dims` is outside 1–3.
* There is **no tier-3 feature builder**. The absence is the enforcement.

---

## 6. End-to-end data flow

| # | Stage | Module | Input → Output |
|---|---|---|---|
| 1 | Load | `adapters/` | raw files → `EventTable`, `OutcomeTable`, `CoverageManifest` |
| 2 | Pivot | `schema.weekly_pivot` | long events → one row per (student, context, week) |
| 3 | Truncate | `features.tier1._at_risk_grid` | dense grid → at-risk grid only |
| 4 | Observations | `features.tier1.observation_frame` | → counts + submission + score |
| 5 | Features | `features.tier1.build_tier1` | → 8 self-relative features |
| 6 | Context | `features.context` | → transition covariates `u_{c,t}` |
| 7 | Fit | `state/fit.fit_twin` | → `TwinParameters` (α, Q, B, loadings, φ, θ_i) |
| 8 | Filter | `state/filter.TwinFilter` | → `StateTrajectory` per student |
| 9 | Readout | `models/readout` | → person-period frame + hazard |
| 10 | Explain | `explain.py` | → per-week attribution + residual |
| 11 | Simulate | `simulation/forward` | → particle cloud, quantiles, cumulative risk |
| 12 | Evaluate | `evaluation/` | → metrics, controls, T1/T2 |
| 13 | Persist | `store/ingest.py` | → SQLite |
| 14 | Serve | `api/` | → JSON |
| 15 | Render | `web/` | → pixels |

Stages 1–12 are the model. Stages 13–15 are transport. **The model appears
exactly once.**

---

## 7. Input data

### 7.1 The canonical event schema

Every adapter must emit the same table. `EventTable` validates it and **rejects
extra columns**, so an OULAD-specific field cannot silently become a feature.

| Column | Type | Meaning |
|---|---|---|
| `student_id` | str | opaque identifier |
| `context_id` | str | course presentation |
| `t` | int | week index within the context |
| `canonical_type` | enum | one of the canonical types below |
| `value` | float | count, indicator, or normalised score |

Canonical types: `content_view`, `forum`, `quiz_attempt`, `resource`, `admin`,
`register`, `withdraw`, `submission`, `score`, `activity_log`, `perceived_load`,
plus permanently-unavailable declarations for physiological and multimodal
channels.

### 7.2 CoverageManifest — a total function

Every adapter must declare **every** canonical type as available or unavailable.
`CoverageManifest.__post_init__` raises otherwise:

```
coverage manifest for 'oulad' does not account for {…}
```

**Why this matters.** Without it, a channel absent from the manifest is
ambiguous between "the dataset does not carry it" and "nobody thought about it".
That ambiguity is how a model quietly imputes zeros for a channel that was never
collected. Physiological and multimodal sensing are declared **permanently
unavailable** — they are in the schema so that no adapter can pretend to supply
them, and they are out of scope for this project.

### 7.3 The synthetic adapter

Generates a cohort from a **known** process (`adapters/synthetic.py`). Its
ground-truth parameters are not shown to the estimator:

```python
TRUE_ALPHA    = [0.35, 0.18]
TRUE_Q        = diag([0.20, 0.10])
TRUE_LOADINGS = { content_view: (2.85, 0.95), forum: (1.30, 0.70),
                  quiz_attempt: (0.90, 0.55), resource: (1.90, 0.80) }
TRUE_SUBMIT   = (1.20, 0.80, 0.45)
TRUE_SCORE    = (0.15, 0.85, 0.45)
TRUE_HAZARD   = (-3.4, -0.85, -0.35)
```

**This is the only reason validation is possible at all.** The latent state is
unobservable, so it cannot be checked against real data — there is no
ground-truth column in OULAD or anywhere else. Synthetic students from a known
process are the substitute, and every recovery number in §19 depends on them.

### 7.4 OULAD — prepared, NOT RUN

| | |
|---|---|
| Students | 32,593 rows, 28,785 unique |
| VLE interactions | 10,655,280 rows |
| Presentations | 22 |
| Withdrawal rate | 31.2% |
| **Status** | **The adapter has never executed against real data.** |

Four defects known and unfixed:

1. `'?'` used as a missing-value sentinel in several columns.
2. 3,538 students appear in multiple presentations and collide on `student_id`.
3. Negative `date_unregistration` values (pre-start withdrawal).
4. `ouelluminate` activity type has no canonical mapping.

---

## 8. Data preprocessing

### 8.1 Weekly pivot

`schema.weekly_pivot` reshapes long events to one row per (student, context,
week), with one column per canonical type present.

**Fixed defect worth recording:** missing `SCORE` was originally filled with
`pd.NA`, producing an `object` dtype that silently broke rolling aggregation
downstream. It is now `float("nan")` with an explicit `astype("float64")`.

### 8.2 The at-risk grid — the single most consequential preprocessing decision

A naive dense grid gives every student a row for every week of the presentation.
For a student who withdrew in week 6 of a 20-week course, that fabricates **14
weeks of all-zero activity** that never happened.

`_at_risk_grid` truncates each student's grid at their withdrawal week.

**Measured impact.** Before truncation, ~30.5% of observation rows were
fabricated post-withdrawal zeros. Those spurious zeros inflated **every**
emission loading by a near-uniform ≈2.2×, and T2 failed with a dispersion ratio
of 3.90 (bands ~4× too wide).

| Channel | Loading before fix | After fix | True |
|---|---|---|---|
| `content_view` | 2.121 (2.23×) | 1.077 (1.13×) | 0.95 |
| `forum` | 1.533 (2.19×) | 0.718 (1.03×) | 0.70 |
| `quiz_attempt` | 1.327 (2.41×) | 0.572 (1.04×) | 0.55 |
| `resource` | 1.727 (2.16×) | 0.841 (1.05×) | 0.80 |

T2 went 3.90 → 1.63 and passed **without any threshold being touched**.
`tests/test_recovery.py::test_emission_loadings_are_not_inflated` is a
regression guard: it fails if any ratio leaves 0.65–1.35.

> **In simple words.** If a student leaves in week 6, the model must not be told
> they did nothing in weeks 7–20. They did not "do nothing" — they were not
> there. Telling the model otherwise made it believe activity mattered twice as
> much as it does.

---

## 9. Feature engineering

### 9.1 The tier system

| Tier | Definition | Builder | Rationale |
|---|---|---|---|
| **1** | Self-relative, dataset-agnostic | `features/tier1.py` | transfers across institutions by construction |
| **2** | Context covariates | `features/context.py` | properties of the course, not the student |
| **3** | Institution-specific | **none exists** | a tier-3 feature cannot transfer; the absence is the enforcement |

### 9.2 The eight tier-1 features

| Feature | Definition |
|---|---|
| `engagement_ratio` | this week's activity ÷ own trailing 4-week mean |
| `engagement_slope` | OLS slope over a 3-week window |
| `engagement_volatility` | SD over a 3-week window |
| `activity_entropy` | Shannon entropy over the channel mix |
| `inactive_streak` | consecutive weeks with zero activity |
| `submission_rate` | submissions ÷ assessments due |
| `score_vs_own_baseline` | score minus own running mean |
| `post_setback_recovery` | activity recovery after a drop |

Every one is a **ratio, difference or shape** relative to that student's own
history. None is an absolute count. That is what "tier 1" means and why these
features are the only ones claimed to transfer.

> **In simple words.** A feature that says "42 clicks" only means something if
> you know what 42 means for this student at this university. A feature that
> says "0.6× your own normal" means the same thing everywhere.

---

## 10. Personal baseline estimation

### 10.1 The formula

Implemented in `state/model.py::TwinParameters.setpoint` and applied at fit time
in `state/fit.py`.

$$\theta_i \;=\; \frac{n_i\,\bar{y}_i \;+\; k\,\mu_c}{n_i + k},
\qquad k \;=\; \frac{\sigma^2_{\text{within}}}{\tau^2_{\text{between}}}$$

| Symbol | Meaning | Where it comes from |
|---|---|---|
| `θ_i` | student *i*'s personal set point | output |
| `ȳ_i` | student *i*'s own mean proxy | their data |
| `n_i` | number of observed weeks | their data |
| `μ_c` | context (cohort) mean | all students in that context |
| `σ²_within` | average within-student variance | one-way random-effects decomposition |
| `τ²_between` | between-student variance of the means | corrected for sampling noise |
| `k` | shrinkage constant | **estimated**, not configured |

### 10.2 Estimating the variance components

```python
sigma_w2 = within-student variance, averaged over students
n_bar    = mean weeks per student
tau2     = max(Var(student means) - sigma_w2 / n_bar, 1e-3)
shrink   = clip(sigma_w2 / tau2, 0.05, 200.0)
```

The `− σ²_w / n̄` correction matters: `Var(ȳ_i) = τ² + σ²_w/n`, so the raw
variance of the student means **over-states** the true between-student spread by
the sampling noise those means carry.

### 10.3 Why estimating `k` rather than fixing it is the whole point

Measured on a fixture whose true set-point SD was **0.242**, a fixed `k` produced
estimates with SD **0.543** — more than twice the real variation, almost all of
it noise. Everything downstream that subtracts θ then subtracts that noise.

**Measured on this run:**

| Dimension | σ²_within | τ²_between | k |
|---|---|---|---|
| engagement | 0.319 | 0.738 | 0.433 |
| capability | 0.328 | 0.272 | 1.205 |

Engagement `k` = 0.43: students genuinely differ, so trust each student's own
history. Capability `k` = 1.21: more pooling, because capability is observed far
more sparsely (only when a score exists). A single fixed `k` cannot express
both.

**Recovery:** θ correlates with the true set point at **r = 0.935**
(engagement), **r = 0.663** (capability), n = 150.

> **In simple words.** θ is "your normal". It is your own average, pulled a bit
> toward your cohort's average. How much it is pulled depends on how different
> students actually are in this cohort — the data decides, not us. A student with
> two weeks of history looks mostly like their cohort; a student with twenty
> looks mostly like themselves.

**Numerical example.** Take `ȳ_i = 1.40`, `n_i = 20`, `μ_c = 0.03`,
`k = 0.433`:

$$\theta_i = \frac{20(1.40) + 0.433(0.03)}{20 + 0.433} = \frac{28.013}{20.433} = 1.371$$

With only 2 weeks of history: `(2(1.40) + 0.433(0.03))/2.433 = 1.156` — pulled
noticeably further toward the cohort, which is correct, because two weeks is
weak evidence about a person.

---

## 11. State representation

### 11.1 What the state is

$$z_{i,t} \in \mathbb{R}^d, \qquad d = 2 \text{ by default}, \ 3 \text{ maximum}$$

Dimension names by convention: `engagement`, `capability`.

The posterior is approximated as Gaussian:

$$p(z_{i,t} \mid y_{i,1:t}) \approx \mathcal{N}(m_{i,t}, P_{i,t})$$

`TwinState` carries `mean`, `cov`, `method` (`InferenceMethod`) and
`n_observations`. The method label travels with the data because a plot that
mixes inference methods without saying so is a misreport.

### 11.2 Why 2 dimensions, maximum 3

`StateConfig.__post_init__` **raises** outside 1–3:

> `n_dims=7 violates the Gate 1 constraint of 2 by default, 3 maximum.
> Higher-dimensional states fitted to weekly counts are not identifiable and
> will fail test T4.`

This is validated rather than documented because the temptation to add
dimensions when the model underperforms is exactly what the constraint resists.

### 11.3 Identifiability by structure

Not by regularisation:

* behaviour counts load on **engagement only**
* score loads on **capability only**
* submission loads on **both**

Without that structure the two dimensions are exchangeable and T4 could never
pass. **T4 has not run**, so this is a necessary condition that has been met,
not a validated result.

> **In simple words.** The twin is two numbers plus how sure it is about them.
> Those two numbers are named "engagement" and "capability" — but we have not
> yet proved they measure what those words mean, so treat them as coordinates,
> not diagnoses.

---

## 12. The prediction step

### 12.1 Mean

`state/model.py::transition`

$$z_{t+1} \;=\; z_t \;+\; \alpha \odot (\theta_i - z_t) \;+\; B u_t \;+\; C d_t \;+\; \varepsilon_t,
\qquad \varepsilon_t \sim \mathcal{N}(0, Q)$$

| Symbol | Meaning | Status |
|---|---|---|
| `α` | per-dimension reversion rate ∈ [0,1] | **fitted** |
| `θ_i` | personal set point | **fitted** (§10) |
| `B` | effect of context covariates | **fitted** |
| `u_t` | context covariates (assessment due, weeks remaining) | observed |
| `C` | intervention sensitivity | **ASSUMED, NOT FITTED** (A-08) |
| `d_t` | intervention vector | **zero in all real data** |
| `Q` | process noise covariance | **fitted** |

`α ∈ [0,1]` is validated in `TwinParameters.__post_init__` — it is a per-week
reversion *fraction*, so a value outside that range is meaningless.

### 12.2 Covariance

`state/filter.py::TwinFilter.predict`

$$F = \frac{\partial z_{t+1}}{\partial z_t} = \operatorname{diag}(1 - \alpha)
\qquad
P_{t+1|t} = F\,P_{t|t}\,F^{\mathsf T} + Q$$

**Uncertainty always grows at this step.** `F P Fᵀ` shrinks the previous
covariance (since `|1−α| < 1`) but `+Q` adds process noise, and Q dominates.

**Measured, demo student, week 19:** posterior SD 0.315 → prior SD 0.577.
As a 95% interval: **±0.618 → ±1.131**. That widening is drawn directly on the
landing page and is read from the database, not recomputed in the browser.

> **In simple words.** A week goes by. The model assumes you drift back toward
> your own normal a bit, and it becomes less sure where you are, because it has
> not seen anything yet.

**Numerical example.** `α = 0.79`, `θ = 0.279`, `z_t = −0.774`, `Q₁₁ = 0.305`,
`P_t = 0.315² = 0.0992`:

* mean: `−0.774 + 0.79(0.279 − (−0.774)) = −0.774 + 0.832 = 0.058`
* covariance: `(1−0.79)² × 0.0992 + 0.305 = 0.0044 + 0.305 = 0.309` → SD 0.556

(The stored value is 0.577; the small difference is `B u_t` and the fact that
`α` differs slightly per dimension.)

---

## 13. The update step

### 13.1 Why there is no closed form

The emissions are **not Gaussian** — counts are negative binomial, submission is
Bernoulli. So there is no Kalman gain. The update solves for the **mode** of the
one-step log-posterior by Newton iteration and takes the negative inverse
Hessian at the mode as the covariance. This is a **Laplace approximation** and
every state it produces is labelled `InferenceMethod.LAPLACE`.

### 13.2 The objective

$$\log p(z \mid y_t) \;\propto\; -\tfrac12 (z - m_{t|t-1})^{\mathsf T} P_{t|t-1}^{-1} (z - m_{t|t-1}) \;+\; \sum_{c \in \text{observed}} \log p(y_{c,t} \mid z)$$

Newton iteration (`max_newton_iters = 25`, `newton_tol = 1e-8`):

$$g(z) = -P^{-1}_{t|t-1}(z - m_{t|t-1}) + \sum_c \nabla_z \log p(y_c \mid z)$$
$$H(z) = -P^{-1}_{t|t-1} + \sum_c \nabla^2_z \log p(y_c \mid z)$$
$$z \leftarrow z - H^{-1} g$$

Then

$$m_{t|t} = \hat z, \qquad P_{t|t} = \left(-H(\hat z)\right)^{-1}$$

A non-positive-definite result from an extreme observation is repaired by
eigenvalue shifting rather than being allowed through.

### 13.3 The three emission likelihoods

`state/emissions.py` — each returns `(loglik, gradient, Hessian)` in state
space, which is precisely what the Laplace update needs.

**(a) Behaviour counts — negative binomial, log link**

$$\mu = \exp(b_{0,c} + w_c^{\mathsf T} z), \qquad
y_c \sim \text{NegBin}(\mu, \phi_c), \qquad
\operatorname{Var}(y) = \mu + \mu^2/\phi$$

$$\frac{\partial \ell}{\partial \eta} = y - \frac{(y+\phi)\mu}{\phi + \mu},
\qquad
\frac{\partial^2 \ell}{\partial \eta^2} = -\frac{(y+\phi)\phi\mu}{(\phi+\mu)^2}$$

*Why not Poisson.* Poisson asserts variance = mean, which weekly click counts
violate badly. The resulting over-confidence would propagate straight into the
state covariance and make the twin's uncertainty a fiction.

Fitted dispersions this run: `content_view` φ = 19.7, `forum` 2.55,
`quiz_attempt` 2.56, `resource` 2.47. Low φ = more extra-Poisson variance.

**(b) Submission — Bernoulli, logit link**

$$p = \sigma(b_0 + w^{\mathsf T} z), \qquad
\nabla_z \ell = (y - p)\,w, \qquad
\nabla^2_z \ell = -p(1-p)\,w w^{\mathsf T}$$

A zero here is an **observation**, not a gap. That is the entire reason this
channel exists separately from `score`.

**(c) Score — Gaussian on the logit scale · PROTOTYPE SIMPLIFICATION (A-04)**

$$\operatorname{logit}(y) \sim \mathcal{N}(b_0 + w^{\mathsf T} z, \sigma^2)$$

The specification calls for a **Beta** likelihood with mean `σ(wᵀz)`. This
Gaussian-on-logit shares the mean structure and the support constraint but has
**constant** rather than mean-dependent variance. Consequence, stated honestly:
under-dispersion near the bounds, so scores concentrated at 0 or 1 are modelled
with too much confidence. Replacing it requires no change outside that one
function.

### 13.4 What the update does to uncertainty

**Measured, demo student, week 19:** prior ±1.131 → posterior ±0.618.
Across all 19 transitions of that student, predict widened and update narrowed
in **19 of 19** weeks.

> **In simple words.** The model had a guess and was unsure. Then it saw what
> you actually did. It moves its guess toward the evidence and becomes more
> confident. How far it moves depends on how much it trusts each signal.

---

## 14. Recursive state estimation

### 14.1 The loop

```
for each week t:
    m_pred, P_pred = predict(state_{t-1}, θ, u_t, d_t)     # §12
    state_t        = update(m_pred, P_pred, y_t)           # §13
    state_{t-1}    = state_t                               # the whole point
```

No history is replayed. Last week's posterior *is* this week's prior. That
sentence is the definition of the persistence property, and T1 tests it.

### 14.2 The RTS smoother

`TwinFilter.smooth` runs a Rauch–Tung–Striebel pass over the filter's Gaussian
approximations:

$$J_t = P_{t|t} F^{\mathsf T} P_{t+1|t}^{-1}$$
$$m_{t|T} = m_{t|t} + J_t (m_{t+1|T} - m_{t+1|t})$$
$$P_{t|T} = P_{t|t} + J_t (P_{t+1|T} - P_{t+1|t}) J_t^{\mathsf T}$$

Used by the (implemented but **disabled by default**) EM refinement. Fitting
transition parameters on *filtered* states double-counts observation noise as
process noise, which is what inflates α and Q — see §24.

---

## 15. Uncertainty modelling

Four sources, of which **two are modelled and two are not**:

| Source | Modelled? |
|---|---|
| Process noise `Q` | **yes** |
| Observation noise (per-channel likelihood) | **yes** |
| **Parameter uncertainty** (α, Q, loadings are point estimates) | **NO** |
| **Transfer / structural uncertainty** (is the model family right?) | **NO** |

The reported intervals are therefore **conditional on the fitted parameters
being exactly correct**, which they are not. This is why §22's coverage numbers
are below nominal and why the UI carries the warning beside the chart rather
than in a footnote.

Uncertainty is encoded as **geometry** everywhere in the product — ribbon
thickness *is* the credible interval — specifically so that it cannot be
switched off the way a charting library would allow.

---

## 16. Risk calculation

### 16.1 The hazard

`models/readout.py` — a **readout**, not an emission. It does not update the
state. Keeping it out of the filter is what makes "prediction is a byproduct of
state" true in the code and not just in the report.

$$h_{i,t} = \sigma\!\left(\gamma^{\mathsf T} z_{i,t} + \gamma_{\text{dev}}^{\mathsf T} \mathrm{dev}_{i,t} + \gamma_u^{\mathsf T} u_{c,t} + \gamma_0\right)$$

Fitted by L2-regularised logistic regression (`C = 1.0`) on the person-period
frame.

### 16.2 The person-period risk set

A student who withdraws in week 6 contributes weeks 0…6, with `y = 1` only in
week 6. A student who completes contributes every observed week with `y = 0`.
**Weeks after withdrawal do not exist** — they are not zeros.

### 16.3 The deviation term, and why it is there

$$\mathrm{dev}_{i,t} = z_{i,t} - \frac{1}{t+1}\sum_{s \le t} z_{i,s}$$

An **expanding** mean over weeks ≤ t, not the fitted set point. Using θ would
leak the future into a forward-chained split, because θ is estimated from the
student's whole history.

**Why it exists.** Without it the readout is linear in `z` alone and cannot
represent a hazard that depends on *departure from a personal norm*. Measured on
a trajectory-dominant fixture, the full model scored **below** a deviation-only
model (0.520 vs 0.564) because the information was present but inexpressible.

### 16.4 Cumulative risk

$$S_{i,t} = \prod_{s \le t} (1 - h_{i,s}), \qquad R_{i,t} = 1 - S_{i,t}$$

Cumulative by construction, so it only rises. Labelling it as such matters —
a rising curve is not deterioration.

> **In simple words.** Each week the model gives a probability that this is the
> week the student leaves. Survival is the chance they have not left by now, and
> cumulative risk is one minus that. It is a probability under this model — not
> a verdict, and not a prediction about a person.

---

## 17. Future simulation

`simulation/forward.py::simulate_forward`

```
1. draw N particles from the CURRENT POSTERIOR  N(m_T, P_T)
2. for h = 1..K:
       z ← transition(z, θ, params, u, d) + Cholesky(Q) · ε
       emit observations from z through the fitted emission models
       evaluate the hazard readout at z
3. return quantiles, cumulative risk, and individual paths
```

Defaults: **600 particles, 8-week horizon**.

**Why particles are drawn from the posterior, not from the mean.** Collapsing to
the posterior mean would discard the uncertainty already accumulated and make
the twin look more confident than it is. The bands must widen with **both**
process noise and existing state uncertainty.

**Count emission uses the NegBin's gamma–Poisson mixture** rather than a normal
approximation:

```python
lam = rng.gamma(phi, mu / phi)
y   = rng.poisson(lam)
```

**Individual paths are retained** (40 per student per scenario) so the fan chart
draws real trajectories. A fan interpolated between q05 and q95 would be a
picture of a band pretending to be a set of outcomes.

**Every scenario magnitude is a separate simulation.** The Intervention Lab
slider has seven stops (0.00 … 1.50) and each is its own 600-particle run stored
in its own `scenario_id`. Nothing is interpolated.

---

## 18. Attribution and explainability

### 18.1 The decomposition

`explain.py` — **structural, not post-hoc**. No surrogate model, nothing fitted.

For a Gaussian-approximate Bayesian update the mean shift decomposes as

$$z_{\text{post}} - z_{\text{pred}} \;\approx\; P_{\text{post}} \sum_c \nabla_z \log p(y_c \mid z)\big|_{z = z_{\text{pred}}}$$

so channel *c*'s contribution is

$$\text{contrib}_c = P_{\text{post}} \, \nabla_z \log p(y_c \mid z_{\text{pred}})$$

— a quantity the filter already computes on its way to the posterior. **The
attribution therefore cannot disagree with the model it is explaining**, which
is not true of SHAP or LIME on a black box.

Gradients are evaluated at the **prior** mean: the question is *"what did this
week's evidence pull toward"*, not *"what does the posterior imply"*.

### 18.2 The residual

$$\text{residual} = (z_{\text{post}} - z_{\text{pred}}) - \sum_c \text{contrib}_c$$

Exactly Newton's higher-order correction. It is reported as its own bar,
labelled *not attributable*, and it is **never** normalised away.

Invariant asserted in both `tests/test_store.py` and `tests/test_api.py`:

```
shift == Σ contributions + residual
```

**Real example** (from `scripts/run_prototype.py`, student S000000, week 14):

```
Week 14: engagement state rose by 0.993
  content views  (observed 98)  pushed up   by 1.223
  resource access(observed  4)  pushed down by 0.036
  quiz activity  (observed  6)  pushed up   by 0.025
  −0.240 not attributable to a single channel (higher-order term in the update)
```

1.223 − 0.036 + 0.025 − 0.240 = 0.972 ≈ 0.993 (remaining channels omitted from
the printed top-3).

### 18.3 What this is NOT

It reports **which observations moved a fitted latent coordinate, in the model's
own units**. It is not a statement about motivation, effort, or knowledge, and
it is **association, not cause**.

---

## 19. Validation

### 19.1 Ground-truth recovery (`tests/test_recovery.py`)

Only possible because the synthetic process is known.

| Quantity | Measured | Test threshold |
|---|---|---|
| Engagement state recovery | **r = 0.9232** | > 0.85 |
| Capability state recovery | **r = 0.7442** | > 0.50 |
| Engagement **trajectory** (first differences) | **r = 0.5584** | > 0.40 |
| Capability **trajectory** | **r = 0.1884** | < 0.40 — *asserted to be weak* |
| Engagement set-point recovery | **r = 0.9347** | > 0.80 |
| Interval coverage, engagement (nominal 95%) | **0.727** | 0.70 < c < 0.93 |
| Interval coverage, capability | **0.882** | as above |
| Loading ratios (fitted ÷ true) | 1.03 – 1.13 | 0.65 – 1.35 |

Two of these tests **assert a limitation**:

* `test_capability_trajectory_is_essentially_unrecovered` asserts r < 0.40.
* `test_state_intervals_are_overconfident` asserts some coverage < 0.93.

If somebody fixes the model, those tests **fail**. That is deliberate: a test
suite that only ever goes green cannot tell you when a known weakness has been
resolved, and a silent improvement is as unreportable as a silent regression.

### 19.2 Predictive comparison

Forward-chained splits, identical folds for every model.
n = 752 person-periods, 26 events.

| Model | AUC | Brier | ECE |
|---|---|---|---|
| **twin_state** | **0.6944** | 0.0338 | 0.0151 |
| prior_assessment | 0.6076 | 0.0333 | **0.0034** |
| rolling_features | 0.5614 | 0.0334 | **0.0015** |
| gbm | 0.5408 | 0.0371 | 0.0315 |
| majority | 0.5000 | 0.0334 | 0.0074 |

**The twin wins on discrimination and loses on calibration.** Its ECE is worse
than three of four baselines. That row is in the product UI and in this report
because deleting it would be the dishonest choice — and because a
well-calibrated wrong answer is still wrong.

### 19.3 Level vs trajectory decomposition

The question "is the twin actually using its dynamics, or is it a level
detector?" is answered numerically rather than inferred:

| Readout input | AUC |
|---|---|
| full state | 0.7146 |
| **level only** (expanding mean) | 0.7108 |
| **deviation only** (z − level) | 0.6206 |

$$\text{trajectory share} = \frac{\text{lift}_{\text{dev}}}{\text{lift}_{\text{level}} + \text{lift}_{\text{dev}}} = \frac{0.1206}{0.2108 + 0.1206} = \mathbf{0.364}$$

**Verdict: MIXED — level dominates but trajectory contributes.**

This is a genuine improvement over the earlier prototype, where the share was
0.056 (LEVEL-DRIVEN). It remains the most important open weakness.

---

## 20. Leakage testing

`evaluation/negative_controls.py`. Each control states **in advance** what it
expects, and the verdict is three-valued.

| Control | Destroys | AUC | Expected | Verdict |
|---|---|---|---|---|
| `permute_student_identity` | trajectory→outcome linkage | 0.4934 | COLLAPSE | **COLLAPSED** ✓ |
| `permute_time` | ordering within a student | 0.7259 | — | SURVIVED |
| `permute_context_labels` | student→context assignment | 0.6944 | — | SURVIVED |

**`permute_student_identity` is the leakage test.** It collapsed from 0.694 to
0.493 — chance. There is no evidence of leakage.

**`permute_time` surviving is not a leak, and it is not nothing.** Shuffling
weeks within a student preserves that student's mean exactly. Survival therefore
says the readout is driven by *level* rather than *trajectory shape* — the same
finding §19.3 quantifies directly. `permute_time` alone cannot distinguish
"level-driven" from "leaking"; the decomposition can, which is why both exist.

---

## 21. Recursive consistency testing (T1)

**What is tested.** Feed the filter one week at a time, carrying only the state
object between calls, and compare the final state to running the filter over the
full history in one call.

**Result:** max |recursive − full replay| over state dimensions =
**0.00e+00** (threshold 0.02). **PASS.**

**What passing means.** The state is a sufficient statistic for the student's
history. Nothing is replayed. The twin has memory in the formal sense.

**What passing does NOT mean.** It does not mean the state is *correct*, or
*useful*, or that it measures anything a person would recognise. For a correctly
implemented filter this is true by construction, so T1 is primarily a
**regression guard**: it catches an implementation that secretly depends on
replayed history, or a state object that is not actually carrying information
forward.

**Consequence if it failed:** the state is bookkeeping over a feature window,
and the system should be described as such rather than as a twin.

---

## 22. Uncertainty calibration (T2 and interval coverage)

### 22.1 T2 — generativity

Consumes `posterior_predictive_check` across students. **Three ways to fail, in
both directions:**

| Failure | Meaning |
|---|---|
| coverage far from nominal | the bands are the wrong width |
| dispersion ratio ≪ 1 | simulated futures **smoother** than real ones — over-confident |
| dispersion ratio ≫ 1 | bands far too wide — coverage looks excellent precisely because the forecast says almost nothing |

A coverage-only test would wave the third case through. That is why the test is
two-sided.

**Result:** 90% band covered **88.9%** of held-out observations across 33
students (target 90% ± 7%); mean dispersion ratio **1.63** (acceptable
0.5–2.0). **PASS.**

**History worth recording.** T2 previously failed at dispersion 3.90. The cause
was not the process-noise hypothesis we started with — it was the fabricated
post-withdrawal zeros of §8.2. Fixing the data bug moved 3.90 → 1.63 and T2
passed **without any threshold being changed**.

### 22.2 State interval coverage — a real failure

| Dimension | Nominal | Measured |
|---|---|---|
| engagement | 95% | **72.7%** |
| capability | 95% | **88.2%** |

**The model is over-confident about engagement.** A stated 95% interval contains
the truth about 73% of the time.

**Why.** §15: parameter uncertainty and transfer uncertainty are not modelled at
all. The intervals are conditional on α, Q and the loadings being exactly right.

This is displayed beside the chart it qualifies on Twin Home, not in a footer.

---

## 23. Assumptions

Full register: `docs/assumptions.md` (A-01 … A-17). The ones that change how a
result may be read:

| ID | Assumption | Consequence |
|---|---|---|
| **A-03** | Two-stage estimation instead of joint | emission loadings conditioned on a noisy proxy → attenuation. EM implemented, **disabled by default** |
| **A-04** | Gaussian-on-logit instead of Beta for score | under-dispersion near 0 and 1 |
| **A-06** | Latent dimensions are **not** validated constructs | T4 has not run; names are conventions |
| **A-08** | Intervention sensitivity `C` is **assumed, not fitted** | **no scenario output is a causal estimate** |
| **A-12** | The replay is **retrospective**, weekly | nothing in this product is real-time |
| — | Emissions conditionally independent given `z` | may be violated (a burst of clicks correlates across channels) |
| — | Gaussian process noise, linear-Gaussian transition | a step change is modelled as several improbable draws |
| — | The Laplace approximation is adequate | unchecked against MCMC; the reference track is **NOT IMPLEMENTED** |

---

## 24. Limitations

**Ranked by how much they should change what you say about the system.**

1. **Never run on real data.** Every number in this report describes an
   estimator's behaviour on data generated from a known process. None of it is a
   finding about students.
2. **`C` is assumed.** Scenario differences are properties of an assumed
   sensitivity matrix. They are not evidence that support changes outcomes.
3. **T4 has not run.** "Engagement" and "capability" are coordinate labels.
4. **T3 has not run.** The intervention mechanism works; its stability across
   refits is untested.
5. **Intervals are over-confident** (72.7% at nominal 95%).
6. **Level dominates trajectory** (share 0.364).
7. **Two-stage fit attenuates loadings** (A-03). EM exists and is off by default.
8. **α and Q are inflated by the two-stage fit.** Fitted α = [0.79, 0.28] vs
   true [0.35, 0.18]; fitted diag(Q) = [0.305, 0.179] vs true [0.20, 0.10].
   Fitting transition parameters on filtered rather than smoothed states
   double-counts observation noise as process noise. This is the specific defect
   the RTS smoother was built to enable fixing.
9. **Score likelihood is a simplification** (A-04).
10. **Small evaluation sample.** 26 events in 752 person-periods. Confidence
    intervals on AUC are wide and **are not computed** — that is itself a gap.
11. **No fairness or subgroup analysis.** Not implemented.
12. **The dashboard shows one student at a time.** No cohort triage view.

---

## 25. Synthetic vs real data

| | Synthetic | OULAD |
|---|---|---|
| Status | **used for every result here** | **NEVER RUN** |
| Ground truth for `z` | yes | impossible — no such column exists |
| Students | 150–250 | 28,785 unique |
| Withdrawal rate | 3.9% (this run) | 31.2% |
| What results mean | describe the **estimator** | would describe **students** |

**Rule enforced in code, not just documented:** if OULAD is absent, the adapter
**raises**. It never silently falls back to synthetic data. Any number from the
synthetic fixture describes the estimator, never students.

The provenance flag travels with the run through the database
(`model_runs.synthetic`), the API (`provenance.synthetic`), and into the UI as a
mandatory chip.

---

## 26. Causal interpretation limits

**The scenario feature is not a causal estimate, and cannot be made into one
with the current data.**

Precisely why:

1. **No intervention exists in the data.** `d_t` is identically zero in both
   OULAD and the synthetic generator. There is nothing from which to estimate a
   treatment effect.
2. **`C` is declared, not learned.** `DEFAULT_SENSITIVITY` in
   `simulation/intervention.py` hard-codes `engagement_support = (0.40, 0.05)`.
   A scenario difference is a property of that declaration.
3. **No identification strategy.** No randomisation, no instrument, no
   discontinuity, no plausible unconfoundedness argument.

**The permitted phrasing** is fixed and used everywhere in the product:

> *Under the model's assumed transition dynamics, …*

**Forbidden phrasings** (from `docs/assumptions.md`): "this intervention would
reduce dropout by X%", "students who receive support are Y% less likely to
withdraw", or any statement in which the model's output becomes evidence about
the effect of an action.

`tests/test_api.py::test_forecasts_are_labelled_model_generated` asserts the
string `NOT A CAUSAL ESTIMATE` is present in every forecast payload. The
disclaimer is a **required schema field**, so a client cannot render a forecast
without it.

---

## 27. Mathematical formulation

Complete, in one place, with the implementing file.

### Transition · `state/model.py::transition`
$$z_{t+1} = z_t + \alpha \odot (\theta_i - z_t) + B u_t + C d_t + \varepsilon_t, \quad \varepsilon_t \sim \mathcal N(0, Q)$$

### Transition Jacobian · `state/model.py::transition_jacobian`
$$F = \operatorname{diag}(1 - \alpha)$$

### Predict · `state/filter.py::TwinFilter.predict`
$$m_{t|t-1} = f(m_{t-1|t-1}), \qquad P_{t|t-1} = F P_{t-1|t-1} F^{\mathsf T} + Q$$

### Emissions · `state/emissions.py`
$$\text{counts:}\quad y_c \sim \text{NegBin}\!\left(\exp(b_{0,c} + w_c^{\mathsf T} z),\ \phi_c\right)$$
$$\text{submission:}\quad y_s \sim \text{Bernoulli}\!\left(\sigma(b_0 + w_s^{\mathsf T} z)\right)$$
$$\text{score:}\quad \operatorname{logit}(y_q) \sim \mathcal N(b_0 + w_q^{\mathsf T} z,\ \sigma^2) \quad \text{(A-04)}$$

### Update · `state/filter.py::TwinFilter.update`
$$\hat z = \arg\max_z \Big[ -\tfrac12 (z - m_{t|t-1})^{\mathsf T} P^{-1}_{t|t-1} (z - m_{t|t-1}) + \textstyle\sum_c \log p(y_c \mid z) \Big]$$
$$m_{t|t} = \hat z, \qquad P_{t|t} = \left(P^{-1}_{t|t-1} - \textstyle\sum_c \nabla^2_z \log p(y_c \mid \hat z)\right)^{-1}$$

### Set point · `state/model.py::TwinParameters.setpoint`
$$\theta_i = \frac{n_i \bar y_i + k \mu_c}{n_i + k}, \qquad k = \frac{\sigma^2_w}{\tau^2}, \qquad \tau^2 = \max\!\left(\operatorname{Var}(\bar y) - \frac{\sigma^2_w}{\bar n},\ 10^{-3}\right)$$

### Hazard · `models/readout.py`
$$h_{i,t} = \sigma\!\left(\gamma^{\mathsf T} z_{i,t} + \gamma_{\text{dev}}^{\mathsf T}\mathrm{dev}_{i,t} + \gamma_u^{\mathsf T} u_{c,t} + \gamma_0\right)$$

### Cumulative risk · `models/readout.py::cumulative_risk`
$$R_{i,t} = 1 - \prod_{s \le t}(1 - h_{i,s})$$

### Attribution · `explain.py`
$$\text{contrib}_c = P_{t|t} \nabla_z \log p(y_c \mid z)\big|_{z = m_{t|t-1}}, \qquad r = \Delta m - \textstyle\sum_c \text{contrib}_c$$

### RTS smoother · `state/filter.py::smooth`
$$J_t = P_{t|t} F^{\mathsf T} P^{-1}_{t+1|t}, \quad m_{t|T} = m_{t|t} + J_t(m_{t+1|T} - m_{t+1|t})$$

### Simulation · `simulation/forward.py`
$$z^{(j)}_0 \sim \mathcal N(m_T, P_T), \qquad z^{(j)}_{h+1} = f(z^{(j)}_h; d) + L\varepsilon,\ \ L L^{\mathsf T} = Q$$

### Metrics · `evaluation/metrics.py`
$$\text{Brier} = \tfrac1n\sum (p_i - y_i)^2, \qquad \text{ECE} = \sum_{b} \frac{n_b}{n}\left| \bar p_b - \bar y_b \right|$$

### Trajectory share · `evaluation/twin_tests.py`
$$\text{share} = \frac{\max(0, \text{AUC}_{\text{dev}} - 0.5)}{\max(0, \text{AUC}_{\text{lvl}} - 0.5) + \max(0, \text{AUC}_{\text{dev}} - 0.5)}$$

---

### Formula → implementation index

| Formula | File | Function |
|---|---|---|
| transition | `state/model.py` | `transition` |
| Jacobian | `state/model.py` | `transition_jacobian` |
| set point | `state/model.py` | `TwinParameters.setpoint` |
| variance components, `k` | `state/fit.py` | `fit_twin` |
| α, Q estimation | `state/fit.py` | `fit_twin` |
| NegBin loglik/grad/Hess | `state/emissions.py` | `negbin` |
| Bernoulli | `state/emissions.py` | `bernoulli` |
| Gaussian-on-logit | `state/emissions.py` | `gaussian_logit` |
| predict | `state/filter.py` | `TwinFilter.predict` |
| Newton update | `state/filter.py` | `TwinFilter.update` |
| RTS smoother | `state/filter.py` | `TwinFilter.smooth` |
| hazard | `models/readout.py` | `HazardReadout.hazard` |
| person-period + deviation | `models/readout.py` | `build_person_period` |
| cumulative risk | `models/readout.py` | `cumulative_risk` |
| attribution | `explain.py` | `explain_week` |
| residual | `state/model.py` | `StepAttribution.residual` |
| forward simulation | `simulation/forward.py` | `simulate_forward` |
| posterior predictive | `simulation/forward.py` | `posterior_predictive_check` |
| Brier / ECE / AUC | `evaluation/metrics.py` | `brier`, `ece`, `auc` |
| T1 | `evaluation/twin_tests.py` | `check_T1_sufficiency` |
| T2 | `evaluation/twin_tests.py` | `check_T2_generativity` |
| level/trajectory | `evaluation/twin_tests.py` | `decompose_level_vs_trajectory` |
| T3, T4 | `evaluation/twin_tests.py` | raise `NotImplementedError` |

---

## 28. Computational complexity

Let *N* = students, *T* = weeks, *d* = state dimensions (≤3), *C* = channels,
*P* = particles, *K* = horizon.

| Stage | Complexity | Measured (150 × 20) |
|---|---|---|
| Load | O(E) | 0.26 s |
| Features | O(N·T·C) | 0.50 s |
| Fit | O(N·T·C) GLMs | 1.62 s |
| **Filter** | **O(N·T·(I·(C·d² + d³)))** | **2.62 s** |
| Readout | O(N·T·d) | 0.08 s |
| Evaluate | O(N·T) | 0.35 s |
| Controls | O(3·N·T) | 0.16 s |
| Simulate | O(P·K·(d² + C)) per student | ~0.3 s / student |

*I* = Newton iterations, capped at 25 and typically 3–5.

**`d ≤ 3` is what keeps this cheap.** The `d³` matrix inverse inside the Newton
loop is 27 operations, so it never dominates. The constraint is a research
decision that happens to also be the performance story.

**Scaling to OULAD** (28,785 students × ~39 weeks): the filter is
embarrassingly parallel across students — no shared state — so it is a `joblib`
call away from linear speed-up. The bottleneck would be the 10.6M-row VLE read,
which the adapter already chunks. Extrapolating the measured per-student filter
cost gives roughly 8–10 minutes single-threaded. **This has not been measured.**

**API latency** is O(rows returned), because everything is precomputed and
indexed. The composite `twin` route for a 20-week student is a handful of
indexed selects.

---

## 29. Backend integration

### 29.1 The one-model rule

```
adapters → pipeline → PipelineResult          ← THE MODEL, exactly once
                          │
                          ▼  scripts/ingest_run.py
                   store/ingest.py             ← the ONLY writer
                          ▼
                       SQLite
                          ▼
                store/repository.py            ← the ONLY reader
                          ▼
                   api/services.py             ← shapes, never estimates
                          ▼
                    api/routes.py              ← parses, delegates, serialises
```

`store/ingest.py` computes **nothing**. Every value it stores is read off a
`PipelineResult` or a `SimulationResult`. If a quantity is not in one of those
objects it does not get a column.

`api/services.py` does exactly one piece of arithmetic the pipeline did not —
mean, SD and run-lengths over stored states for the Deep Dive screen — and its
docstring and the API field description both say so.

### 29.2 Why FastAPI, reversing an earlier decision

`docs/architecture.md` rejected FastAPI on the grounds that *"the `api/` package
is an empty placeholder. Nothing consumes an HTTP API yet."* That condition no
longer holds. The reversal is recorded in that document rather than left for a
reader to discover.

pydantic was likewise rejected as a **transport type inside the pipeline**,
where frames are correct and per-row objects for 10.6M rows would be absurd.
Validating a few dozen fields at an HTTP boundary is a different job.

### 29.3 Model versioning and reproducibility

Every stored number traces to:

| Field | Source |
|---|---|
| `model_runs.seed` | master seed; all others derive via `rng_for(config, purpose)` |
| `model_runs.model_version` | `student_twin.__version__` |
| `model_runs.code_revision` | git short SHA, or `NULL` — never faked |
| `model_runs.config_json` | full resolved `Config` |
| `model_runs.params_json` | fitted α, diag(Q), μ₀, loadings, φ, shrinkage |
| `scenarios.seed_purpose` | the exact `rng_for` purpose string |

To reproduce a result: read `config_json` and `seed`, check out `code_revision`,
re-run `scripts/ingest_run.py`. Because `rng_for` derives every generator from
the master seed by purpose, the same seed reproduces the same particle cloud.

---

## 30. API data flow

```
Browser                       FastAPI                    SQLite
  │                              │                          │
  ├─ GET /api/health ───────────►│─ SELECT COUNT(*) ───────►│
  │◄──────── runs, migrations ───┤◄─────────────────────────┤
  │                              │                          │
  ├─ GET /api/students/demo ────►│─ largest sustained ─────►│
  │◄──────── S000021 ────────────┤   decline in dim 0       │
  │                              │                          │
  ├─ GET /students/S000021/twin ►│─ 12 indexed selects ────►│
  │                              │─ services.twin_payload   │
  │                              │─ response_model validate │
  │◄──── TwinPayload (JSON) ─────┤                          │
  │                              │                          │
  ├─ GET /api/evaluation ───────►│                          │
  ├─ GET /api/cohort ───────────►│   (in parallel)          │
  ├─ GET /api/contrast ─────────►│                          │
  │                              │                          │
  ▼  web/api.js  fromApi() → view model → app.js → charts.js
```

**Failure path.** If any request fails or times out (6 s), `ST_Api.boot()` falls
back to `web/data.js`, a frozen export, and the UI shows a non-dismissible
banner: *"Offline snapshot. The API at … did not respond."* If neither is
available it renders an error naming what failed. **It never renders a
placeholder number.**

---

## 31. Database design

Full reference: [`DATABASE_SCHEMA.md`](DATABASE_SCHEMA.md).

**Which values are persistent vs computed on demand:**

| Quantity | Persistent | Computed at request |
|---|---|---|
| latent states, θ, hazard, attribution | ✓ | |
| forecast quantiles, risk, particle paths | ✓ | |
| metrics, controls, capability tests | ✓ | |
| own-distribution summary (mean, SD, runs) | | ✓ (arithmetic only) |
| cohort scatter | ✓ (aggregated in SQL) | |
| contrast pair selection | | ✓ (ranking stored θ) |

Nothing model-derived is computed at request time. **Nothing is cached beyond
the database** — SQLite with indexes is fast enough that a cache layer would add
a staleness failure mode for no measured benefit.

**How a future model version reproduces an old result:** old rows keep their own
`run_id`, `model_version`, `code_revision` and `config_json`. A new run inserts a
new `run_id`; it never mutates an old one. Two model versions coexist in the same
file and the API can serve either via `?run_id=`.

---

## 32. Worked example: one student end to end

Student **S000021**, context `SYN0_2026A`, run `f7bf16be…`, seed 20260813.

**1 · Observations, week 19** — canonical channels: `content_view`,
`resource`, `quiz_attempt`, `forum`, `submission`.

**2 · Personal baseline** — `θ_engagement = 0.279`, from 20 weeks with
`k = 0.433` and context mean 0.031.

**3 · Prediction into week 19** — `α = 0.79`, so the state drifts 79% of the way
toward θ, then `+Q` widens: prior interval **±1.131**.

**4 · Update** — the week's evidence pulls the distribution; posterior interval
**±0.618**. Predict widened and update narrowed in **19 of 19** transitions.

**5 · State** — engagement **−0.774**, i.e. **−1.053 below their own baseline**.
Against the cohort's *average activity* this student is unremarkable; against
their own normal they are among the furthest below it. That gap is the entire
argument for personalisation.

**6 · Hazard** — 7.34% for week 19; cumulative risk 45.97% across the observed
weeks.

**7 · Attribution, week 19** — `content_view` dominates; the residual is
reported as its own bar and is not folded in.

**8 · Simulation** — 600 particles, 8 weeks. Under **current dynamics**
cumulative simulated risk reaches 45.97%; under an **assumed** engagement
support of +1.00 it reaches 30.91%. That difference is a property of the
assumed `C`. **It is not evidence that support helps.**

**9 · Persistence** — one `run_id`, ~1,326 state rows, 1,326 attribution steps,
4,480 forecast rows across 7 scenarios.

**10 · Serving** — one `GET /api/students/S000021/twin`, validated against
`TwinPayload`, rendered by `web/app.js`.

---

## 33. Glossary

| Term | Meaning here |
|---|---|
| **Attribution** | Which observation channels moved the state this week. Association, not cause. |
| **Censored** | Still enrolled at the last observed week. **Not** a negative. |
| **Credible interval** | Bayesian interval from the posterior. Reported at 95% (±1.96 SD). |
| **Dispersion ratio** | SD of simulated observations ÷ SD of real ones. 1.0 is ideal. |
| **ECE** | Expected Calibration Error — do stated probabilities match observed rates. |
| **Emission** | The likelihood linking latent state to an observed channel. |
| **Forward chaining** | Train on weeks ≤ *w*, test on weeks > *w*. Never shuffle time. |
| **Hazard** | P(event in week *t* | survived to *t*). A readout, not a verdict. |
| **Laplace approximation** | Gaussian centred at the posterior mode with covariance −H⁻¹. |
| **Latent state (z)** | The unobserved coordinates the model tracks. **Not** knowledge or motivation. |
| **Negative control** | A perturbation that *should* destroy performance. If it does not, suspect a leak. |
| **Particle** | One sampled trajectory in the forward simulation. |
| **Person-period** | One row per student-week at risk. |
| **Posterior / Prior** | Belief after / before this week's evidence. |
| **Process noise (Q)** | Week-to-week randomness in the state, independent of observation. |
| **Residual** | The part of the state shift no channel can be credited with. |
| **Set point (θ)** | The student's own fitted normal. The origin of every comparison. |
| **Shrinkage (k)** | How far θ is pulled toward the cohort. Estimated, not chosen. |
| **Sufficient statistic** | A summary carrying all the information the history had. What T1 tests. |
| **Tier 1 / 2 / 3** | Self-relative / context / institution-specific features. Tier 3 does not exist. |

---

## 34. Future research directions

**Ordered by how much each would change what the system may claim.**

### P0 — required before any real-data claim

1. **Run OULAD.** Fix the four adapter defects. Until this happens the project
   has no empirical result at all.
2. **Confidence intervals on every metric.** 26 events is a small sample and the
   AUC comparison currently has no error bars.

### P1 — the model's known defects

3. **Enable EM.** The smoother exists; the M-step exists; it is off by default.
   Should correct the inflated α and Q and the attenuated loadings (A-03).
4. **Model parameter uncertainty** so intervals stop being over-confident
   (§22.2). Bootstrap over refits is the cheap version; the MCMC reference track
   is the principled one.
5. **Implement T4.** Rotation-aware comparison of latent dimensions across
   independent refits and contexts. Until it runs, the dimension names cannot be
   defended.
6. **Implement T3.** Refit across seeds; check sign and magnitude stability of
   the intervention response.
7. **Replace the score likelihood with the specified Beta** (A-04). Single
   function; no interface change.

### P2 — capability

8. **Raise the trajectory share above 0.5.** Candidates: a change-point term, an
   explicit velocity dimension (within the 3-dimension limit), or a hazard that
   is a function of the *derivative* of the deviation.
9. **MCMC reference track** to check the Laplace approximation. This is the point
   at which adding `pymc`/`numpyro` stops being cargo.
10. **Fairness and subgroup analysis**, including intersectional subgroups.
11. **Cross-dataset transfer.** Fit on one institution, evaluate on another —
    the actual test of the tier-1 hypothesis.

### P3 — product

12. Cohort triage view.
13. Authentication, before any real student data exists in the database.
14. Streaming ingestion, which would make "synchronization" mean something
    closer to real-time — and would require A-12 to be revisited explicitly
    rather than quietly.

---

*End of report. Every figure quoted is reproducible with
`python scripts/run_prototype.py --out outputs/synthetic` at seed 20260813.*
