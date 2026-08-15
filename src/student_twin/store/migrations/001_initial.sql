-- ============================================================
-- StudyTwin 001 - initial schema
-- ------------------------------------------------------------
-- SQLite. Chosen over Postgres because this is a single-machine
-- research prototype: no server to run, the whole database is one
-- file that can be committed to a release artefact, and the SQL is
-- close enough to standard that the Postgres migration is mechanical
-- (see docs/DATABASE_SCHEMA.md).
--
-- Two ideas run through every table here:
--
--   1. EVERY model-derived row carries run_id. A number without a run
--      has no seed, no model version and no code revision behind it,
--      which makes it unreproducible and therefore not a result.
--
--   2. Long format over wide. The latent state has 1-3 dimensions and
--      an adapter may supply any subset of the canonical channels. A
--      wide table would need a migration every time that changed, and
--      would have to store NULL where the honest answer is "this
--      dataset does not carry that channel" - which is exactly the
--      distinction CoverageManifest exists to preserve.
-- ============================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------
-- PROVENANCE
-- ---------------------------------------------------------------

-- One row per execution of the pipeline. This is the root of the
-- provenance graph: delete a run and every number it produced goes
-- with it (ON DELETE CASCADE throughout).
CREATE TABLE model_runs (
    run_id            TEXT PRIMARY KEY,          -- uuid4 hex
    created_at        TEXT    NOT NULL,          -- ISO-8601 UTC
    dataset           TEXT    NOT NULL,          -- 'synthetic' | 'oulad' | ...
    synthetic         INTEGER NOT NULL,          -- 0/1. Travels with the run.
    seed              INTEGER NOT NULL,          -- master seed; all others derive
    model_version     TEXT    NOT NULL,          -- student_twin.__version__
    code_revision     TEXT,                      -- git sha if available
    inference_method  TEXT    NOT NULL,          -- 'laplace_approximate' | ...
    n_dims            INTEGER NOT NULL,
    dim_names         TEXT    NOT NULL,          -- JSON array
    config_json       TEXT    NOT NULL,          -- full resolved Config
    params_json       TEXT,                      -- fitted alpha/Q/loadings etc.
    n_students        INTEGER NOT NULL DEFAULT 0,
    n_person_periods  INTEGER NOT NULL DEFAULT 0,
    n_events          INTEGER NOT NULL DEFAULT 0,
    notes             TEXT,
    CHECK (synthetic IN (0, 1)),
    CHECK (n_dims BETWEEN 1 AND 3)               -- mirrors StateConfig
);
CREATE INDEX ix_runs_created ON model_runs (created_at DESC);
CREATE INDEX ix_runs_dataset ON model_runs (dataset, created_at DESC);

-- Which canonical event types the adapter declared available. Every
-- canonical type must appear exactly once per run - the pipeline's
-- CoverageManifest raises otherwise, and this table preserves that
-- guarantee rather than letting absence mean "unknown".
CREATE TABLE run_coverage (
    run_id          TEXT    NOT NULL REFERENCES model_runs(run_id) ON DELETE CASCADE,
    canonical_type  TEXT    NOT NULL,
    available       INTEGER NOT NULL,
    PRIMARY KEY (run_id, canonical_type),
    CHECK (available IN (0, 1))
);

-- ---------------------------------------------------------------
-- SUBJECTS
-- ---------------------------------------------------------------

CREATE TABLE contexts (
    run_id      TEXT    NOT NULL REFERENCES model_runs(run_id) ON DELETE CASCADE,
    context_id  TEXT    NOT NULL,
    n_students  INTEGER NOT NULL DEFAULT 0,
    n_weeks     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id, context_id)
);

