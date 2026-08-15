# The backend, explained from zero

Written for someone who has built the model and the frontend but has not done
backend work before. No prior backend vocabulary is assumed. Every concept is
introduced generically, then immediately shown in StudyTwin's own code.

---

## Part 1 — The words

### What is a backend?

Your browser can draw things. It cannot keep things.

Close the tab and everything in the page is gone. Open StudyTwin on a different
laptop and it knows nothing about what you did on this one. A browser is a
renderer with amnesia.

A **backend** is a program running on a computer somewhere that *does* keep
things, and that answers questions from browsers. It has three jobs:

1. **Store** data so it survives the tab closing.
2. **Compute** things that are too slow, too secret, or too large for a browser.
3. **Answer questions** from any browser that asks.

**In StudyTwin.** Fitting the model takes about 5 seconds of CPU on 150
students. If the browser did that, every page load would take 5 seconds and
every user's laptop would be doing identical arithmetic. Instead: the model runs
**once**, the results are stored, and the backend hands them out in
milliseconds.

### What is an API?

An **API** (Application Programming Interface) is the menu of questions a
backend will answer.

A restaurant analogy that actually holds up: the menu lists what you may order
and what you get. You do not walk into the kitchen. You do not need to know how
the dish is made. You order by name, and something specific arrives.

An API is that menu, for programs.

**In StudyTwin**, the menu includes:

```
GET  /api/health                        →  is everything working?
GET  /api/students                      →  who is in this run?
GET  /api/students/S000021/twin         →  everything about this student
GET  /api/evaluation                    →  how good is the model?
POST /api/profiles                      →  save a Twin someone created
```

`GET` means *give me something*. `POST` means *here, store this*. There are also
`PUT` (replace this) and `DELETE` (remove this). These four are called **HTTP
methods** and they are just verbs.

### What is JSON?

The language browsers and backends use to exchange data. It is text that looks
like this:

```json
{
  "student_id": "S000021",
  "n_weeks": 20,
  "event_observed": false
}
```

Curly braces make an object. Square brackets make a list. Values are text,
numbers, `true`/`false`, or `null` (meaning "nothing here"). That is the entire
language.

### What is a database?

A program whose only job is storing data in an organised way and finding it
again quickly.

Think of a spreadsheet workbook, except:

* it can hold millions of rows without slowing down,
* it can enforce rules ("this column may never be empty"),
* many programs can read it at once safely.

**In StudyTwin** the database is **SQLite**, which is unusual in a useful way:
it is not a server you start. It is a single file, `data/studytwin.db`. You can
copy it, email it, or commit it to a release. That is exactly right for a
research prototype.

### What is a table?

One kind of thing, as a grid. StudyTwin has a `students` table, a `twin_states`
table, a `hazards` table, and so on.

```
students
┌──────────┬────────────┬─────────┬────────────────┬────────────┐
│ run_id   │ student_id │ n_weeks │ event_observed │ event_week │
├──────────┼────────────┼─────────┼────────────────┼────────────┤
│ f7bf16…  │ S000021    │ 20      │ 0              │ NULL       │
│ f7bf16…  │ S000022    │ 14      │ 1              │ 14         │
└──────────┴────────────┴─────────┴────────────────┴────────────┘
```

### What is a row? A column?

A **row** is one instance of the thing. One row of `students` is one student.

A **column** is one property, with a fixed type. `n_weeks` is always a whole
number. Putting the word `"twenty"` there is rejected.

### What is a primary key?

The column (or set of columns) that uniquely identifies a row. No two rows may
share one.

**In StudyTwin** the primary key of `students` is `(run_id, student_id)` — *both
together*. That is a **composite key**, and the reason is worth understanding:

> The same student appearing in two different model runs is **two rows**, not
> one. Their estimates differ, because a different run fitted them. `S000021`
> alone would not be unique. `(run f7bf16…, student S000021)` is.

### What is a foreign key?

A column that points at another table's primary key, with the database enforcing
that the target exists.

`twin_states.run_id` is a foreign key to `model_runs.run_id`. So:

* you cannot store a state for a run that does not exist, and
* when you delete a run, everything that pointed at it goes too — that is
  `ON DELETE CASCADE`.

**Why StudyTwin cares.** A latent state with no run attached has no seed, no
model version and no code revision behind it. It is unreproducible, therefore it
is not a result. The foreign key makes an orphan number *impossible* rather than
merely discouraged.

