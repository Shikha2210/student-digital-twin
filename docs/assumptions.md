# Assumptions

Every assumption behind the twin, and especially behind simulation and
intervention. This file is normative: if the code and this document disagree, one
of them is a bug.

Each entry states what we assume, why, what breaks if it is wrong, and how we
would find out.

---

## A-01 — A week is the right time unit

**Assume.** Student state evolves slowly enough that weekly aggregation loses
nothing decision-relevant.

**Why.** OULAD's clickstream is daily-aggregated per activity type. Sub-daily
behaviour is not recoverable, and daily modelling would give a very sparse,
zero-inflated series for most students.

**If wrong.** Fast disengagement (a student who stops mid-week) is detected up to
a week late, which matters for an early-warning system.

**How we would find out.** Refit at a daily resolution on a subsample and compare
detection lead times.

---

## A-02 — Non-submission is an observation, not missing data

**Assume.** A student not submitting in an assessment week is informative
evidence about their state, not a gap to be imputed.

**Why.** It is the single strongest early signal of disengagement. Imputing it
away destroys exactly what the system exists to detect.

**Implementation.** `submission` is its own Bernoulli channel (`emissions.bernoulli`);
`score` is conditioned on it and is skipped when absent rather than zero-filled.
Enforced by `test_missing_score_is_not_treated_as_zero`.

**If wrong.** If non-submission were genuinely at random (an administrative
glitch, say), we would be reading noise as signal.

---

## A-03 — Two-stage parameter estimation is adequate for a prototype

**PROTOTYPE SIMPLIFICATION.** Gate 1 specifies joint estimation of states and
parameters. `state/fit.py` instead fits emissions against observable *proxies*,
then runs the filter.

**Consequence, specifically.** Emission loadings are regressed on a noisy proxy
rather than the posterior state, so they are attenuated toward zero (classical
errors-in-variables). The twin is therefore **conservative**: real loadings are
probably larger than the fitted ones.

**Fix.** EM: iterate fit → filter → refit to convergence. The interface already
accepts `fit_twin(..., n_em_iters=k)` and raises `NotImplementedError` for
non-zero `k` rather than silently ignoring it.

---

## A-04 — Score is modelled Gaussian on the logit scale, not Beta

**PROTOTYPE SIMPLIFICATION.** Gate 1 equation 3 specifies a Beta likelihood.
`emissions.gaussian_logit` uses a Gaussian on `logit(score)`.

**Consequence.** Constant rather than mean-dependent variance, so scores
concentrated near 0 or 1 are modelled with too much confidence.

**Fix.** Replace one function. No other module changes.

---

## A-05 — Only two of four uncertainty sources are estimated

| Source | Status |
|---|---|
| Filtering / state | **Estimated** — posterior covariance from the Laplace update |
| Observation / model | **Estimated** — dispersion and noise parameters per channel |
| Parameter | **Hook only** — point estimates are treated as known |
| Transfer | **Hook only** — requires the cross-context experiments |

**Consequence.** Reported uncertainty is an **under-estimate**. Intervals are
narrower than a full posterior would give. The dashboard says so beside the chart.

---

## A-06 — The latent dimensions are labels of convenience

**Assume nothing.** We call them `engagement` and `capability` because behaviour
loads on the first and score on the second *by construction*, not because we have
shown they measure those constructs.

**Status.** Gate 1 test T4 (identifiability across refits) is **not implemented**.
Until it runs and passes, the report must not claim the dimensions measure
engagement or knowledge. `check_T4_identifiability` raises `NotImplementedError`
rather than returning a pass.

---

## A-07 — Lifestyle and self-report channels do not exist in any current dataset

The capstone proposal requires lifestyle data (sleep, exercise, hobbies) and
self-reported cognitive/affective state (stress, motivation, perceived load).
**OULAD contains neither.**

**What we did.** `Channel.LIFESTYLE` and `Channel.SELF_REPORT`, with
`ACTIVITY_LOG` and `PERCEIVED_LOAD` types, exist in the canonical schema. Every
adapter must declare them explicitly unavailable — enforced by
`CoverageManifest.__post_init__`, which rejects a manifest that fails to account
for any canonical type.