-- A student AS OBSERVED IN ONE RUN. The same person re-run under a new
-- seed is a different row, because the estimates attached to them are
-- different. `external_id` is the adapter's identifier and is the only
-- link back to source data.
CREATE TABLE students (
    run_id       TEXT    NOT NULL REFERENCES model_runs(run_id) ON DELETE CASCADE,
    student_id   TEXT    NOT NULL,
    context_id   TEXT    NOT NULL,
    external_id  TEXT,
    n_weeks      INTEGER NOT NULL DEFAULT 0,
    event_observed INTEGER NOT NULL DEFAULT 0,   -- did the modelled event occur
    event_week   INTEGER,                        -- NULL = censored, not zero
    PRIMARY KEY (run_id, student_id),
    FOREIGN KEY (run_id, context_id) REFERENCES contexts(run_id, context_id) ON DELETE CASCADE,
    CHECK (event_observed IN (0, 1))
);
CREATE INDEX ix_students_context ON students (run_id, context_id);

-- ---------------------------------------------------------------
-- INPUTS
-- ---------------------------------------------------------------

-- Canonical observation channels, long format. A dataset that does not
-- carry `forum` simply has no forum rows; it does not have zeros.
CREATE TABLE observations (
    run_id      TEXT    NOT NULL,
    student_id  TEXT    NOT NULL,
    t           INTEGER NOT NULL,                -- week index within the context
    channel     TEXT    NOT NULL,                -- CanonicalType value
    value       REAL    NOT NULL,
    PRIMARY KEY (run_id, student_id, t, channel),
    FOREIGN KEY (run_id, student_id) REFERENCES students(run_id, student_id) ON DELETE CASCADE
);
CREATE INDEX ix_obs_student_week ON observations (run_id, student_id, t);

-- Tier-1 features: self-relative and dataset-agnostic by construction.
-- There is deliberately no tier-3 table, mirroring the absence of a
-- tier-3 feature builder. The absence is the enforcement.
CREATE TABLE features (
    run_id      TEXT    NOT NULL,
    student_id  TEXT    NOT NULL,
    t           INTEGER NOT NULL,
    feature     TEXT    NOT NULL,
    value       REAL    NOT NULL,
    PRIMARY KEY (run_id, student_id, t, feature),
    FOREIGN KEY (run_id, student_id) REFERENCES students(run_id, student_id) ON DELETE CASCADE
);
CREATE INDEX ix_feat_student_week ON features (run_id, student_id, t);

-- ---------------------------------------------------------------
-- MODEL OUTPUTS
-- ---------------------------------------------------------------

-- The filtered posterior p(z_t | y_1..t), one row per dimension.
-- `sd` is stored rather than the full covariance: the product shows
-- marginal intervals, and storing a 2x2 per week per student for a
-- quantity nothing reads would be storage without a consumer.
CREATE TABLE twin_states (
    run_id          TEXT    NOT NULL,
    student_id      TEXT    NOT NULL,
    t               INTEGER NOT NULL,
    dim_name        TEXT    NOT NULL,
    mean            REAL    NOT NULL,
    sd              REAL    NOT NULL,
    method          TEXT    NOT NULL,            -- InferenceMethod
    n_observations  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id, student_id, t, dim_name),
    FOREIGN KEY (run_id, student_id) REFERENCES students(run_id, student_id) ON DELETE CASCADE,
    CHECK (sd >= 0)
);
CREATE INDEX ix_state_student_week ON twin_states (run_id, student_id, t);

-- Empirical-Bayes personal set point theta_i, one row per dimension.
-- No credible interval column: the two-stage estimator returns a point
-- estimate, and a nullable column that is always NULL would invite
-- somebody to fill it with something plausible.
CREATE TABLE baselines (
    run_id        TEXT    NOT NULL,
    student_id    TEXT    NOT NULL,
    dim_name      TEXT    NOT NULL,
    theta         REAL    NOT NULL,
    shrinkage_k   REAL    NOT NULL,              -- sigma_within^2 / tau_between^2
    context_mean  REAL    NOT NULL,              -- what it was shrunk toward
    n_obs         INTEGER NOT NULL,
    PRIMARY KEY (run_id, student_id, dim_name),
    FOREIGN KEY (run_id, student_id) REFERENCES students(run_id, student_id) ON DELETE CASCADE
);