> ⚠️ SQLite turns foreign keys **off** by default. Every `ON DELETE CASCADE` in
> the schema would silently do nothing. `store/db.py` runs
> `PRAGMA foreign_keys = ON` on every connection, and a test fails if that line
> is ever removed.

### What is SQL?

The language for asking a database questions.

```sql
SELECT t, mean, sd
FROM   twin_states
WHERE  run_id = ? AND student_id = ? AND dim_name = 'engagement'
ORDER BY t;
```

Read it as English: *select these columns, from this table, where these
conditions hold, sorted by week*.

Those `?` marks are **bound parameters** and they matter enormously — see
Part 4.

### What is an ORM? (and why StudyTwin does not use one)

An **ORM** (Object-Relational Mapper) is a library that lets you write Python
objects and generates the SQL for you.

StudyTwin deliberately does not use one. Three reasons:

1. **The schema is the documentation.** Reading `001_initial.sql` teaches you
   the data model. Reading a declarative-base class hierarchy teaches you the
   ORM.
2. **Every query here is simple** — a select over a composite key. An ORM's real
   value is managing complicated relationships, which we do not have.
3. **`sqlite3` is in Python's standard library**, so persistence costs zero
   extra packages.

You are therefore reading real SQL in `store/repository.py`, and so is anyone
reviewing this project.

### What is a migration?

A recorded, numbered change to the shape of the database.

You cannot just edit a table on a running system — other copies of the database
would still have the old shape. So changes are written as numbered files that
are applied in order, each exactly once.

**In StudyTwin**, `src/student_twin/store/migrations/`:

```
001_initial.sql            create every table
002_prior_uncertainty.sql  add prior_sd and posterior_sd
```

A table called `schema_migrations` records which have run. Running `migrate`
twice is safe — the second time does nothing.

There is one clever guard. Each migration's contents are hashed. If you *edit* a
migration that has already run, you get:

```
migration 001_initial has already been applied but its contents changed.
Add a new migration instead of editing an applied one.
```

Without that check, your laptop and a teammate's could end up with different
schemas and neither of you would know.

### Why migration 002 exists — a real example

`001` stored the **mean** of the model's prediction but not its **uncertainty**.

The landing page needs to show *"predicting widens the uncertainty, updating
narrows it again"*. Without the stored uncertainty, the only way to draw that was
to recompute the equation `P_pred = F P Fᵀ + Q` in JavaScript.

That would mean **the model existed in two places** — Python and the browser —
and they could disagree. So instead of writing the equation twice, we added two
columns.

That is the kind of decision migrations are for.

---

## Part 2 — What happens when you open StudyTwin

Follow one page load all the way down and back.

### Step 0 — before anyone opens anything

Somebody ran:

```bash
python scripts/ingest_run.py --students 250 --weeks 20
```

That ran the **actual model** (about 30 seconds) and wrote every number into the
database with a `run_id`. This happens **once**, not per visitor.

### Step 1 — you type the address

```
http://127.0.0.1:8000
```

Your browser asks that address for a page. The backend hands back
`web/index.html`, then the CSS and JavaScript files it references.

### Step 2 — the page asks for data

`web/app.js` starts and immediately shows a **loading state** — a heading, a
sentence saying what it is fetching, and a progress bar. Not a blank screen, and
not fake numbers.

Then `web/api.js` asks four questions at once:

```
GET /api/health
GET /api/students/demo
GET /api/students/S000021/twin
GET /api/evaluation
```

### Step 3 — the backend receives the question

FastAPI matches the URL to a function in `api/routes.py`:

```python
@router.get("/students/{student_id}/twin", response_model=TwinPayload)
def student_twin(student_id: str, run_id: str = Depends(resolve_run),
                 repo: Repository = Depends(get_repo)):
    return services.twin_payload(repo, run_id, student_id)
```

Three things happened before your code ran:

* `student_id` was pulled out of the URL,
* `resolve_run` worked out which run to read (the newest, if unspecified),
* `get_repo` opened a database connection and will close it afterwards.

That is **dependency injection**: the framework supplies what the function
needs, so the function does not fetch it itself.

### Step 4 — the backend asks the database

`store/repository.py` runs about a dozen `SELECT`s: states, baseline, hazards,
observations, features, attribution, scenarios.

