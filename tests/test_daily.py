"""Daily records: vocabulary, week arithmetic, storage and aggregation.

The database tests here are the counterpart to `test_store.py`: they exist
to catch a constraint that is documented but not enforced, a cascade that
does not cascade, or an isolation guarantee that holds only because no
route has yet been written to break it.

The aggregation tests assert two honesty properties that are easy to lose
in a refactor and impossible to notice from a screenshot:

* a metric nobody recorded is ABSENT from the rollup, not zero
* `minutes_logged` always travels with `activities_without_duration`, so
  a partial sum cannot be read as a total
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

import pytest

from student_twin.daily import calendar as cal
from student_twin.daily.aggregate import rollup_week, rollup_weeks
from student_twin.daily.vocab import (
    ACTIVITY_CATEGORIES,
    METRIC_RANGES,
    REFLECTION_PROMPTS,
    DailyValueError,
    check_metric,
    vocabulary,
)
from student_twin.store import migrate
from student_twin.store.db import Database
from student_twin.store.repository import Repository

TERM_START = "2026-06-22"          # a Monday
WEEK8_MONDAY = "2026-08-10"
WEEK8_THURSDAY = "2026-08-13"


@pytest.fixture()
def repo(tmp_path):
    path = tmp_path / "daily.db"
    migrate(path)
    db = Database(path)
    r = Repository(db)
    r.create_profile("p1", "2026-06-01T00:00:00+00:00", "A", True, "{}", TERM_START)
    yield r
    db.close()


@pytest.fixture()
def two_profiles(repo):
    repo.create_profile("p2", "2026-06-01T00:00:00+00:00", "B", True, "{}", TERM_START)
    return repo


# ------------------------------------------------------------- migration

def test_migration_003_applies_to_a_fresh_database(tmp_path):
    applied = migrate(tmp_path / "fresh.db")
    assert "003_daily_records" in applied


def test_migration_003_applies_to_an_existing_database(tmp_path):
    """The upgrade path matters more than the fresh one.

    A migration that only works on an empty file is useless to anybody who
    already has data, which is everybody who has run the project before.
    """
    path = tmp_path / "existing.db"
    db = Database(path)
    db.close()
    # Apply 001 and 002 only, as a database created before this feature had.
    # `student_twin.store.migrate` the FUNCTION shadows the module of the same
    # name in the package namespace, so the module is fetched from sys.modules.
    import importlib
    m = importlib.import_module("student_twin.store.migrate")
    every = m._discover()
    original = [f for f in every if not f.name.startswith("003")]
    m._discover = lambda: original                       # type: ignore[assignment]
    try:
        first = m.migrate(path)
    finally:
        m._discover = lambda: every                      # type: ignore[assignment]
    assert "003_daily_records" not in first

    # A profile as a pre-003 database held it: raw SQL against the old
    # column list, because the current repository writes `term_start` and
    # that column does not exist yet. This is the row the migration has to
    # preserve.
    db = Database(path)
    db.execute(
        """INSERT INTO profiles
           (profile_id, created_at, updated_at, display_name, consent,
            payload_json, observations)
           VALUES ('old','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00',
                   'Prior user', 1, '{"courses": ["ML"]}', 0)""")
    db.conn.commit()
    db.close()

    applied = migrate(path)
    assert applied == ["003_daily_records"]

    db = Database(path)
    r = Repository(db)
    # The pre-existing profile survived, and can now own days.
    assert r.profile("old")["display_name"] == "Prior user"
    assert r.profile("old")["days_recorded"] == 0
    r.create_day("old", "2026-08-13")
    assert r.profile("old")["days_recorded"] == 1
    db.close()


def test_migration_003_is_idempotent(tmp_path):
    path = tmp_path / "twice.db"
    migrate(path)
    assert migrate(path) == []


# ------------------------------------------------------------ vocabulary

def test_metric_ranges_are_enforced_not_clamped():
    assert check_metric("mood", 4) == 4.0
    with pytest.raises(DailyValueError):
        check_metric("mood", 6)
    with pytest.raises(DailyValueError):
        check_metric("mood", 0)
    with pytest.raises(DailyValueError):
        check_metric("vibes", 3)
    assert check_metric("sleep_hours", 0) == 0.0
    assert check_metric("sleep_hours", 7.5) == 7.5
    with pytest.raises(DailyValueError):
        check_metric("sleep_hours", 25)


def test_vocabulary_payload_covers_every_declared_term():
    v = vocabulary()
    assert {c["value"] for c in v["activity_categories"]} == set(ACTIVITY_CATEGORIES)
    assert {m["value"] for m in v["metrics"]} == set(METRIC_RANGES)
    assert {p["value"] for p in v["reflection_prompts"]} == set(REFLECTION_PROMPTS)
    for m in v["metrics"]:
        assert m["label"] and m["min"] < m["max"]


# -------------------------------------------------------------- calendar

def test_week_1_contains_the_term_start():
    assert cal.week_index(TERM_START, TERM_START) == 1
    assert cal.week_index("2026-06-28", TERM_START) == 1          # the Sunday
    assert cal.week_index("2026-06-29", TERM_START) == 2          # next Monday


def test_a_term_starting_midweek_still_has_a_seven_day_week_1():
    """Week 1 runs from the Monday, not from the declared date.

    Anchoring on a Wednesday would leave that week's Monday and Tuesday in
    a week 0 that does not exist.
    """
    wednesday = "2026-06-24"
    lo, hi = cal.week_bounds(1, wednesday)
    assert (lo, hi) == ("2026-06-22", "2026-06-28")
    assert cal.week_index("2026-06-22", wednesday) == 1


def test_week_8_is_the_week_the_ui_shows():
    assert cal.week_bounds(8, TERM_START) == (WEEK8_MONDAY, "2026-08-16")
    assert cal.week_index(WEEK8_THURSDAY, TERM_START) == 8
    assert cal.day_of_week(WEEK8_THURSDAY) == 4
    assert len(cal.week_dates(8, TERM_START)) == 7
    assert cal.week_dates(8, TERM_START)[3] == WEEK8_THURSDAY


def test_dates_are_parsed_not_guessed():
    with pytest.raises(cal.DateFormatError):
        cal.iso_date("13/08/2026")
    with pytest.raises(cal.DateFormatError):
        cal.iso_date("2026-02-30")


def test_default_anchor_is_absent_for_an_empty_history():
    assert cal.default_term_start([]) is None
    assert cal.default_term_start(["2026-08-13"]) == WEEK8_MONDAY


# ----------------------------------------------------------- day storage

def test_create_and_read_back_a_day(repo):
    day_id = repo.create_day("p1", WEEK8_THURSDAY)
    day = repo.day("p1", WEEK8_THURSDAY)
    assert day["day_id"] == day_id
    assert day["week_index"] == 8
    assert day["day_of_week"] == 4
    assert day["source"] == "student"
    # A brand-new day carries no content at all - not empty strings, not zeros.
    assert day["activities"] == []
    assert day["observations"] == {}
    assert day["reflections"] == {}


def test_a_duplicate_date_is_refused_by_the_database(repo):
    repo.create_day("p1", WEEK8_THURSDAY)
    with pytest.raises(sqlite3.IntegrityError):
        repo.create_day("p1", WEEK8_THURSDAY)


def test_two_students_may_record_the_same_date(repo, two_profiles):
    repo.create_day("p1", WEEK8_THURSDAY)
    repo.create_day("p2", WEEK8_THURSDAY)
    assert repo.day("p1", WEEK8_THURSDAY)["day_id"] != \
        repo.day("p2", WEEK8_THURSDAY)["day_id"]


def test_a_day_needs_a_profile_that_exists(repo):
    """The FK is the isolation guarantee's first half; it must be live."""
    with pytest.raises(sqlite3.IntegrityError):
        repo.create_day("ghost", WEEK8_THURSDAY)


