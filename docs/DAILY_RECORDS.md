# Daily records

The student's own account of each day: what they did, how it went, and what
they made of it. Persisted, aggregated into weeks, displayed - and consumed by
no model.

This document is the reference for the layer. `DATABASE_SCHEMA.md` §2.13 has the
tables, `API_SPEC.md` has the routes; what is here is the reasoning, and in
particular the boundary between raw input, derived summaries and model output,
which is the one thing about this feature that is easy to overstate.

---

## 1. The gap this closes

Before it, the only longitudinal object in the system was a **week produced by a
pipeline run**. That is the right unit for the model - A-01 argues it - and the
wrong unit for a person, who lives days.

The consequence was concrete rather than philosophical:

* `twin_states`, `observations`, `features` and every other model table is keyed
  by `run_id` and is written **only** by `store/ingest.py`. Nothing a user does
  can reach them, by design.
* `profiles` could hold onboarding answers, and did - but as one opaque
  `payload_json` blob with no structure to query and no way to add to it.
* The onboarding flow never even called `POST /api/profiles`. It wrote to
  `localStorage` and stopped, so a Twin survived exactly as long as that
  browser's storage did.

So there was no table, no route and no screen through which a day could enter
the system. Twenty weeks were displayed and nothing could be recorded.

---

## 2. What a daily record is

```
profile  (the account - the only person-scoped, run-independent table)
   |
   +-- day_record            one student, one calendar date
        |
        +-- day_activities       many. A lecture, an assignment, the gym.
        +-- day_observations     structured 1-5 scales, plus sleep hours
        +-- day_reflections      free text, one row per prompt answered
```

A `day_record` exists because the student **opened** the day, even if they then
recorded nothing in it. An opened-and-empty day and an absent day are different
facts, and the week view distinguishes them: `days_recorded` counts the first,
`days_with_content` counts only days that hold something.

### Why it hangs off `profiles` and not off `students`

`students` is *a student as observed in one run*. It is re-created under a new
`run_id` on every ingest and cascade-deleted with that run. A person's account
of their own Tuesday must not vanish because somebody re-ran the pipeline with a
different seed.

`profiles` is the only table in the schema that is run-independent,
person-scoped and writable. It is already the PII island, so:

* a person's days cascade away with the same `DELETE` that erases them - "delete
  a user" stays one operation
* every read is reachable only through a `profile_id`, which is what makes
  cross-account access structurally impossible rather than a rule to remember

**No table in this layer carries `run_id`, and `tests/test_daily.py` asserts the
column was never quietly added.**

### Why long format, again

`day_observations` and `day_reflections` are long - one row per recorded metric,
one row per answered prompt - for exactly the reason `001_initial.sql` gives for
`observations`. A student who rated their mood and skipped everything else has
**one row**. There is no representation of "focus = 0 because the form wanted a
number", because there is no focus row at all.

The wide alternative - twenty nullable columns on one table - puts a
plausible-looking number one careless `COALESCE` away, and would need a
migration every time a metric was added.

### What is *not* stored

There is no `week_data` JSON blob, and no JSON column anywhere in this layer.
`profiles.payload_json` remains what it always was: the onboarding answers
verbatim, unqueried and unaggregated.

---

## 3. Weeks

**A study week runs Monday to Sunday. Week 1 is the week containing the
profile's `term_start`.** `daily/calendar.py` is the only place that decides
this, and every consumer - repository, API, frontend - reads weeks through it or
through values it derived.

`term_start` is normalised to a Monday when stored. A term beginning on a
Wednesday would otherwise leave that week's Monday and Tuesday in a week 0 that
does not exist.

`term_start` is **nullable**. A profile that has declared none falls back to the
Monday of its earliest recorded day, and the timeline reports
`term_start_declared: false` so the UI can say the numbering is provisional
rather than presenting an invented week 1 as settled.

`day_records.week_index` is a **cached derivation** of `date`. Changing the
anchor re-derives every stored value in one transaction
(`Repository.set_term_start`), through `calendar.week_index` rather than through
SQL date arithmetic - so there is never a second implementation of week
numbering, and never a row whose stored week disagrees with the week its date
resolves to.