### Step 5 — the backend shapes the answer

`api/services.py` turns database rows into the shape the frontend wants —
grouping long rows into series, putting dimensions in the model's order.

**It does not calculate anything the model should have calculated.** That is the
rule the whole architecture is built around.

### Step 6 — the answer is checked before it leaves

`response_model=TwinPayload` means FastAPI validates the payload against a
declared schema. If a field is missing or the wrong type, **the server raises**
rather than sending a broken payload the browser will fail on later.

Errors caught on the server are debuggable. Errors caught in a browser are not.

### Step 7 — JSON travels back

### Step 8 — the frontend draws

`web/api.js` converts the payload into the frontend's internal *view model*;
`app.js` and `charts.js` draw it.

### The whole path

```
Browser ──► FastAPI ──► Repository ──► SQLite
                                          │
Browser ◄── JSON ◄── Services ◄───────────┘

                 ...and, once, offline:

adapters ──► pipeline ──► ingest ──► SQLite
```

### What if the backend is not running?

`web/api.js` waits 6 seconds, gives up, and falls back to `web/data.js` — a
frozen export of a real run bundled with the site. The page then shows a banner
that cannot be dismissed:

> **Offline snapshot.** The API at http://127.0.0.1:8000 did not respond. These
> are real pipeline numbers from a bundled export, not live results.

Three properties matter here:

1. the demo still works with no backend,
2. the numbers are still real,
3. **it says so.** A snapshot silently standing in for live data is the failure
   this entire layer exists to prevent.

If both fail, you get an error naming what failed. **Never a placeholder
number.**

---

## Part 3 — StudyTwin's backend, file by file

```
src/student_twin/
├── store/                    ← everything about storage
│   ├── db.py                 open connections, set pragmas, transactions
│   ├── migrate.py            apply numbered .sql files, once each
│   ├── migrations/*.sql      the schema itself
│   ├── ingest.py             PipelineResult → database   (ONLY writer)
│   └── repository.py         database → dicts            (ONLY reader)
│
└── api/                      ← everything about HTTP
    ├── settings.py           configuration from environment variables
    ├── schemas.py            the shape of every request and response
    ├── deps.py               per-request database connection
    ├── services.py           rows → payloads (shape, never estimate)
    ├── routes.py             URL → function
    └── app.py                assemble the app, CORS, errors, static files
```

### `store/db.py` — connections

```python
conn.execute("PRAGMA foreign_keys = ON")    # or every CASCADE is a lie
conn.execute("PRAGMA journal_mode = WAL")   # read while an ingest writes
```

Also `transaction()`, which makes a write **all-or-nothing**:

```python
with transaction(db.conn):
    ...many inserts...
```

If anything raises, everything rolls back. A half-ingested run looks like a
result and is not one.

### `store/ingest.py` — the only writer

Takes a `PipelineResult` and writes it. **Computes nothing.** If a value is not
in the pipeline's output it does not get a column.

### `store/repository.py` — the only reader

Every `SELECT` in the project. Routes never contain SQL, so all the parameter
binding and joins are reviewable in one file.

### `api/schemas.py` — the contract, in code

```python
class HazardPoint(BaseModel):
    t: int
    hazard: float = Field(ge=0.0, le=1.0)   # must be a probability
    cum_risk: float = Field(ge=0.0, le=1.0)
    y: int
```

`ge`/`le` are enforced. A hazard of 1.4 cannot leave this server.

### `api/settings.py` — configuration

Every setting reads an environment variable with a safe default. Nothing is
hard-coded:

```python
database_path = os.environ.get("STUDYTWIN_DB", "data/studytwin.db")
```

**Why this matters even here.** The habit of putting configuration in code is
how passwords end up in git. There is no password in StudyTwin — but the habit
is the point, and the day a real database URL is needed, the slot already exists.

### `api/app.py` — assembly

Creates the app, sets CORS, installs an error handler, mounts `/api`, and serves
`web/` at `/` so the whole product runs from one process.

---

## Part 4 — Things that will bite you

### Bound parameters, or: SQL injection

**Never** do this:

```python
db.execute(f"SELECT * FROM students WHERE student_id = '{student_id}'")
```

If someone passes `x'; DROP TABLE students;--`, you just handed them your
database.

**Always** do this:

