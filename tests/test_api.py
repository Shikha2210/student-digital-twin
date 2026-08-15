"""HTTP API: routes, contract shape, errors, and the honesty guarantees.

The last group is the important one. It is easy to write an API that
returns correct numbers and lies about what they are; these tests assert
that every payload carrying a model quantity also carries the provenance
that qualifies it.
"""

from __future__ import annotations

import pytest

from student_twin.config import Config
from student_twin.pipeline import run_pipeline
from student_twin.store import migrate
from student_twin.store.db import Database
from student_twin.store.ingest import ingest_run

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("api") / "api.db"
    migrate(db_path)
    result = run_pipeline(Config(), adapter_name="synthetic",
                          adapter_kwargs=dict(n_students=40, n_weeks=12))
    db = Database(db_path)
    run_id = ingest_run(db, result, config=Config(),
                        scenarios={"Current dynamics": 0.0, "Support +1.00": 1.0},
                        horizon=4, n_particles=80, max_students=6)
    db.close()

    import student_twin.api.settings as st
    st.get_settings.cache_clear()
    import os
    os.environ["STUDYTWIN_DB"] = str(db_path)
    os.environ["STUDYTWIN_SERVE_WEB"] = "0"
    from student_twin.api.app import create_app

    with TestClient(create_app()) as c:
        c.run_id = run_id
        yield c
    st.get_settings.cache_clear()


@pytest.fixture()
def sid(client):
    return client.get("/api/students/demo").json()["student_id"]


# ------------------------------------------------------------------ meta

def test_health_reports_what_is_actually_there(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    b = r.json()
    assert b["database"] is True
    assert b["runs"] >= 1
    assert b["migrations_applied"] >= 1
    assert b["status"] == "ok"


def test_openapi_documents_every_route(client):
    spec = client.get("/api/openapi.json").json()
    for path in ("/api/health", "/api/runs", "/api/students",
                 "/api/students/{student_id}/twin", "/api/evaluation"):
        assert path in spec["paths"], f"{path} missing from the OpenAPI spec"


def test_run_detail_carries_reproducibility(client):
    run_id = client.get("/api/health").json()["latest_run_id"]
    b = client.get(f"/api/runs/{run_id}").json()
    assert b["seed"] and b["model_version"] and b["inference_method"]
    assert b["config"], "a run without its config cannot be reproduced"
    assert b["coverage"]["available"] and "unavailable" in b["coverage"]


# --------------------------------------------------------------- students

def test_student_list_is_paged(client):
    b = client.get("/api/students?limit=2").json()
    assert b["limit"] == 2 and len(b["items"]) == 2
    assert b["total"] >= 2


def test_twin_payload_has_the_documented_shape(client, sid):
    b = client.get(f"/api/students/{sid}/twin").json()
    for key in ("provenance", "student", "dim_names", "state", "baseline",
                "hazard", "observations", "attribution", "scenarios",
                "own_distribution", "cohort_theta"):
        assert key in b, f"contract key {key} missing"
    assert b["state"][0]["dim_name"] == b["dim_names"][0], (
        "the first series must be the model's first dimension, not SQLite's")
    assert b["baseline"][0]["dim_name"] == b["dim_names"][0]
    assert len(b["state"][0]["mean"]) == len(b["state"][0]["sd"]) > 0


def test_state_series_carry_their_inference_method(client, sid):
    for s in client.get(f"/api/students/{sid}/state").json():
        assert s["method"], "a state without a method label is unreportable"


def test_attribution_exposes_the_residual(client, sid):
    steps = client.get(f"/api/students/{sid}/twin").json()["attribution"]
    assert steps
    for s in steps:
        explained = sum(c["contribution"] for c in s["components"])
        assert s["shift"] == pytest.approx(explained + s["residual"], abs=1e-6), (
            "components plus residual must equal the shift; normalising the "
            "residual away would make them sum to the shift by construction")


def test_forecasts_are_labelled_model_generated(client, sid):
    scens = client.get(f"/api/students/{sid}/forecast").json()
    assert scens
    for s in scens:
        assert "NOT A CAUSAL ESTIMATE" in s["disclaimer"]
        assert s["quantiles"] and s["cum_risk"]
        assert s["paths"], "the fan must be real particle paths"


def test_scenarios_differ_from_one_another(client, sid):
    scens = client.get(f"/api/students/{sid}/forecast").json()
    meds = [tuple(q["q50"]) for s in scens for q in s["quantiles"]
            if q["dim_name"] == "engagement"]
    assert len(set(meds)) == len(meds), "two scenarios produced identical medians"


# ----------------------------------------------------------- evaluation

def test_evaluation_reports_unimplemented_tests_explicitly(client):
    b = client.get("/api/evaluation").json()
    joined = " ".join(b["not_implemented"])
    assert "T3" in joined and "T4" in joined
    assert "NOT IMPLEMENTED" in joined
    ran = {t["test_id"] for t in b["capability_tests"]}
    assert "T3" not in ran and "T4" not in ran, (
        "a test that never ran must be absent, never stored as passed")


def test_negative_controls_keep_their_verdicts(client):
    controls = client.get("/api/evaluation").json()["negative_controls"]
    assert controls
    assert {c["verdict"] for c in controls} <= {"COLLAPSED", "SURVIVED", "UNDEFINED"}


# ------------------------------------------------------------- honesty

def test_every_model_payload_carries_provenance(client, sid):
    for path in (f"/api/students/{sid}/twin", "/api/evaluation"):
        b = client.get(path).json()
        p = b["provenance"]
        assert p["run_id"] and p["seed"] and p["model_version"]
        assert isinstance(p["synthetic"], bool)
        if p["synthetic"]:
            assert "SYNTHETIC" in p["note"].upper()


def test_synthetic_flag_is_not_optional(client, sid):
    b = client.get(f"/api/students/{sid}/twin").json()
    assert b["provenance"]["synthetic"] is True, (
        "this fixture is synthetic; if the flag can be dropped the UI cannot "
        "label it")


def test_profile_says_it_is_not_model_input(client):
    r = client.post("/api/profiles", json={"display_name": "Sid", "consent": True,
                                           "payload": {"courses": ["ML"]}})
    assert r.status_code == 201
    b = r.json()
    assert b["model_input"] is False
    assert b["observations"] == 0
    assert client.get(f"/api/profiles/{b['profile_id']}").status_code == 200
    assert client.delete(f"/api/profiles/{b['profile_id']}").status_code == 204
    assert client.get(f"/api/profiles/{b['profile_id']}").status_code == 404


# --------------------------------------------------------------- errors

def test_unknown_student_is_404_not_an_empty_twin(client):
    r = client.get("/api/students/NOT_A_STUDENT/twin")
    assert r.status_code == 404
    assert "detail" in r.json()


def test_unknown_run_is_404(client):
    assert client.get("/api/runs/deadbeef").status_code == 404
    assert client.get("/api/students?run_id=deadbeef").status_code == 404


def test_pagination_bounds_are_validated(client):
    assert client.get("/api/students?limit=0").status_code == 422
    assert client.get("/api/students?limit=99999").status_code == 422
    assert client.get("/api/students?offset=-1").status_code == 422


def test_sql_injection_in_a_path_parameter_is_inert(client):
    """Every value is a bound parameter; this should 404, never execute."""
    r = client.get("/api/students/x'; DROP TABLE students;--/twin")
    assert r.status_code == 404
    assert client.get("/api/students?limit=1").json()["total"] >= 1
