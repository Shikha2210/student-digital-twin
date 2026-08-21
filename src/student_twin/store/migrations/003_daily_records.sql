-- ============================================================
-- 003 - daily records: the student's own day, as a first-class entity
-- ------------------------------------------------------------
-- WHY THIS EXISTS
--
-- Until now the only longitudinal object in this database was a WEEK
-- produced by a pipeline run. That is the right unit for the model
-- (A-01) and the wrong unit for a person: a student lives days, and
-- there was no table anywhere that a student's own account of a day
-- could be written to. The product could therefore display twenty
-- weeks and accept nothing.
--
-- THREE PROPERTIES DECIDE THE SHAPE OF EVERY TABLE BELOW.
--
--   1. NO run_id, ANYWHERE. Every model-derived row in this schema
--      carries a run_id because a number without a seed and a code
--      revision is unreproducible. A day a student lived is the exact
--      opposite kind of fact: it is RAW INPUT, it is not derived from
--      anything, and deleting a model run must not delete it. Hanging
--      these tables off model_runs would make a person's history
--      cascade away when somebody re-ingests.
--
--   2. The owner is a PROFILE, not a `students` row. `students` is
--      "a student as observed in one run" and is re-created under a new
--      run_id every ingest. `profiles` is the only run-independent,
--      person-scoped, writable table in the schema, and it is already
--      the PII island - so a person's days belong to it, cascade with
--      it, and are erased by the same DELETE that erases them. That is
--      also what makes cross-profile access structurally impossible:
--      every read is reachable only through a profile_id.
--
--   3. LONG FORMAT OVER WIDE, for exactly the reason 001 gives. A
--      student who recorded their mood but not their sleep has one row,
--      not one row with a NULL sleep column and not a zero. There is no
--      value the UI can render as "0 hours slept" when the honest answer
--      is "not recorded", because no such row exists. The alternative -
--      twenty nullable columns on one wide table - would put a
--      plausible-looking number one careless COALESCE away.
--
-- RAW vs DERIVED vs MODEL. Everything in this migration is RAW: it is
-- what a student typed. Weekly aggregates over it are DERIVED and are
-- computed on read by student_twin.daily.aggregate - they are not
-- stored, because a stored aggregate can silently disagree with the rows
-- under it. Nothing here is model input; see docs/DAILY_RECORDS.md.
-- ============================================================

PRAGMA foreign_keys = ON;

-- The anchor that turns a calendar date into "week N of this student's
-- study period". Nullable: a profile that has recorded nothing has no
-- meaningful anchor, and inventing one would fabricate a week numbering.
-- When it is NULL the application derives it from the earliest recorded
-- day and says so.
ALTER TABLE profiles ADD COLUMN term_start TEXT;

-- ---------------------------------------------------------------
-- ONE DAY OF ONE STUDENT
-- ---------------------------------------------------------------
--
-- The row exists because the student opened the day, even if they then
-- recorded nothing in it. An empty day and an absent day are different
-- facts and the UI distinguishes them.
--
-- `week_index` and `day_of_week` are DERIVED FROM `date` and stored so
-- that "give me week 8" is one indexed range scan rather than seven
-- date computations. They are written by the repository and never by a
-- client: a client that could send its own week number could put
-- Thursday in week 3 and Friday in week 40.
CREATE TABLE day_records (
    day_id       TEXT PRIMARY KEY,             -- uuid4 hex
    profile_id   TEXT    NOT NULL REFERENCES profiles(profile_id) ON DELETE CASCADE,
    date         TEXT    NOT NULL,             -- ISO-8601 calendar date, YYYY-MM-DD
    week_index   INTEGER NOT NULL,             -- 1-based, relative to term_start
    day_of_week  INTEGER NOT NULL,             -- ISO: 1 = Monday ... 7 = Sunday
    source       TEXT    NOT NULL DEFAULT 'student',
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL,

    -- One record per student per calendar date. Without this a save that
    -- retries on a flaky connection silently splits one day in two, and
    -- the week view then shows Thursday twice.
    UNIQUE (profile_id, date),

    -- A date SQLite cannot parse is rejected here, not merely in pydantic.
    -- `IS` rather than `=` because strftime returns NULL for garbage and a
    -- NULL comparison would satisfy the CHECK.
    CHECK (date IS strftime('%Y-%m-%d', date)),
    CHECK (week_index >= 1),
    CHECK (day_of_week BETWEEN 1 AND 7),
    -- Provenance of the row itself. 'student' is somebody typing; the other
    -- three exist so a future importer does not have to pretend to be one.
    CHECK (source IN ('student', 'system', 'import', 'other'))
);

