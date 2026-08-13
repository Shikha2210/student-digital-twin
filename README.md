# Context-Adaptive Student Digital Twin — Prototype 1

A per-student latent-state model with recursive updating, generative forward
simulation, and an explicit intervention interface. Prediction is a *readout from
the state*, not the definition of the system.

**Status: first vertical slice.** The pipeline runs end to end. It runs on a
synthetic fixture only — OULAD is not present in this environment, and the
adapter refuses to substitute anything for it.

---

## Quick start

```bash
py -3.13 -m pip install -e ".[dev,dashboard]"

py -3.13 scripts/run_prototype.py                  # synthetic fixture
py -3.13 scripts/run_prototype.py --adapter oulad  # real data, once present
py -3.13 -m pytest -q                              # 69 tests
streamlit run dashboard/app.py                     # dashboard
```

To use real data, put the OULAD CSVs in `data/raw/oulad/` — see
[data/README.md](data/README.md).

---

## The four properties, and where each lives

| Property | Meaning | Implementation | Evidence |
|---|---|---|---|
| **Persistence** | State exists between observations | `state/model.py::StateTrajectory` | `test_state_persists_across_weeks` |
| **Synchronization** | State updated recursively as evidence arrives | `state/filter.py::TwinFilter` | T1 passes exactly (max diff 0.00e+00) |
| **Generativity** | Simulates future observation trajectories | `simulation/forward.py` | T2 runs — **currently FAILS**, see below |
| **Intervenability** | Transition takes an exogenous intervention vector | `simulation/intervention.py` | `test_intervention_shifts_the_simulated_trajectory` |

---

## What is honestly working

- Canonical schema with validation that **rejects** malformed adapter output
  rather than coercing it.
- OULAD adapter written against the published table layout, with a coverage
  manifest — **structurally tested, never executed against real data.**
- Tier-1 features with inspectable provenance and a passing temporal-leak guard.
- Recursive Laplace filter: uncertainty shrinks with evidence, covariance stays
  positive definite, empty weeks do not fabricate updates, missing scores are
  skipped rather than imputed.
- Baseline ladder + twin, forward-chained, with calibration reported beside
  discrimination.
- Negative controls with three-valued verdicts and control-specific interpretation.
- Per-channel explanation of every weekly state change.
- Forward simulation with uncertainty bands and scenario comparison.

## What is failing, and why that is reported rather than fixed

**T2 (generativity) FAILS: dispersion ratio 3.90, acceptable range 0.5–2.0.**

Simulated trajectories are roughly four times more dispersed than real ones. The
90% band covers 98.3% of held-out observations — coverage looks *excellent*
precisely because the forecast is saying very little. Under-confidence is a
failure too, and a coverage-only test would have waved it through.

Per Gate 1, the consequence is that scenario outputs are not yet trustworthy as
calibrated forecasts. The dashboard still shows them, labelled, because the
*mechanism* is what this prototype is demonstrating.

**The twin is currently a level detector, not a trajectory detector.**
`permute_time` (which shuffles weeks within a student, preserving their mean
exactly) barely dents AUC — 0.737 → 0.726. This is not leakage; the leakage test
(`permute_student_identity`) collapses to 0.495 as required. It means the
dynamics are not yet earning their place, which is exactly Gate 1 weakness 1.

**GBM underperforms the majority baseline** on the synthetic fixture (AUC 0.497).
With a 3.9% weekly event rate and ~650 test rows there is too little signal.
Reported as-is; it needs real data before it means anything.

---

## What is NOT implemented

- **MCMC reference track.** Interface only. All state estimates are
  Laplace-approximate and labelled as such.
- **EM parameter refinement.** `fit_twin(n_em_iters=k)` raises for non-zero `k`
  rather than silently ignoring it.
- **T3 (intervention stability), T4 (identifiability).** Raise
  `NotImplementedError`. Until T4 passes, "engagement" and "capability" are
  labels of convenience — see [A-06](docs/assumptions.md#a-06).
- **Parameter and transfer uncertainty.** Architectural hooks only; reported
  uncertainty is therefore an under-estimate.
- **Cross-dataset transfer (L5), divergence curve.** P1, not prototype scope.
- **`api/`** is an empty placeholder. Nothing needs HTTP yet.
- **Lifestyle and self-report channels.** In the schema, supplied by nobody.

---

## The line this project does not cross

Intervention effects are **assumed, never estimated.** OULAD records no
interventions, so there is nothing to estimate them from. Read every scenario as

> Under the model's assumed transition dynamics, ...

and never as

> Doing this will improve the student's outcome.

The separation is structural: interventions enter only through `d_t`, a channel
no observation can write to. Full list of forbidden claims in
[docs/assumptions.md](docs/assumptions.md).

---

## Layout

```
src/student_twin/
  schema.py         canonical event contract, coverage manifest
  config.py         dataclass config from TOML, seed derivation
  pipeline.py       end-to-end orchestration
  explain.py        per-channel attribution of state change
  adapters/         oulad.py, synthetic.py  (only place dataset vocabulary appears)
  features/         tier1.py, context.py, provenance.py
  state/            model.py, emissions.py, filter.py, fit.py
  models/           readout.py, baselines.py
  simulation/       forward.py, intervention.py
  evaluation/       metrics.py, splits.py, negative_controls.py, twin_tests.py
tests/              69 tests, no OULAD dependency
dashboard/app.py    streamlit prototype
docs/               architecture.md, assumptions.md
```

## Reproducibility

One master seed in `configs/prototype.toml`, with independent generators derived
per purpose so adding a diagnostic cannot shift an experiment's stream. Runs
write a manifest via `--out`. See [docs/architecture.md](docs/architecture.md).