**Consequence.** Adding a survey instrument later is a new adapter, not a schema
migration. Until then, the report must not describe the system as modelling
cognitive load, stress, or lifestyle.

**Note.** This is *self-report*, which is feasible. It is not physiological
sensing, which is out of scope permanently (Gate 1 §04).

---

## A-08 — Intervention effects are ASSUMED, never estimated

**This is the most important entry in this file.**

**Assume.** The matrix `C` maps intervention intensity to a shift in state.
Default values are in `simulation/intervention.py::DEFAULT_SENSITIVITY`.

**These numbers are declared, not fitted.** OULAD records no interventions. There
is nothing in the data from which `C` could be estimated, and no amount of
modelling changes that.

**What a scenario output means.**

> Under the model's assumed transition dynamics, if engagement were shifted by
> +1 state unit from week *t*, the simulated trajectory would be as shown.

**What it does NOT mean.**

> Providing engagement support will reduce this student's risk from 34% to 10%.

The first is a conditional statement about a model. The second is a causal claim
about a person, and nothing in this project supports it.

**Enforcement.** Interventions enter only through `d_t`, a channel no observation
can write to. `SimulationResult.provenance()` returns a string that must be shown
alongside any scenario output; the dashboard renders it beside the chart.

**How we would find out.** We would not, from OULAD. Validating `C` needs a
randomised trial or a credible natural experiment. Gate 1 E6 checks only that the
*machinery* recovers known effects on synthetic data where ground truth exists —
which tests our estimator, not the world.

---

## A-09 — Interventions are additive, immediate, and constant

Beyond A-08: the functional form assumes an intervention shifts the state by a
fixed amount per week while active, with no onset delay, no decay, no saturation,
and no interaction between simultaneous interventions.

All four are near-certainly wrong about real support programmes. They are the
simplest defensible starting point, and each is a one-line change to the
transition once there is data to justify something better.

---

## A-10 — Context covariates condition; they never identify

Tier-2 covariates enter the transition and the readout. `context_id` itself is
never a model input, and tier-3 institution-specific fields (`imd_band`,
`region`, `code_module`, raw `id_site`) are excluded from the twin entirely.

**Why.** Hypothesis H3: institution-specific features improve in-domain fit and
hurt transfer. Keeping them out by construction means the transfer result is not
contaminated by them; `OULADAdapter.tier3_frame()` retains them separately so
their cost can be *measured* later.

**Enforced by.** `test_no_institution_specific_features_exist` — the tier-3
feature builder does not exist, and the absence is the enforcement.

---

## A-11 — The synthetic fixture is not evidence

Data from `SyntheticAdapter` is generated from a known process. It exists for
pipeline tests and for ground-truth recovery checks (E6).

**No number derived from it is a finding about students.** `TwinParameters.synthetic`
propagates to `SimulationResult.synthetic_source` and into every provenance
string; the pipeline banner and the dashboard both refuse to hide it.

---

## A-12 — Historical replay is not real-time

The system processes weeks in order from a fixed historical dataset. Nothing is
live. Describing this as "real-time monitoring" would be false, and the proposal's
use of that phrase needs correcting before submission.

---

## Claims this project must not make

Reproduced from the Gate 1 specification, kept here because this file lives with
the code:

1. No causal claims about interventions (see A-08).
2. Not "generalises to universities" — at most to tested contexts.
3. Not "students" unqualified — adult, part-time, open-entry, UK distance
   learners, 2013–2014.
4. We do not measure motivation, engagement, or self-regulation (A-06).
5. Not "prevents dropout" — we predict; we do not prevent.
6. Not "real-time" (A-12).
7. Not multi-modal in the sensing sense — heterogeneous digital traces (A-07).
8. No novelty claim until the literature sweep completes.
9. Not "fair" or "equitable" — we measure disparities on recorded attributes.
10. Not "the student's actual knowledge state" (A-06).