def test_an_unparseable_date_never_reaches_a_row(repo):
    with pytest.raises(cal.DateFormatError):
        repo.create_day("p1", "not-a-date")


def test_the_date_check_constraint_rejects_a_direct_write(repo):
    """Bypassing the repository must not bypass the constraint."""
    with pytest.raises(sqlite3.IntegrityError):
        repo.db.execute(
            """INSERT INTO day_records
               (day_id, profile_id, date, week_index, day_of_week, source,
                created_at, updated_at)
               VALUES ('x','p1','2026-13-45',1,1,'student','n','n')""")


def test_update_and_delete_a_day(repo):
    day_id = repo.create_day("p1", WEEK8_THURSDAY)
    repo.replace_observations(day_id, {"mood": 4, "focus": 3})
    repo.replace_reflections(day_id, {"learned": "memoization"})
    day = repo.day("p1", WEEK8_THURSDAY)
    assert day["observations"] == {"mood": 4.0, "focus": 3.0}
    assert day["reflections"] == {"learned": "memoization"}

    # Replace, not merge: an omitted metric has been cleared.
    repo.replace_observations(day_id, {"mood": 2})
    assert repo.day("p1", WEEK8_THURSDAY)["observations"] == {"mood": 2.0}

    assert repo.delete_day("p1", WEEK8_THURSDAY) is True
    assert repo.day("p1", WEEK8_THURSDAY) is None
    assert repo.delete_day("p1", WEEK8_THURSDAY) is False