```python
db.execute("SELECT * FROM students WHERE student_id = ?", (student_id,))
```

The `?` is a **bound parameter**. The value is sent separately from the query
and is never parsed as SQL. It cannot become a command.

Every query in StudyTwin uses bound parameters, and
`tests/test_api.py::test_sql_injection_in_a_path_parameter_is_inert` fires that
exact attack and asserts it 404s harmlessly.

### `NULL` is not zero

`students.event_week IS NULL` means *this student never withdrew* — they are
**censored**. It does **not** mean they withdrew in week 0.

Getting this wrong inflates every metric in the project. The database allows
`NULL` there specifically so the distinction cannot be lost.

### Restart the server after changing Python

This caught me twice while building this. `uvicorn` imports your code once at
startup. Edit a `.py` file and the running server still has the old version.

* Development: `uvicorn ... --reload`
* Otherwise: stop it and start it again

**Symptom:** you fixed something, the tests pass, and the browser still shows the
old behaviour. The server is stale, not your code.

### CORS

A browser refuses to let a page on one address read data from a different
address, unless that address says it is allowed. This is a security feature.

StudyTwin serves the page and the API from the same address, so it usually does
not arise. It does when you open the static server on `:8777` and the API is on
`:8000` — which is why `settings.py` lists both. Never `*`.

---

## Part 5 — Running it

```bash
# 1. create/upgrade the database
python -m student_twin.store.migrate

# 2. run the model and store the result   (~30 s)
python scripts/ingest_run.py --students 250 --weeks 20

# 3. start the server
uvicorn student_twin.api.app:app --port 8000

# 4. open
#    http://127.0.0.1:8000            the product
#    http://127.0.0.1:8000/api/docs   the API, explorable in a browser
```

**`/api/docs` is worth ten minutes of your time.** FastAPI generates it from the
same schemas it validates against, so it cannot go out of date. You can click
any endpoint, press *Try it out*, and see the real response.

### Checking it works

```bash
curl http://127.0.0.1:8000/api/health
```

```json
{"status":"ok","database":true,"migrations_applied":2,"runs":1,
 "latest_run_id":"f7bf16…","model_version":"0.1.0"}
```

`"status":"degraded"` means the database is reachable but empty — run step 2.

### Running the tests

```bash
python -m pytest tests/test_store.py tests/test_api.py -v
```

These use a temporary database, so they never touch your real one.

---

## Part 6 — What to learn next

In the order that will help you most.

1. **SQL joins.** You can read a `SELECT` now. `JOIN` is how two tables get
   combined; `store/repository.py::cohort_summary` is a real example to trace.
2. **HTTP status codes.** 200 ok, 201 created, 204 no content, 400 bad request,
   403 forbidden, 404 not found, 422 validation failed, 500 server error.
   StudyTwin uses every one of these.
3. **Read `/api/docs`.** Explore the API you now own.
4. **Transactions and atomicity.** Why `test_ingest_is_atomic` matters.
5. **Authentication**, when — and only when — real student data is involved.
   Right now there are no accounts, and that is a deliberate, documented
   decision (`API_SPEC.md` → *Security*), not an oversight.
6. **Indexes.** Why `ix_state_student_week` makes a chart load instantly, and
   what happens without it.

---

## One-page summary

| Word | Means | In StudyTwin |
|---|---|---|
| Backend | Program that stores data and answers questions | `src/student_twin/api/` + `store/` |
| API | The menu of questions | 16 routes under `/api` |
| Endpoint | One item on the menu | `GET /api/students/{id}/twin` |
| JSON | The text format for the answers | every response |
| Database | Organised, durable storage | SQLite, `data/studytwin.db` |
| Table | One kind of thing, as a grid | `students`, `twin_states`, … |
| Row | One instance | one student in one run |
| Column | One property | `theta`, `hazard`, `sd` |
| Primary key | What makes a row unique | `(run_id, student_id)` |
| Foreign key | A pointer the database enforces | `twin_states.run_id → model_runs` |
| SQL | The query language | `store/repository.py` |
| Bound parameter | `?` — the reason injection fails | every query |
| Migration | A numbered, one-time schema change | `migrations/001`, `002` |
| ORM | Library that writes SQL for you | **not used**, on purpose |
| CORS | Rule about cross-address requests | `settings.py` |
| Environment variable | Configuration outside the code | `STUDYTWIN_DB` |