### There is no fixed number of weeks

`n_weeks` on the timeline is derived: week 1 to whichever is later, the last week
holding data or the week containing today. Today is included so a student always
has somewhere to put today's entry; nothing beyond it is manufactured.

Empty weeks appear in the strip because a calendar has them. They do **not** get
a rollup: a row of zeros reads as a measurement, so `rollups` covers only weeks
that hold rows.

---

## 4. Raw, derived and model output

The distinction the whole layer is built around.

| | Example | Where it lives | Labelled |
|---|---|---|---|
| **Raw** | "Studied operating systems, 09:00-11:00" | `day_activities`, `day_observations`, `day_reflections` | `recorded by you` |
| **Derived** | "Week 8: 6h 30m logged across 9 activities; mean mood 3.4 over 5 days" | computed on read by `daily/aggregate.py` | `derived` |
| **Model** | "Filtered engagement state -0.77 ± 0.62" | `twin_states`, written by the pipeline | `INFERRED` |

Two properties keep the middle column honest.

**A summary states its own coverage.** `minutes_logged` never travels without
`activities_without_duration`. "6h 30m this week" over a week where four of nine
activities carry no duration reads as a total and is not one.

**A metric nobody recorded is absent, not zero.** The rollup emits a key only
when at least one day in the week has a row for it, mirroring the storage. Every
metric summary carries `n`, because a mean over one day and a mean over seven
are different claims.

Nothing is stored pre-aggregated. A stored aggregate can silently disagree with
the rows beneath it; this one cannot, because it is recomputed from them on every
read.

---

## 5. Model integration status

Stated plainly, in the form the brief asked for.

```
Currently persisted:
    Day records, activities, structured daily metrics, written reflections.
    Raw, in normalised tables, owned by a profile.

Currently displayed:
    The full day (activities, metrics, reflections) in the day panel.
    Seven day slots per week with per-day counts.
    A timeline of every week the student has.

Currently aggregated:
    Weekly rollups computed on read by student_twin.daily.aggregate:
    activity counts and logged minutes by category, per-metric mean/min/max
    with n, days recorded, days with content, reflection count.

Currently consumed by the model:
    NOTHING. Not one field.

Future integration:
    A new adapter, not a shortcut from the aggregation into state/.
```

### Why not, specifically

The filter's emission models are fitted per channel: negative-binomial on
behaviour counts, Bernoulli on submission, Gaussian-on-logit on score. A weekly
mean of a self-reported 1-5 mood scale has **no fitted loading, no dispersion
parameter and no place in `TwinParameters`**. Feeding it in would require
inventing all three, and an invented loading is a fabricated result - the first
non-negotiable in `CLAUDE.md`.

There is also no reason to improvise, because the schema already names the right
route. `Channel.LIFESTYLE` / `CanonicalType.ACTIVITY_LOG` and
`Channel.SELF_REPORT` / `CanonicalType.PERCEIVED_LOAD` exist for exactly this
data and are declared **unavailable** by every current adapter, which is what
A-07 requires:

> Adding a survey instrument later is a new adapter, not a schema migration.

So the integration, when it is justified, is: a new adapter that reads these
tables, declares those two canonical types available, and is **refitted** - with
`CoverageManifest` and the capability tests doing their job on the result. Until
that adapter exists and has run, the claim is the one above, and the API repeats
it in a field rather than a footnote: `model_input: false` on every daily
payload.

### The seam that makes it possible later

`daily/aggregate.py` is the boundary. It takes raw day dicts and returns derived
weekly summaries, as pure functions over plain dicts, importing nothing from
`state/`, `models/`, `simulation/`, `evaluation/` or any adapter. A future
adapter attaches there, to a function that is already tested without a database.

It is a boundary and not an abstraction layer: there is no plugin registry, no
`DataSource` interface and no unused mapper waiting for a caller. The only
concession to a future outside source is the `source` column
(`student | system | import | other`), so an importer has somewhere honest to
declare itself instead of masquerading as a person typing.

---

## 6. Validation, and where each rule is enforced