-- Discrete-time hazard readout on the person-period risk set. Rows exist
-- only for weeks the student was AT RISK; weeks after withdrawal are
-- absent, not zero.
CREATE TABLE hazards (
    run_id      TEXT    NOT NULL,
    student_id  TEXT    NOT NULL,
    t           INTEGER NOT NULL,
    hazard      REAL    NOT NULL,
    cum_risk    REAL    NOT NULL,
    y           INTEGER NOT NULL,                -- event in this week
    PRIMARY KEY (run_id, student_id, t),
    FOREIGN KEY (run_id, student_id) REFERENCES students(run_id, student_id) ON DELETE CASCADE,
    CHECK (hazard >= 0 AND hazard <= 1),
    CHECK (y IN (0, 1))
);

-- ---------------------------------------------------------------
-- EXPLANATION
-- ---------------------------------------------------------------

-- Header: the prior -> posterior move for one week and dimension.
-- `residual` is the higher-order term the first-order decomposition
-- cannot assign. It is a column, not a rounding error, because
-- normalising it away is the commonest dishonesty in this genre.
CREATE TABLE attribution_steps (
    run_id          TEXT    NOT NULL,
    student_id      TEXT    NOT NULL,
    t               INTEGER NOT NULL,
    dim_name        TEXT    NOT NULL,
    prior_mean      REAL    NOT NULL,
    posterior_mean  REAL    NOT NULL,
    shift           REAL    NOT NULL,
    residual        REAL    NOT NULL,
    PRIMARY KEY (run_id, student_id, t, dim_name),
    FOREIGN KEY (run_id, student_id) REFERENCES students(run_id, student_id) ON DELETE CASCADE
);

CREATE TABLE attribution_components (
    run_id        TEXT NOT NULL,
    student_id    TEXT NOT NULL,
    t             INTEGER NOT NULL,
    dim_name      TEXT NOT NULL,
    channel       TEXT NOT NULL,
    contribution  REAL NOT NULL,
    observed_value REAL,                          -- NULL = channel not observed
    PRIMARY KEY (run_id, student_id, t, dim_name, channel),
    FOREIGN KEY (run_id, student_id, t, dim_name)
        REFERENCES attribution_steps(run_id, student_id, t, dim_name) ON DELETE CASCADE
);

-- ---------------------------------------------------------------
-- SIMULATION
-- ---------------------------------------------------------------

-- A scenario is a named set of intervention magnitudes plus the
-- simulation settings used to run it. Its own seed is stored so the
-- exact particle cloud can be regenerated.
CREATE TABLE scenarios (
    scenario_id       TEXT PRIMARY KEY,
    run_id            TEXT    NOT NULL REFERENCES model_runs(run_id) ON DELETE CASCADE,
    label             TEXT    NOT NULL,
    interventions_json TEXT   NOT NULL,          -- [{name, magnitude}, ...]
    is_counterfactual INTEGER NOT NULL DEFAULT 1,
    horizon           INTEGER NOT NULL,
    n_particles       INTEGER NOT NULL,
    seed_purpose      TEXT    NOT NULL,          -- rng_for(config, purpose)
    CHECK (is_counterfactual IN (0, 1))
);
CREATE INDEX ix_scen_run ON scenarios (run_id);

-- Quantiles of the simulated latent state. MODEL-GENERATED, never observed.
CREATE TABLE forecasts (
    scenario_id TEXT    NOT NULL REFERENCES scenarios(scenario_id) ON DELETE CASCADE,
    student_id  TEXT    NOT NULL,
    h           INTEGER NOT NULL,                -- 0-based step into the horizon
    t           INTEGER NOT NULL,                -- absolute week
    dim_name    TEXT    NOT NULL,
    q05         REAL    NOT NULL,
    q50         REAL    NOT NULL,
    q95         REAL    NOT NULL,
    mean        REAL    NOT NULL,
    PRIMARY KEY (scenario_id, student_id, h, dim_name)
);