def test_blank_reflections_are_dropped_rather_than_stored(repo):
    """Otherwise "unanswered" and "answered with nothing" look identical."""
    day_id = repo.create_day("p1", WEEK8_THURSDAY)
    repo.replace_reflections(day_id, {"learned": "   ", "difficult": "recursion"})
    assert repo.day("p1", WEEK8_THURSDAY)["reflections"] == {"difficult": "recursion"}


def test_an_out_of_range_metric_is_refused_by_the_database(repo):
    day_id = repo.create_day("p1", WEEK8_THURSDAY)
    with pytest.raises(sqlite3.IntegrityError):
        repo.db.execute(
            "INSERT INTO day_observations (day_id, metric, value) VALUES (?,?,?)",
            (day_id, "mood", 9.0))
    with pytest.raises(sqlite3.IntegrityError):
        repo.db.execute(
            "INSERT INTO day_observations (day_id, metric, value) VALUES (?,?,?)",
            (day_id, "not_a_metric", 3.0))
    # sleep_hours has its own range, and 12 is legal there but not on a 1-5 scale
    repo.db.execute(
        "INSERT INTO day_observations (day_id, metric, value) VALUES (?,?,?)",
        (day_id, "sleep_hours", 12.0))


# ------------------------------------------------------------ activities

def test_many_activities_on_one_day_keep_their_order(repo):
    day_id = repo.create_day("p1", WEEK8_THURSDAY)
    titles = ["DBMS Lecture", "ML assignment", "Digital Twin work", "Gym",
              "Neural networks"]
    for t in titles:
        repo.create_activity(day_id, {"title": t, "category": "study"})
    got = repo.day("p1", WEEK8_THURSDAY)["activities"]
    assert [a["title"] for a in got] == titles
    assert [a["seq"] for a in got] == [0, 1, 2, 3, 4]


def test_update_and_delete_an_activity(repo):
    day_id = repo.create_day("p1", WEEK8_THURSDAY)
    aid = repo.create_activity(day_id, {"title": "Gym", "category": "extracurricular",
                                        "minutes": 60})
    assert repo.update_activity(aid, {"title": "Gym and swim", "minutes": 90}) is True
    a = repo.day("p1", WEEK8_THURSDAY)["activities"][0]
    assert a["title"] == "Gym and swim" and a["minutes"] == 90
    assert repo.delete_activity(aid) is True
    assert repo.day("p1", WEEK8_THURSDAY)["activities"] == []


def test_an_activity_needs_a_day_that_exists(repo):
    with pytest.raises(sqlite3.IntegrityError):
        repo.create_activity("no-such-day", {"title": "x", "category": "study"})


def test_activity_vocabularies_are_enforced_by_the_database(repo):
    day_id = repo.create_day("p1", WEEK8_THURSDAY)
    for bad in ({"title": "x", "category": "napping"},
                {"title": "", "category": "study"},
                {"title": "x", "category": "study", "start_time": "9am"},
                {"title": "x", "category": "study", "minutes": 0},
                {"title": "x", "category": "study", "importance": 9},
                {"title": "x", "category": "study", "status": "maybe"}):
        with pytest.raises(sqlite3.IntegrityError):
            repo.create_activity(day_id, bad)


def test_writing_to_a_day_marks_it_edited(repo):
    day_id = repo.create_day("p1", WEEK8_THURSDAY)
    before = repo.day("p1", WEEK8_THURSDAY)["updated_at"]
    repo.db.execute("UPDATE day_records SET updated_at = '2000-01-01T00:00:00+00:00' "
                    "WHERE day_id = ?", (day_id,))
    repo.db.conn.commit()
    repo.create_activity(day_id, {"title": "x", "category": "study"})
    after = repo.day("p1", WEEK8_THURSDAY)["updated_at"]
    assert after != "2000-01-01T00:00:00+00:00"
    assert before is not None