Every rule below is enforced **twice**: once in pydantic at the HTTP boundary,
once as a SQL `CHECK`. The duplication follows the precedent of
`model_runs.n_dims` - a constraint only Python enforces is one a stray script can
route around by opening the database file directly.

| Rule | pydantic | SQL |
|---|---|---|
| Date is a real ISO calendar date | `pattern` + `cal.parse_date` | `CHECK (date IS strftime('%Y-%m-%d', date))` |
| One record per profile per date | - | `UNIQUE (profile_id, date)` -> `409` |
| Metric is known and in range | `check_metric` | per-metric `CHECK` |
| Category is in the vocabulary | `Literal[ACTIVITY_CATEGORIES]` | `CHECK category IN (...)` |
| Times are `HH:MM` | `pattern` | `GLOB '[0-2][0-9]:[0-5][0-9]'` |
| Duration is 1-1440 minutes | `ge`/`le` | `CHECK` |
| Prompt is in the vocabulary | `field_validator` | `CHECK prompt IN (...)` |
| Activity has a title | `min_length=1` | `CHECK length(trim(title)) > 0` |

Three rules have no SQL counterpart because they are not properties of a row:

* **A day in the future is refused** (`422 future_date`). Daily records describe
  what happened; a row dated next Tuesday is a typo or a plan, and planning is a
  different feature with different semantics.
* **`end_time` before `start_time` is refused** rather than wrapped past
  midnight. Guessing would put an invented eleven-hour study session in a weekly
  total. An overnight activity is recorded as two entries.
* **`minutes` is derived from a start/end pair** when one is not given, but an
  explicitly stated duration always wins - it is the more direct statement.

The vocabularies themselves are served at `GET /api/daily/vocabulary`, so the
frontend never keeps its own copy. A form whose options are typed out again in
JavaScript drifts from the `CHECK` the first time either changes, and the user
sees a `422` they cannot act on.

---

## 7. Isolation

There is still no authentication - `README.md` §12 lists it as a hard blocker
before any real cohort. What *is* implemented is that one account cannot reach
another's rows even by guessing an id:

* every route begins `/api/profiles/{profile_id}/...`
* every repository method takes `profile_id`; there is deliberately **no**
  `day_by_id(day_id)`
* the child queries in `_populate` join `day_records` and filter on `profile_id`
  in their own right, so a future caller that assembled the day list differently
  still could not pull another profile's children through
* activity routes resolve through `activity_day(profile_id, activity_id)`, which
  joins the owner in - so somebody else's activity is a `404`, not an edit

Asserted from both directions in `tests/test_daily.py` and
`tests/test_api_daily.py`.

---

## 8. Persistence, and the absence of a local fallback

The rest of the frontend falls back to `web/data.js` when the API is
unreachable, and says so in a banner. **The journal does not, and must not.**

A write that "succeeds" into `localStorage` while the server is down is exactly
the failure this feature exists to remove: the student closes the tab believing
their week is saved. So the journal reports the failure, keeps everything typed
in the form, and refuses to render anything it did not receive.

The only thing kept in `localStorage` is the `profile_id` - a pointer to a
server row, not the data itself, and only because there is no auth to resolve it
from a session.

---

## 9. Files

| File | Holds |
|---|---|
| `src/student_twin/daily/vocab.py` | closed vocabularies, ranges, labels |
| `src/student_twin/daily/calendar.py` | the only week-numbering implementation |
| `src/student_twin/daily/aggregate.py` | raw days -> derived weekly summaries |
| `src/student_twin/store/migrations/003_daily_records.sql` | the four tables |
| `src/student_twin/store/repository.py` | every query, all `profile_id`-scoped |
| `src/student_twin/api/routes_daily.py` | the routes |
| `src/student_twin/api/schemas.py` | request/response models |
| `src/student_twin/api/services.py` | day/week/timeline assembly |
| `web/journal.js`, `web/journal.css` | the screen |
| `tests/test_daily.py` | storage, calendar, aggregation, isolation |
| `tests/test_api_daily.py` | routes, validation, honesty guarantees |
