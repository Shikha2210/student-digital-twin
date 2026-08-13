# Working notes for Claude

## What this project is

A context-adaptive student digital twin. The Gate 1 research architecture is the
source of truth; `docs/assumptions.md` is normative for anything the code does.

## Non-negotiables

1. **Never fabricate a result.** If OULAD is absent, the adapter raises. It must
   never fall back to synthetic data silently. Any number from the synthetic
   fixture describes the estimator, never students.
2. **Never claim causal intervention effects.** `C` is assumed, not fitted
   (A-08). Scenario language is "under the model's assumed transition
   dynamics, ...".
3. **Never call the replay real-time.** It is retrospective (A-12).
4. **Never call digital traces physiological or multimodal sensing.** Physiological
   sensing is permanently out of scope.
5. **Never claim the latent state is the student's real knowledge or motivation.**
   T4 has not run (A-06).
6. **Expose failures.** A failing capability test is a result. Do not tune a
   threshold to make it pass.

## Constraints that are enforced in code, not just documented

- Latent state is 2 dims by default, 3 maximum — `StateConfig` raises otherwise.
- Every canonical type must be declared available or unavailable by every adapter
  — `CoverageManifest` raises otherwise.
- `EventTable` rejects extra columns, so dataset-specific fields cannot leak
  through the schema.
- There is no tier-3 feature builder. The absence is the enforcement.
- `state/`, `models/`, `simulation/`, `evaluation/` must not import an adapter.

## Conventions

- Python 3.13 via `py -3.13`. The bare `python` on PATH is 3.11 and lacks sklearn.
- Config is TOML through stdlib `tomllib`. No PyYAML.
- Source files are ASCII. A cleanup pass replaced em dashes because the Windows
  console renders them as mojibake in script output.
- Library functions must not be named `test_*` — pytest collects them. The Gate 1
  capability checks are `check_T1_sufficiency` etc. for this reason.
- Seeds derive from one master seed via `rng_for(config, purpose)`.

## Before adding a dependency

Check `docs/architecture.md` — several obvious ones were considered and rejected
with reasons (pydantic, PyYAML, lightgbm, Airflow, FastAPI). Adding pymc/numpyro
is expected when the MCMC reference track is built, and not before.

## Current state

Prototype 1. Runs end to end on the synthetic fixture; 69 tests pass. T1 passes,
**T2 fails** (over-dispersed simulation), T3/T4 not implemented. The twin is
currently level-driven rather than trajectory-driven — Gate 1 weakness 1, and it
is the most important open question for Phase 1.