# -------------------------------------------------------------- cascades

def test_deleting_a_day_removes_everything_in_it(repo):
    day_id = repo.create_day("p1", WEEK8_THURSDAY)
    repo.create_activity(day_id, {"title": "x", "category": "study"})
    repo.replace_observations(day_id, {"mood": 3})
    repo.replace_reflections(day_id, {"notes": "n"})
    repo.delete_day("p1", WEEK8_THURSDAY)
    for table in ("day_activities", "day_observations", "day_reflections"):
        assert repo.db.scalar(
            f"SELECT COUNT(*) FROM {table} WHERE day_id = ?", (day_id,)) == 0


def test_deleting_a_profile_removes_their_whole_history(repo):
    """"Delete a user" stays one operation, as the profiles island promises."""
    day_id = repo.create_day("p1", WEEK8_THURSDAY)
    repo.create_activity(day_id, {"title": "x", "category": "study"})
    repo.replace_observations(day_id, {"mood": 3})
    assert repo.delete_profile("p1") is True
    assert repo.db.scalar("SELECT COUNT(*) FROM day_records") == 0
    assert repo.db.scalar("SELECT COUNT(*) FROM day_activities") == 0
    assert repo.db.scalar("SELECT COUNT(*) FROM day_observations") == 0


def test_daily_records_do_not_hang_off_a_model_run(repo):
    """A person's history must survive a re-ingest.

    Every model-derived table carries `run_id` and cascades from
    `model_runs`. These deliberately do not, and this asserts the columns
    were never quietly added.
    """
    cols = {r["name"] for r in repo.db.query("PRAGMA table_info(day_records)")}
    assert "run_id" not in cols
    for table in ("day_activities", "day_observations", "day_reflections"):
        assert "run_id" not in {
            r["name"] for r in repo.db.query(f"PRAGMA table_info({table})")}


# ------------------------------------------------------------- isolation

def test_one_student_cannot_read_another_students_day(repo, two_profiles):
    day_id = repo.create_day("p1", WEEK8_THURSDAY)
    repo.create_activity(day_id, {"title": "private", "category": "personal"})
    assert repo.day("p2", WEEK8_THURSDAY) is None
    assert repo.days_for_week("p2", 8) == []
    assert repo.days_between("p2", "2020-01-01", "2030-01-01") == []
    assert repo.all_days("p2") == []
    assert repo.day_id_for("p2", WEEK8_THURSDAY) is None


def test_one_student_cannot_reach_another_students_activity(repo, two_profiles):
    day_id = repo.create_day("p1", WEEK8_THURSDAY)
    aid = repo.create_activity(day_id, {"title": "private", "category": "personal"})
    assert repo.activity_day("p1", aid) is not None
    assert repo.activity_day("p2", aid) is None


def test_populate_never_leaks_children_across_profiles(repo, two_profiles):
    """The child queries filter on profile_id in their own right.

    If they relied on the parent list having been filtered, a future caller
    that built that list differently would leak.
    """
    d1 = repo.create_day("p1", WEEK8_THURSDAY)
    repo.create_activity(d1, {"title": "p1 activity", "category": "study"})
    repo.replace_observations(d1, {"mood": 5})
    repo.create_day("p2", WEEK8_THURSDAY)
    p2_day = repo.day("p2", WEEK8_THURSDAY)
    assert p2_day["activities"] == []
    assert p2_day["observations"] == {}


# ----------------------------------------------------------- week anchor

def test_moving_the_term_start_re_derives_every_stored_week(repo):
    """A cached derivation that is not refreshed is worse than no cache."""
    repo.create_day("p1", WEEK8_THURSDAY)
    assert repo.day("p1", WEEK8_THURSDAY)["week_index"] == 8
    repo.set_term_start("p1", "2026-08-10")          # week 8's Monday becomes week 1
    assert repo.day("p1", WEEK8_THURSDAY)["week_index"] == 1
    assert repo.days_for_week("p1", 1)
    assert repo.days_for_week("p1", 8) == []


