"""Daily-record routes: CRUD, validation, isolation, and the honesty guarantees.

The last group matters most, for the same reason it does in `test_api.py`.
It is easy to build a journal that stores the right rows and then renders a
zero where a student recorded nothing, or prints a weekly total over data
that is half missing. These tests assert that neither can happen through
the API:

* a metric that was not recorded is ABSENT from the payload
* `model_input` is present and False on every daily payload
* `minutes_logged` never travels without `activities_without_duration`
* an empty week returns seven slots and zeros in `days_recorded`, not a 404

The isolation group asserts it from both directions: profile B cannot read
profile A's day, and cannot reach A's activity by id either.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from student_twin.store import migrate  # noqa: E402

TERM_START = "2026-06-22"          # a Monday
WEEK8_MONDAY = "2026-08-10"
WEEK8_THURSDAY = "2026-08-13"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """An API over an empty database.

    No pipeline run is ingested: daily records are deliberately independent
    of `model_runs`, and a fixture that needed one would hide it if that
    ever stopped being true.
    """
    db_path = tmp_path_factory.mktemp("apid") / "daily.db"
    migrate(db_path)
    import student_twin.api.settings as st
    st.get_settings.cache_clear()
    os.environ["STUDYTWIN_DB"] = str(db_path)
    os.environ["STUDYTWIN_SERVE_WEB"] = "0"
    from student_twin.api.app import create_app

    with TestClient(create_app()) as c:
        yield c
    st.get_settings.cache_clear()


def new_profile(client, name="A", term_start=TERM_START):
    r = client.post("/api/profiles", json={
        "display_name": name, "consent": True, "payload": {"courses": ["ML"]},
        "term_start": term_start})
    assert r.status_code == 201, r.text
    return r.json()["profile_id"]


@pytest.fixture()
def pid(client):
    return new_profile(client)


# ------------------------------------------------------------- vocabulary

def test_vocabulary_is_served_so_the_client_keeps_no_copy(client):
    v = client.get("/api/daily/vocabulary").json()
    assert {c["value"] for c in v["activity_categories"]} >= {"class", "study", "exam"}
    metrics = {m["value"]: m for m in v["metrics"]}
    assert metrics["mood"]["min"] == 1 and metrics["mood"]["max"] == 5
    assert metrics["sleep_hours"]["max"] == 24
    assert {p["value"] for p in v["reflection_prompts"]} >= {"difficult", "learned"}


def test_openapi_documents_the_daily_routes(client):
    spec = client.get("/api/openapi.json").json()
    for path in ("/api/daily/vocabulary",
                 "/api/profiles/{profile_id}/timeline",
                 "/api/profiles/{profile_id}/weeks/{week}",
                 "/api/profiles/{profile_id}/days",
                 "/api/profiles/{profile_id}/days/{day_date}",
                 "/api/profiles/{profile_id}/days/{day_date}/activities",
                 "/api/profiles/{profile_id}/activities/{activity_id}"):
        assert path in spec["paths"], f"{path} missing from the OpenAPI spec"


# ---------------------------------------------------------------- profile

def test_a_profile_declares_its_anchor_and_its_day_count(client, pid):
    p = client.get(f"/api/profiles/{pid}").json()
    # Normalised to the Monday of the declared week on the way in.
    assert p["term_start"] == TERM_START
    assert p["days_recorded"] == 0
    assert p["observations"] == 0
    assert p["model_input"] is False


def test_a_midweek_anchor_is_normalised_to_its_monday(client):
    other = new_profile(client, "Wed", term_start="2026-06-24")
    assert client.get(f"/api/profiles/{other}").json()["term_start"] == TERM_START


# --------------------------------------------------------------- the week

def test_an_untouched_week_returns_seven_slots_not_a_404(client, pid):
    """The screen exists so an empty week can be filled in."""
    r = client.get(f"/api/profiles/{pid}/weeks/8")
    assert r.status_code == 200
    b = r.json()
    assert [s["weekday"] for s in b["slots"]] == [
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    assert b["start_date"] == WEEK8_MONDAY and b["end_date"] == "2026-08-16"
    assert all(s["recorded"] is False for s in b["slots"])
    assert all(s["n_activities"] == 0 for s in b["slots"])
    assert b["days"] == []
    assert b["rollup"]["days_recorded"] == 0
    assert b["rollup"]["metrics"] == []
    assert b["derived"] is True


def test_week_slots_carry_the_dates_the_ui_needs(client, pid):
    b = client.get(f"/api/profiles/{pid}/weeks/8").json()
    assert b["slots"][3]["date"] == WEEK8_THURSDAY
    assert b["slots"][3]["day_of_week"] == 4


def test_the_same_machinery_serves_any_week_not_only_week_8(client, pid):
    for week in (1, 2, 8, 17, 40):
        b = client.get(f"/api/profiles/{pid}/weeks/{week}").json()
        assert b["week"] == week and len(b["slots"]) == 7
        assert b["slots"][0]["day_of_week"] == 1


def test_week_bounds_are_validated(client, pid):
    assert client.get(f"/api/profiles/{pid}/weeks/0").status_code == 422
    assert client.get(f"/api/profiles/{pid}/weeks/99999").status_code == 422


# ---------------------------------------------------------- create a day

def test_create_a_day_with_everything_in_it(client, pid):
    r = client.post(f"/api/profiles/{pid}/days", json={
        "date": WEEK8_THURSDAY,
        "observations": {"mood": 4, "stress": 2, "sleep_hours": 7},
        "reflections": {"difficult": "dynamic programming",
                        "learned": "memoization"},
        "activities": [
            {"title": "DBMS Lecture", "category": "class",
             "start_time": "09:00", "end_time": "10:30"},
            {"title": "ML assignment", "category": "assignment",
             "subject": "Machine Learning", "minutes": 120, "status": "partial"},
        ]})
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["week"] == 8 and b["day_of_week"] == 4
    assert b["observations"] == {"mood": 4.0, "stress": 2.0, "sleep_hours": 7.0}
    assert b["reflections"]["difficult"] == "dynamic programming"
    assert [a["title"] for a in b["activities"]] == ["DBMS Lecture", "ML assignment"]
    # 09:00-10:30 derived to 90 minutes rather than demanding both.
    assert b["activities"][0]["minutes"] == 90
    assert b["model_input"] is False


def test_a_duplicate_date_is_409_not_a_silent_merge(client):
    p = new_profile(client, "dup")
    assert client.post(f"/api/profiles/{p}/days",
                       json={"date": WEEK8_THURSDAY}).status_code == 201
    r = client.post(f"/api/profiles/{p}/days", json={"date": WEEK8_THURSDAY})
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "day_exists"


def test_a_missing_day_is_404_with_a_hint(client, pid):
    r = client.get(f"/api/profiles/{pid}/days/2026-08-11")
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "day_not_found"
    assert "PUT" in r.json()["detail"]["hint"]


def test_days_for_an_unknown_profile_are_404(client):
    assert client.get("/api/profiles/nope/timeline").status_code == 404
    assert client.get("/api/profiles/nope/weeks/8").status_code == 404
    assert client.get("/api/profiles/nope/days").status_code == 404
    assert client.post("/api/profiles/nope/days",
                       json={"date": WEEK8_THURSDAY}).status_code == 404


# ------------------------------------------------------- update a day

def test_put_creates_or_replaces_and_never_merges(client):
    p = new_profile(client, "put")
    r = client.put(f"/api/profiles/{p}/days/{WEEK8_THURSDAY}",
                   json={"observations": {"mood": 4, "focus": 3},
                         "reflections": {"notes": "first"}})
    assert r.status_code == 200
    assert r.json()["observations"] == {"mood": 4.0, "focus": 3.0}

    # An omitted metric has been CLEARED. A student who deletes their focus
    # rating and saves must not find it still there.
    r = client.put(f"/api/profiles/{p}/days/{WEEK8_THURSDAY}",
                   json={"observations": {"mood": 2}, "reflections": {}})
    assert r.json()["observations"] == {"mood": 2.0}
    assert r.json()["reflections"] == {}


def test_put_leaves_activities_alone(client):
    p = new_profile(client, "keep")
    client.post(f"/api/profiles/{p}/days", json={"date": WEEK8_THURSDAY})
    client.post(f"/api/profiles/{p}/days/{WEEK8_THURSDAY}/activities",
                json={"title": "Gym", "category": "extracurricular"})
    r = client.put(f"/api/profiles/{p}/days/{WEEK8_THURSDAY}",
                   json={"observations": {"mood": 5}})
    assert len(r.json()["activities"]) == 1, (
        "a whole-day save must not re-create the activity rows and invalidate "
        "the ids the client is holding")


def test_delete_a_day_removes_everything_in_it(client):
    p = new_profile(client, "del")
    client.post(f"/api/profiles/{p}/days", json={
        "date": WEEK8_THURSDAY, "observations": {"mood": 3},
        "activities": [{"title": "x", "category": "study"}]})
    assert client.delete(f"/api/profiles/{p}/days/{WEEK8_THURSDAY}").status_code == 204
    assert client.get(f"/api/profiles/{p}/days/{WEEK8_THURSDAY}").status_code == 404
    assert client.delete(f"/api/profiles/{p}/days/{WEEK8_THURSDAY}").status_code == 404
    assert client.get(f"/api/profiles/{p}/weeks/8").json()["rollup"]["n_activities"] == 0


# ------------------------------------------------------------ activities

def test_activity_crud(client):
    p = new_profile(client, "acts")
    client.post(f"/api/profiles/{p}/days", json={"date": WEEK8_THURSDAY})
    made = []
    for title in ("DBMS Lecture", "ML assignment", "Gym"):
        r = client.post(f"/api/profiles/{p}/days/{WEEK8_THURSDAY}/activities",
                        json={"title": title, "category": "study"})
        assert r.status_code == 201, r.text
        made.append(r.json())
    assert [a["seq"] for a in made] == [0, 1, 2]

    r = client.put(f"/api/profiles/{p}/activities/{made[2]['activity_id']}",
                   json={"title": "Gym and swim", "category": "extracurricular",
                         "minutes": 90, "status": "done"})
    assert r.status_code == 200
    assert r.json()["title"] == "Gym and swim" and r.json()["minutes"] == 90

    day = client.get(f"/api/profiles/{p}/days/{WEEK8_THURSDAY}").json()
    assert [a["title"] for a in day["activities"]] == [
        "DBMS Lecture", "ML assignment", "Gym and swim"]

    assert client.delete(
        f"/api/profiles/{p}/activities/{made[0]['activity_id']}").status_code == 204
    day = client.get(f"/api/profiles/{p}/days/{WEEK8_THURSDAY}").json()
    assert len(day["activities"]) == 2


def test_an_activity_needs_a_day_that_exists(client, pid):
    r = client.post(f"/api/profiles/{pid}/days/2026-08-12/activities",
                    json={"title": "x", "category": "study"})
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "day_not_found"


def test_an_unknown_activity_is_404(client, pid):
    assert client.put(f"/api/profiles/{pid}/activities/deadbeef",
                      json={"title": "x", "category": "study"}).status_code == 404
    assert client.delete(f"/api/profiles/{pid}/activities/deadbeef").status_code == 404


# ------------------------------------------------------------ validation

def test_unknown_metrics_and_out_of_range_values_are_422(client, pid):
    for bad in ({"vibes": 3}, {"mood": 9}, {"mood": 0}, {"sleep_hours": 30}):
        r = client.put(f"/api/profiles/{pid}/days/{WEEK8_THURSDAY}",
                       json={"observations": bad})
        assert r.status_code == 422, bad


def test_an_unknown_reflection_prompt_is_422(client, pid):
    r = client.put(f"/api/profiles/{pid}/days/{WEEK8_THURSDAY}",
                   json={"reflections": {"horoscope": "mercury retrograde"}})
    assert r.status_code == 422


def test_an_unknown_activity_category_is_422(client):
    p = new_profile(client, "cat")
    client.post(f"/api/profiles/{p}/days", json={"date": WEEK8_THURSDAY})
    r = client.post(f"/api/profiles/{p}/days/{WEEK8_THURSDAY}/activities",
                    json={"title": "Nap", "category": "napping"})
    assert r.status_code == 422


def test_an_empty_activity_title_is_422(client):
    p = new_profile(client, "blank")
    client.post(f"/api/profiles/{p}/days", json={"date": WEEK8_THURSDAY})
    r = client.post(f"/api/profiles/{p}/days/{WEEK8_THURSDAY}/activities",
                    json={"title": "", "category": "study"})
    assert r.status_code == 422


def test_an_end_before_its_start_is_refused_rather_than_wrapped(client):
    """Guessing "past midnight" would invent an eleven-hour study session."""
    p = new_profile(client, "times")
    client.post(f"/api/profiles/{p}/days", json={"date": WEEK8_THURSDAY})
    r = client.post(f"/api/profiles/{p}/days/{WEEK8_THURSDAY}/activities",
                    json={"title": "x", "category": "study",
                          "start_time": "22:00", "end_time": "02:00"})
    assert r.status_code == 422


def test_a_malformed_date_is_422_not_a_500(client, pid):
    assert client.get(f"/api/profiles/{pid}/days/13-08-2026").status_code == 422
    assert client.get(f"/api/profiles/{pid}/days/2026-02-30").status_code == 422
    assert client.post(f"/api/profiles/{pid}/days",
                       json={"date": "13/08/2026"}).status_code == 422


def test_a_day_that_has_not_happened_is_refused(client, pid):
    """Daily records describe what happened, not what is planned."""
    future = (date.today() + timedelta(days=3)).isoformat()
    r = client.post(f"/api/profiles/{pid}/days", json={"date": future})
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "future_date"
    assert client.put(f"/api/profiles/{pid}/days/{future}",
                      json={"observations": {}}).status_code == 422


def test_a_date_before_the_declared_week_1_is_422_not_a_500(client):
    """`CHECK (week_index >= 1)` must never be reached by a request.

    Before this was caught in the route, a declared study period later than the
    day being recorded raised an IntegrityError: a 500 on PUT, and on POST the
    same exception type was mistranslated into "that date already exists".
    """
    p = new_profile(client, "future-term", term_start="2027-01-04")
    r = client.post(f"/api/profiles/{p}/days", json={"date": WEEK8_THURSDAY})
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "before_term_start"
    r = client.put(f"/api/profiles/{p}/days/{WEEK8_THURSDAY}",
                   json={"observations": {"mood": 3}})
    assert r.status_code == 422
    assert r.json()["detail"]["error"] == "before_term_start"


def test_an_inferred_anchor_can_never_put_a_day_before_week_1(client):
    """It is the Monday of the earliest recorded day, so back-filling works."""
    p = client.post("/api/profiles", json={"display_name": "backfill"}).json()["profile_id"]
    assert client.post(f"/api/profiles/{p}/days",
                       json={"date": "2026-08-20"}).status_code == 201
    # An earlier day moves the inferred anchor rather than being refused.
    assert client.post(f"/api/profiles/{p}/days",
                       json={"date": WEEK8_MONDAY}).status_code == 201
    t = client.get(f"/api/profiles/{p}/timeline").json()
    assert t["term_start"] == WEEK8_MONDAY
    assert t["days_recorded"] == 2


def test_sql_injection_in_a_daily_path_parameter_is_inert(client, pid):
    r = client.get(f"/api/profiles/{pid}/days/x'; DROP TABLE day_records;--")
    assert r.status_code == 422
    assert client.get(f"/api/profiles/{pid}/weeks/8").status_code == 200


# ------------------------------------------------------------- isolation

def test_one_student_cannot_reach_another_students_records(client):
    a = new_profile(client, "A-iso")
    b = new_profile(client, "B-iso")
    client.post(f"/api/profiles/{a}/days", json={
        "date": WEEK8_THURSDAY, "observations": {"mood": 5},
        "activities": [{"title": "private", "category": "personal"}]})
    aid = client.get(f"/api/profiles/{a}/days/{WEEK8_THURSDAY}") \
                .json()["activities"][0]["activity_id"]

    assert client.get(f"/api/profiles/{b}/days/{WEEK8_THURSDAY}").status_code == 404
    assert client.get(f"/api/profiles/{b}/days").json() == []
    assert client.get(f"/api/profiles/{b}/weeks/8").json()["days"] == []
    assert client.put(f"/api/profiles/{b}/activities/{aid}",
                      json={"title": "hijacked", "category": "study"}).status_code == 404
    assert client.delete(f"/api/profiles/{b}/activities/{aid}").status_code == 404

    # And A's row is untouched by every one of those attempts.
    assert client.get(f"/api/profiles/{a}/days/{WEEK8_THURSDAY}") \
                 .json()["activities"][0]["title"] == "private"


def test_deleting_a_profile_takes_its_days_with_it(client):
    p = new_profile(client, "erase")
    client.post(f"/api/profiles/{p}/days", json={
        "date": WEEK8_THURSDAY, "observations": {"mood": 3}})
    assert client.delete(f"/api/profiles/{p}").status_code == 204
    assert client.get(f"/api/profiles/{p}/days/{WEEK8_THURSDAY}").status_code == 404
    assert client.get(f"/api/profiles/{p}/timeline").status_code == 404


# --------------------------------------------------------------- honesty

def test_a_metric_that_was_not_recorded_is_absent_from_the_payload(client):
    """Not zero, not null - absent. The UI can then omit the element."""
    p = new_profile(client, "absent")
    client.post(f"/api/profiles/{p}/days", json={
        "date": WEEK8_THURSDAY, "observations": {"mood": 4}})
    day = client.get(f"/api/profiles/{p}/days/{WEEK8_THURSDAY}").json()
    assert day["observations"] == {"mood": 4.0}
    assert "stress" not in day["observations"]
    assert "sleep_hours" not in day["observations"]
    assert day["reflections"] == {}

    week = client.get(f"/api/profiles/{p}/weeks/8").json()
    assert [m["metric"] for m in week["rollup"]["metrics"]] == ["mood"]


def test_every_daily_payload_says_it_is_not_model_input(client):
    p = new_profile(client, "note")
    client.post(f"/api/profiles/{p}/days", json={"date": WEEK8_THURSDAY})
    assert client.get(f"/api/profiles/{p}/days/{WEEK8_THURSDAY}") \
                 .json()["model_input"] is False
    assert client.get(f"/api/profiles/{p}/timeline").json()["model_input"] is False
    assert client.get(f"/api/profiles/{p}").json()["model_input"] is False


def test_a_partial_time_total_declares_that_it_is_partial(client):
    p = new_profile(client, "partial")
    client.post(f"/api/profiles/{p}/days", json={
        "date": WEEK8_THURSDAY,
        "activities": [
            {"title": "Lecture", "category": "class", "minutes": 90},
            {"title": "Reading", "category": "study"},
        ]})
    r = client.get(f"/api/profiles/{p}/weeks/8").json()["rollup"]
    assert r["minutes_logged"] == 90
    assert r["activities_without_duration"] == 1, (
        "a sum over half the activities must not be readable as a total")


def test_a_weekly_mean_carries_the_number_of_days_behind_it(client):
    p = new_profile(client, "meanN")
    client.post(f"/api/profiles/{p}/days", json={
        "date": WEEK8_THURSDAY, "observations": {"mood": 5}})
    client.post(f"/api/profiles/{p}/days", json={
        "date": "2026-08-14", "observations": {"mood": 1, "stress": 4}})
    metrics = {m["metric"]: m for m in
               client.get(f"/api/profiles/{p}/weeks/8").json()["rollup"]["metrics"]}
    assert metrics["mood"]["mean"] == 3.0 and metrics["mood"]["n"] == 2
    assert metrics["stress"]["n"] == 1, (
        "a one-day average and a seven-day average are different claims")


def test_an_opened_but_empty_day_is_distinguishable_from_an_absent_one(client):
    p = new_profile(client, "opened")
    client.post(f"/api/profiles/{p}/days", json={"date": WEEK8_THURSDAY})
    week = client.get(f"/api/profiles/{p}/weeks/8").json()
    thursday = week["slots"][3]
    monday = week["slots"][0]
    assert thursday["recorded"] is True and thursday["n_activities"] == 0
    assert monday["recorded"] is False
    assert week["rollup"]["days_recorded"] == 1
    assert week["rollup"]["days_with_content"] == 0


# -------------------------------------------------------------- timeline

def test_the_timeline_length_comes_from_the_data_not_a_constant(client):
    """No twenty anywhere. The span is week 1 to the later of last-week and now."""
    p = new_profile(client, "span")
    empty = client.get(f"/api/profiles/{p}/timeline").json()
    assert empty["days_recorded"] == 0
    assert empty["n_weeks"] == len(empty["weeks"])
    assert all(not w["has_data"] for w in empty["weeks"])
    assert empty["rollups"] == []

    client.post(f"/api/profiles/{p}/days", json={"date": WEEK8_THURSDAY})
    t = client.get(f"/api/profiles/{p}/timeline").json()
    assert t["days_recorded"] == 1
    assert t["first_date"] == t["last_date"] == WEEK8_THURSDAY
    weeks = {w["week"]: w for w in t["weeks"]}
    assert weeks[8]["has_data"] and weeks[8]["days_recorded"] == 1
    assert not weeks[1]["has_data"]
    assert [r["week"] for r in t["rollups"]] == [8], (
        "an empty week has no rollup; a row of zeros would read as measurement")


def test_a_history_far_longer_than_twenty_weeks_is_served_whole(client):
    """Thirty-five weeks, ending today, because future days are refused.

    The point is that nothing in the stack has an opinion about how long a
    history may be - not the schema, not the rollup, not the timeline span.
    """
    n_weeks = 35
    # Work backwards from today so every generated date is in the past.
    today = date.today()
    first = today - timedelta(days=(n_weeks - 1) * 7)
    p = new_profile(client, "long", term_start=first.isoformat())
    for i in range(n_weeks):
        r = client.post(f"/api/profiles/{p}/days",
                        json={"date": (first + timedelta(days=i * 7)).isoformat()})
        assert r.status_code == 201, r.text
    t = client.get(f"/api/profiles/{p}/timeline").json()
    assert t["days_recorded"] == n_weeks
    assert t["n_weeks"] >= n_weeks
    assert max(w["week"] for w in t["weeks"] if w["has_data"]) == n_weeks
    assert client.get(f"/api/profiles/{p}/weeks/{n_weeks}")                  .json()["rollup"]["days_recorded"] == 1


def test_an_inferred_anchor_is_reported_as_inferred(client):
    p = client.post("/api/profiles", json={"display_name": "noanchor"}).json()["profile_id"]
    empty = client.get(f"/api/profiles/{p}/timeline").json()
    assert empty["term_start"] is None
    assert empty["term_start_declared"] is False

    client.post(f"/api/profiles/{p}/days", json={"date": WEEK8_THURSDAY})
    t = client.get(f"/api/profiles/{p}/timeline").json()
    assert t["term_start"] == WEEK8_MONDAY
    assert t["term_start_declared"] is False, (
        "the UI must be able to say the numbering is provisional")
    assert client.get(f"/api/profiles/{p}/days/{WEEK8_THURSDAY}").json()["week"] == 1


def test_declaring_an_anchor_later_renumbers_the_whole_history(client):
    p = client.post("/api/profiles", json={"display_name": "late"}).json()["profile_id"]
    client.post(f"/api/profiles/{p}/days", json={"date": WEEK8_THURSDAY})
    assert client.get(f"/api/profiles/{p}/days/{WEEK8_THURSDAY}").json()["week"] == 1

    r = client.put(f"/api/profiles/{p}", json={
        "display_name": "late", "consent": False, "payload": {},
        "term_start": TERM_START})
    assert r.status_code == 200 and r.json()["term_start"] == TERM_START
    assert client.get(f"/api/profiles/{p}/days/{WEEK8_THURSDAY}").json()["week"] == 8
    assert client.get(f"/api/profiles/{p}/weeks/8").json()["slots"][3]["recorded"] is True
    assert client.get(f"/api/profiles/{p}/timeline").json()["term_start_declared"] is True


def test_days_can_be_listed_over_a_range(client):
    p = new_profile(client, "range")
    for d in (WEEK8_MONDAY, WEEK8_THURSDAY, "2026-08-20"):
        client.post(f"/api/profiles/{p}/days", json={"date": d})
    got = client.get(f"/api/profiles/{p}/days",
                     params={"start": WEEK8_MONDAY, "end": "2026-08-16"}).json()
    assert [d["date"] for d in got] == [WEEK8_MONDAY, WEEK8_THURSDAY]
    assert len(client.get(f"/api/profiles/{p}/days").json()) == 3
    assert client.get(f"/api/profiles/{p}/days",
                      params={"start": "2026-09-01", "end": "2026-08-01"}
                      ).status_code == 422


# ------------------------------------------------------ the whole journey

def test_the_success_criteria_end_to_end(client):
    """Student -> timeline -> week 8 -> Thursday -> write -> reload -> still there.

    This is the acceptance path stated for the feature, executed against the
    real routes. The final read uses a fresh client over the same database,
    which is what a browser refresh amounts to.
    """
    p = new_profile(client, "journey")

    # timeline -> week 8 -> Monday..Sunday
    t = client.get(f"/api/profiles/{p}/timeline").json()
    assert any(w["week"] == 8 for w in t["weeks"])
    week = client.get(f"/api/profiles/{p}/weeks/8").json()
    thursday = week["slots"][3]
    assert thursday["weekday"] == "Thursday" and thursday["recorded"] is False

    # open Thursday and write the day
    client.post(f"/api/profiles/{p}/days", json={"date": thursday["date"]})
    for act in ({"title": "DBMS Lecture", "category": "class", "start_time": "09:00",
                 "end_time": "10:30", "subject": "DBMS"},
                {"title": "ML assignment", "category": "assignment",
                 "start_time": "11:00", "minutes": 120, "status": "partial"},
                {"title": "Gym", "category": "extracurricular",
                 "start_time": "17:00", "minutes": 60}):
        assert client.post(
            f"/api/profiles/{p}/days/{thursday['date']}/activities",
            json=act).status_code == 201
    assert client.put(f"/api/profiles/{p}/days/{thursday['date']}", json={
        "observations": {"mood": 4, "focus": 3, "stress": 2, "energy": 4,
                         "sleep_hours": 7},
        "reflections": {"difficult": "I struggled with dynamic programming.",
                        "learned": "I finally understood memoization.",
                        "went_well": "Completed my assignment."},
    }).status_code == 200

    # "refresh the browser": a new client over the same file
    import student_twin.api.settings as st
    st.get_settings.cache_clear()
    from student_twin.api.app import create_app
    with TestClient(create_app()) as fresh:
        day = fresh.get(f"/api/profiles/{p}/days/{thursday['date']}").json()
        assert len(day["activities"]) == 3
        assert day["observations"]["sleep_hours"] == 7.0
        assert "memoization" in day["reflections"]["learned"]

        # week 8 reflects the day
        w = fresh.get(f"/api/profiles/{p}/weeks/8").json()
        assert w["slots"][3]["recorded"] is True
        assert w["slots"][3]["n_activities"] == 3
        assert w["rollup"]["n_activities"] == 3
        assert w["rollup"]["minutes_logged"] == 270
        assert w["rollup"]["days_with_content"] == 1
        assert {m["metric"] for m in w["rollup"]["metrics"]} == {
            "mood", "focus", "stress", "energy", "sleep_hours"}

        # and the timeline knows the week has data
        tl = fresh.get(f"/api/profiles/{p}/timeline").json()
        assert next(x for x in tl["weeks"] if x["week"] == 8)["n_activities"] == 3
    st.get_settings.cache_clear()


def test_existing_model_routes_are_unaffected_by_an_empty_daily_layer(client):
    """The daily half must not have broken the read-only half.

    No run is ingested in this fixture, so `/api/health` reports degraded and
    the run-scoped routes 503 - which is the pre-existing behaviour for an
    empty database, and is asserted here so a regression shows up as a
    failure rather than as a 500.
    """
    h = client.get("/api/health").json()
    assert h["database"] is True and h["runs"] == 0
    assert h["status"] == "degraded"
    assert client.get("/api/students").status_code == 503
    assert client.get("/api/evaluation").status_code == 503