CREATE TABLE forecast_risk (
    scenario_id TEXT    NOT NULL REFERENCES scenarios(scenario_id) ON DELETE CASCADE,
    student_id  TEXT    NOT NULL,
    h           INTEGER NOT NULL,
    cum_risk    REAL    NOT NULL,
    PRIMARY KEY (scenario_id, student_id, h),
    CHECK (cum_risk >= 0 AND cum_risk <= 1)
);

-- A sample of INDIVIDUAL particle paths, retained so the fan chart can
-- draw real trajectories. Interpolating a fan between two quantiles
-- would be a picture of a band pretending to be a set of outcomes.
CREATE TABLE forecast_paths (
    scenario_id TEXT    NOT NULL REFERENCES scenarios(scenario_id) ON DELETE CASCADE,
    student_id  TEXT    NOT NULL,
    particle_ix INTEGER NOT NULL,
    h           INTEGER NOT NULL,
    dim_name    TEXT    NOT NULL,
    value       REAL    NOT NULL,
    PRIMARY KEY (scenario_id, student_id, particle_ix, h, dim_name)
);

-- ---------------------------------------------------------------
-- EVALUATION
-- ---------------------------------------------------------------

CREATE TABLE metrics (
    run_id      TEXT    NOT NULL REFERENCES model_runs(run_id) ON DELETE CASCADE,
    model_name  TEXT    NOT NULL,
    auc         REAL,
    brier       REAL,
    ece         REAL,
    n           INTEGER NOT NULL,
    positives   INTEGER NOT NULL,
    PRIMARY KEY (run_id, model_name)
);

CREATE TABLE negative_controls (
    run_id           TEXT    NOT NULL REFERENCES model_runs(run_id) ON DELETE CASCADE,
    control          TEXT    NOT NULL,
    verdict          TEXT    NOT NULL,           -- COLLAPSED | SURVIVED | UNDEFINED
    auc              REAL,
    is_leakage_test  INTEGER NOT NULL,
    PRIMARY KEY (run_id, control),
    CHECK (is_leakage_test IN (0, 1)),
    CHECK (verdict IN ('COLLAPSED', 'SURVIVED', 'UNDEFINED'))
);

-- T1-T4. A test that has not run is ABSENT, never stored as passed.
CREATE TABLE capability_tests (
    run_id      TEXT    NOT NULL REFERENCES model_runs(run_id) ON DELETE CASCADE,
    test_id     TEXT    NOT NULL,                -- T1 | T2 | T3 | T4
    name        TEXT    NOT NULL,
    passed      INTEGER NOT NULL,
    statistic   REAL,
    threshold   REAL,
    detail      TEXT,
    PRIMARY KEY (run_id, test_id),
    CHECK (passed IN (0, 1))
);

-- ---------------------------------------------------------------
-- PRODUCT
-- ---------------------------------------------------------------

-- Twins created through onboarding. The ONLY table that can hold data
-- about a real person, kept separate from every model table so that
-- "drop all model data" and "delete a user" are different operations.
-- No column here is model input; see docs/DATABASE_SCHEMA.md.
CREATE TABLE profiles (
    profile_id    TEXT PRIMARY KEY,
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL,
    display_name  TEXT,
    consent       INTEGER NOT NULL DEFAULT 0,
    payload_json  TEXT    NOT NULL,              -- the onboarding answers verbatim
    observations  INTEGER NOT NULL DEFAULT 0,    -- always 0 until ingestion exists
    CHECK (consent IN (0, 1))
);
CREATE INDEX ix_profiles_created ON profiles (created_at DESC);