def test_an_undeclared_anchor_is_inferred_from_the_earliest_day(repo):
    repo.create_profile("p3", "2026-06-01T00:00:00+00:00", "C", True, "{}")
    assert repo.term_start("p3") is None
    assert repo.effective_term_start("p3") is None      # nothing to infer from yet
    repo.create_day("p3", WEEK8_THURSDAY)
    assert repo.effective_term_start("p3") == WEEK8_MONDAY


def test_updating_a_profile_carries_the_anchor_change_through(repo):
    repo.create_day("p1", WEEK8_THURSDAY)
    repo.update_profile("p1", "2026-08-20T00:00:00+00:00", "A", True, "{}",
                        "2026-08-10")
    assert repo.day("p1", WEEK8_THURSDAY)["week_index"] == 1


# ------------------------------------------------------------ week counts

def test_week_counts_report_only_weeks_that_hold_rows(repo):
    d1 = repo.create_day("p1", WEEK8_THURSDAY)
    repo.create_activity(d1, {"title": "a", "category": "study"})
    repo.create_day("p1", "2026-08-14")
    repo.create_day("p1", "2026-06-23")               # week 1
    counts = {c["week"]: c for c in repo.week_counts("p1")}
    assert set(counts) == {1, 8}
    assert counts[8]["days_recorded"] == 2
    assert counts[8]["n_activities"] == 1
    assert counts[1]["n_activities"] == 0


# ----------------------------------------------------------- aggregation

def _day(week, dt, acts=(), obs=None, refl=None):
    return {"week_index": week, "date": dt, "activities": list(acts),
            "observations": dict(obs or {}), "reflections": dict(refl or {})}


def test_a_metric_nobody_recorded_is_absent_from_the_rollup():
    """The whole point of long-format storage, carried through to the summary."""
    days = [_day(8, WEEK8_THURSDAY, obs={"mood": 4}),
            _day(8, "2026-08-14", obs={"mood": 2})]
    r = rollup_week(days, 8, TERM_START)
    assert [m.metric for m in r.metrics] == ["mood"]
    assert r.metrics[0].mean == 3.0
    assert r.metrics[0].n == 2
    assert all(m.metric != "stress" for m in r.metrics)


def test_a_metric_recorded_once_reports_n_equals_one():
    r = rollup_week([_day(8, WEEK8_THURSDAY, obs={"focus": 5}),
                     _day(8, "2026-08-14", obs={})], 8, TERM_START)
    focus = next(m for m in r.metrics if m.metric == "focus")
    assert focus.n == 1 and focus.mean == 5.0


def test_minutes_logged_travels_with_its_coverage():
    """A sum over partial data must not be readable as a total."""
    days = [_day(8, WEEK8_THURSDAY, acts=[
        {"category": "class", "minutes": 90},
        {"category": "study", "minutes": None},
        {"category": "study", "minutes": 30},
    ])]
    r = rollup_week(days, 8, TERM_START)
    assert r.minutes_logged == 120
    assert r.activities_without_duration == 1
    study = next(c for c in r.by_category if c.category == "study")
    assert study.n_activities == 2 and study.minutes == 30 and study.without_duration == 1


def test_categories_that_did_not_occur_are_not_emitted_as_zeros():
    r = rollup_week([_day(8, WEEK8_THURSDAY,
                          acts=[{"category": "class", "minutes": 60}])],
                    8, TERM_START)
    assert [c.category for c in r.by_category] == ["class"]


def test_an_opened_but_empty_day_counts_as_recorded_not_as_content():
    r = rollup_week([_day(8, WEEK8_THURSDAY)], 8, TERM_START)
    assert r.days_recorded == 1
    assert r.days_with_content == 0
    assert r.n_activities == 0 and r.minutes_logged == 0
    assert r.metrics == []


def test_rollup_ignores_days_from_other_weeks():
    days = [_day(8, WEEK8_THURSDAY, obs={"mood": 4}),
            _day(9, "2026-08-20", obs={"mood": 1})]
    assert rollup_week(days, 8, TERM_START).metrics[0].mean == 4.0


def test_rollup_weeks_covers_only_weeks_that_exist():
    """No padding to twenty, or to any other number."""
    days = [_day(1, "2026-06-23"), _day(8, WEEK8_THURSDAY)]
    assert [r.week for r in rollup_weeks(days, TERM_START)] == [1, 8]
    assert rollup_weeks([], TERM_START) == []


