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
7. **Never claim daily records feed the model.** They are persisted, aggregated
   and displayed. No emission model has been fitted for a self-reported scale, so
   feeding one in would mean inventing a loading — which is rule 1. The correct
   route is a new adapter declaring `lifestyle` / `self_report` available, plus a
   refit (A-07). `model_input: false` is on every daily payload.
8. **Never show a value a student did not enter.** A metric with no row is
   absent, not zero. A sum over activities that lack durations travels with
   `activities_without_duration` so it cannot read as a total.

## Constraints that are enforced in code, not just documented

- Latent state is 2 dims by default, 3 maximum — `StateConfig` raises otherwise.
- Every canonical type must be declared available or unavailable by every adapter
  — `CoverageManifest` raises otherwise.
- `EventTable` rejects extra columns, so dataset-specific fields cannot leak
  through the schema.
- There is no tier-3 feature builder. The absence is the enforcement.
- `state/`, `models/`, `simulation/`, `evaluation/` must not import an adapter.
- `daily/` must not import an adapter, the store, or anything under `state/`,
  `models/`, `simulation/`, `evaluation/`. It is the raw-input layer and the seam
  a future adapter would attach to; a dependency in either direction collapses it.
- No `day_*` table carries `run_id`, and none has a foreign key to a model table
  — `test_daily_records_do_not_hang_off_a_model_run` asserts it.
- Week numbering exists once, in `daily/calendar.py`. `week_index` is a cached
  derivation of `date` and is re-derived whenever the anchor moves.

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

Prototype 1. Runs end to end on the synthetic fixture; **207 tests pass**. T1 and
T2 pass, T3/T4 not implemented. The twin is currently level-driven rather than
trajectory-driven — Gate 1 weakness 1, and it is the most important open
question for Phase 1.

The daily-record layer (migration `003`, `src/student_twin/daily/`,
`api/routes_daily.py`, `web/journal.js`) is the second thing in the database
after model output, and the first a person can write to. It is raw input,
aggregated on read, and consumed by no model. `docs/DAILY_RECORDS.md` is the
reference; read §5 of it before saying anything about what the model uses.