-- (profile_id, date) is already indexed by the UNIQUE constraint, which
-- covers "one day" and "a date range". This one covers the week view,
-- which is the hot path in the product.
CREATE INDEX ix_day_profile_week ON day_records (profile_id, week_index, day_of_week);

-- ---------------------------------------------------------------
-- WHAT THE STUDENT DID
-- ---------------------------------------------------------------
--
-- A separate table because a day genuinely has many activities: a
-- lecture, an assignment, the gym and two hours of neural networks are
-- four rows, not one text field. `seq` keeps a stable order for the ones
-- with no clock time, which is most of them when somebody logs a day
-- from memory.
--
-- `minutes` is stored rather than always computed from start/end because
-- "about two hours on the assignment" is a thing a student knows and a
-- pair of timestamps is not. When both times are present the repository
-- derives minutes; the column then holds a derivation of raw input,
-- which is still raw, not a model quantity.
CREATE TABLE day_activities (
    activity_id  TEXT PRIMARY KEY,
    day_id       TEXT    NOT NULL REFERENCES day_records(day_id) ON DELETE CASCADE,
    seq          INTEGER NOT NULL,
    title        TEXT    NOT NULL,
    category     TEXT    NOT NULL,
    detail       TEXT,                          -- free text; NULL = not written
    subject      TEXT,                          -- course, module or topic
    start_time   TEXT,                          -- 'HH:MM', 24h. NULL = no clock time
    end_time     TEXT,
    minutes      INTEGER,                       -- NULL = unknown, never 0-for-unknown
    importance   INTEGER,                       -- 1..5. NULL = not rated
    status       TEXT,                          -- for work that has one
    source       TEXT    NOT NULL DEFAULT 'student',
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL,

    CHECK (length(trim(title)) > 0),
    -- The vocabulary is closed, and it is the same list as
    -- student_twin.daily.vocab.ACTIVITY_CATEGORIES. A free-text category
    -- turns into forty spellings of "studying" within a week and no
    -- aggregate over it means anything.
    CHECK (category IN ('class', 'study', 'assignment', 'project', 'exam',
                        'quiz', 'extracurricular', 'meeting', 'personal', 'other')),
    CHECK (status IS NULL OR status IN ('done', 'partial', 'pending', 'missed')),
    CHECK (start_time IS NULL OR start_time GLOB '[0-2][0-9]:[0-5][0-9]'),
    CHECK (end_time   IS NULL OR end_time   GLOB '[0-2][0-9]:[0-5][0-9]'),
    CHECK (minutes IS NULL OR (minutes > 0 AND minutes <= 1440)),
    CHECK (importance IS NULL OR importance BETWEEN 1 AND 5),
    CHECK (seq >= 0),
    CHECK (source IN ('student', 'system', 'import', 'other'))
);

CREATE INDEX ix_dayact_day ON day_activities (day_id, seq);

-- ---------------------------------------------------------------
-- HOW THE DAY WENT  -  structured scales
-- ---------------------------------------------------------------
--
-- Long format, one row per recorded metric. A student who rated their
-- mood and skipped everything else has exactly one row here. There is no
-- representation of "focus = 0 because the form wanted a number".
--
-- The range CHECK is per metric and deliberately duplicates the Python
-- validation in student_twin.daily.vocab, in the same spirit as the
-- n_dims CHECK on model_runs: a stray script writing to this file
-- directly must not be able to route around a stated constraint.
CREATE TABLE day_observations (
    day_id  TEXT NOT NULL REFERENCES day_records(day_id) ON DELETE CASCADE,
    metric  TEXT NOT NULL,
    value   REAL NOT NULL,
    PRIMARY KEY (day_id, metric),
    CHECK (
        (metric = 'sleep_hours' AND value >= 0 AND value <= 24)
        OR (metric IN ('mood', 'stress', 'focus', 'motivation', 'energy',
                       'workload', 'productivity', 'sleep_quality')
            AND value >= 1 AND value <= 5)
    )
);

-- ---------------------------------------------------------------
-- WHAT THE STUDENT SAID  -  free text, one row per prompt answered
-- ---------------------------------------------------------------
--
-- Same reasoning: an unanswered prompt has no row, so "what did you find
-- difficult?" renders as unanswered rather than as an empty quotation.
-- The prompt vocabulary is closed so the day view can label rows without
-- a lookup table of user-invented keys.
CREATE TABLE day_reflections (
    day_id  TEXT NOT NULL REFERENCES day_records(day_id) ON DELETE CASCADE,
    prompt  TEXT NOT NULL,
    body    TEXT NOT NULL,
    PRIMARY KEY (day_id, prompt),
    CHECK (prompt IN ('difficult', 'learned', 'went_well', 'went_badly',
                      'events', 'notes')),
    CHECK (length(trim(body)) > 0)
);