def test_rollup_week_reports_the_right_calendar_bounds():
    r = rollup_week([], 8, TERM_START)
    assert (r.start_date, r.end_date) == (WEEK8_MONDAY, "2026-08-16")


# ------------------------------------------------ the whole loop, once

def test_a_full_day_survives_a_round_trip_through_the_database(repo):
    """Write everything a day can hold, read it back, and check nothing moved."""
    day_id = repo.create_day("p1", WEEK8_THURSDAY)
    repo.create_activity(day_id, {
        "title": "DBMS Lecture", "category": "class", "subject": "DBMS",
        "start_time": "09:00", "end_time": "10:30", "minutes": 90,
        "importance": 4, "status": "done", "detail": "normalisation"})
    repo.create_activity(day_id, {"title": "Gym", "category": "extracurricular",
                                  "start_time": "17:00", "minutes": 60})
    repo.replace_observations(day_id, {"mood": 4, "stress": 3, "focus": 4,
                                       "sleep_hours": 7.5})
    repo.replace_reflections(day_id, {
        "difficult": "dynamic programming",
        "learned": "memoization finally clicked",
        "went_well": "finished the assignment"})

    day = repo.day("p1", WEEK8_THURSDAY)
    assert len(day["activities"]) == 2
    assert day["activities"][0]["start_time"] == "09:00"
    assert day["activities"][0]["status"] == "done"
    assert day["observations"]["sleep_hours"] == 7.5
    assert day["reflections"]["difficult"] == "dynamic programming"

    r = rollup_week(repo.days_for_week("p1", 8), 8, TERM_START)
    assert r.days_recorded == 1 and r.n_activities == 2
    assert r.minutes_logged == 150 and r.activities_without_duration == 0
    assert {m.metric for m in r.metrics} == {"mood", "stress", "focus", "sleep_hours"}
    assert r.n_reflections == 3


def test_a_long_history_spans_many_weeks(repo):
    """Nothing in the storage layer knows or cares how long twenty weeks is."""
    start = date.fromisoformat(TERM_START)
    for i in range(0, 210, 3):                     # 30 weeks of every third day
        repo.create_day("p1", (start + timedelta(days=i)).isoformat())
    weeks = {c["week"] for c in repo.week_counts("p1")}
    assert max(weeks) == 30
    assert len(repo.all_days("p1")) == 70


# ------------------------------------------------------- module boundary

def test_the_daily_package_imports_nothing_from_the_model_or_the_store():
    """`daily/` is the raw layer and the seam a future adapter attaches to.

    A dependency in either direction collapses it: importing the store would
    make the aggregation untestable without a database, and importing
    `state/` would put a raw-input module one line away from feeding the
    filter something with no fitted emission model behind it.

    Checked by reading the source rather than by inspecting `sys.modules`,
    because an import that only happens inside a function would not show up
    in the latter until it ran.
    """
    import ast
    import pathlib

    import student_twin.daily as pkg

    forbidden = ("adapters", "store", "state", "models", "simulation",
                 "evaluation", "pipeline", "features")
    root = pathlib.Path(pkg.__file__).parent
    offenders = []
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                # `from .calendar import ...` has module="calendar", level=1;
                # only a sibling, which is fine. `from ..store import x` has
                # level=2 and is not.
                names = [("." * node.level) + (node.module or "")]
            for name in names:
                bare = name.lstrip(".").split(".")[0]
                if bare in forbidden:
                    offenders.append(f"{path.name}: {name}")
    assert not offenders, (
        "student_twin.daily must not import the model or the store: "
        + ", ".join(offenders))


def test_the_daily_package_needs_no_third_party_dependency():
    """It is stdlib only, like the store. Nothing here needs pandas or numpy.

    The aggregation is arithmetic over a handful of dicts. Reaching for a
    frame to do it would add a dependency to a layer whose whole job is to be
    importable from anywhere.
    """
    import ast
    import pathlib
    import sys

    import student_twin.daily as pkg

    stdlib = sys.stdlib_module_names
    root = pathlib.Path(pkg.__file__).parent
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    assert a.name.split(".")[0] in stdlib, f"{path.name}: {a.name}"
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                assert (node.module or "").split(".")[0] in stdlib,                     f"{path.name}: {node.module}"
