"""Persistence layer: migrations, constraints, ingest, read-back.

These tests exist to catch the class of bug that is invisible until a demo:
a schema constraint that is documented but not enforced, an ingest that
silently drops rows, or a cascade that does not cascade because SQLite's
foreign keys were off.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from student_twin.config import Config
from student_twin.pipeline import run_pipeline
from student_twin.store import migrate
from student_twin.store.db import Database
from student_twin.store.ingest import ingest_run
from student_twin.store.repository import Repository


@pytest.fixture(scope="module")
def result():
    return run_pipeline(Config(), adapter_name="synthetic",
                        adapter_kwargs=dict(n_students=40, n_weeks=12))


@pytest.fixture()
def db(tmp_path):
    path = tmp_path / "t.db"
    migrate(path)
    d = Database(path)
    yield d
    d.close()


@pytest.fixture()
def ingested(db, result):
    run_id = ingest_run(db, result, config=Config(),
                        scenarios={"Current dynamics": 0.0, "Support +1.00": 1.0},
                        horizon=4, n_particles=80, max_students=6)
    return run_id


# ----------------------------------------------------------- migrations

def test_migrations_are_idempotent(tmp_path):
    path = tmp_path / "m.db"
    first = migrate(path)
    second = migrate(path)
    assert first, "first run should apply at least one migration"
    assert second == [], "re-running must be a no-op, not a re-apply"


def test_editing_an_applied_migration_is_refused(tmp_path, monkeypatch):
    """A silently changed migration is how two environments diverge."""
    path = tmp_path / "m.db"
    migrate(path)
    conn = sqlite3.connect(path)
    conn.execute("UPDATE schema_migrations SET checksum = 'tampered'")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="contents changed"):
        migrate(path)


# ----------------------------------------------------------- constraints

def test_foreign_keys_are_enforced(db):
    """ON DELETE CASCADE is a no-op unless PRAGMA foreign_keys is ON."""
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO students (run_id, student_id, context_id, n_weeks) "
            "VALUES ('ghost', 's1', 'c1', 3)")


def test_n_dims_check_mirrors_state_config(db):
    """The 1-3 dimension limit is enforced in the database too, not only in Python."""
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """INSERT INTO model_runs (run_id, created_at, dataset, synthetic, seed,
                   model_version, inference_method, n_dims, dim_names, config_json)
               VALUES ('r','2026-01-01','synthetic',1,1,'0.1','laplace',7,'[]','{}')""")


def test_hazard_must_be_a_probability(db, ingested):
    sid = db.scalar("SELECT student_id FROM students WHERE run_id = ? LIMIT 1", (ingested,))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO hazards (run_id, student_id, t, hazard, cum_risk, y) "
            "VALUES (?,?,999,1.4,0.2,0)", (ingested, sid))


def test_verdict_is_constrained_to_the_three_outcomes(db, ingested):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO negative_controls (run_id, control, verdict, auc, is_leakage_test) "
            "VALUES (?, 'made_up', 'PROBABLY_FINE', 0.5, 0)", (ingested,))


# --------------------------------------------------------------- ingest

def test_ingest_populates_every_output_table(db, ingested, result):
    for table in ("students", "observations", "features", "twin_states",
                  "baselines", "hazards", "attribution_steps",
                  "attribution_components", "metrics", "negative_controls",
                  "run_coverage"):
        n = db.scalar(f"SELECT COUNT(*) FROM {table} WHERE run_id = ?", (ingested,))
        assert n and n > 0, f"{table} is empty after ingest"


def test_every_canonical_type_is_accounted_for(db, ingested, result):
    """CoverageManifest's guarantee has to survive the trip into storage."""
    stored = db.scalar("SELECT COUNT(*) FROM run_coverage WHERE run_id = ?", (ingested,))
    cov = result.data.coverage
    assert stored == len(cov.available) + len(cov.unavailable)


def test_states_match_the_pipeline_exactly(db, ingested, result):
    """The database is a cache of a run, not a second computation of it."""
    repo = Repository(db)
    sid = repo.list_students(ingested, limit=1)[0]["student_id"]
    traj = result.trajectories[sid]
    stored = {(r["t"], r["dim_name"]): r["mean"] for r in repo.states(ingested, sid)}
    for s in traj.states:
        for j, name in enumerate(result.params.dim_names):
            assert stored[(s.t, name)] == pytest.approx(float(s.mean[j]), abs=1e-9)


def test_attribution_residual_is_stored_not_absorbed(db, ingested):
    """The unexplained term must survive as its own number."""
    repo = Repository(db)
    sid = repo.list_students(ingested, limit=1)[0]["student_id"]
    steps = repo.attribution(ingested, sid, "engagement")
    assert steps
    assert any(abs(s["residual"]) > 1e-9 for s in steps), (
        "every residual is zero, which would mean the decomposition is exact - "
        "it is first-order, so it is not")
    for s in steps:
        explained = sum(c["contribution"] for c in s["components"])
        # shift = explained + residual, by construction
        assert s["shift"] == pytest.approx(explained + s["residual"], abs=1e-6)


def test_scenarios_are_separate_simulations(db, ingested):
    """Each magnitude is its own run, not an interpolation of two."""
    repo = Repository(db)
    sid = repo.list_students(ingested, limit=1)[0]["student_id"]
    scens = repo.scenarios(ingested)
    assert len(scens) == 2
    a = repo.forecast(scens[0]["scenario_id"], sid)
    b = repo.forecast(scens[1]["scenario_id"], sid)
    assert a["quantiles"] and b["quantiles"]
    assert a["paths"] and b["paths"], "individual particle paths must be retained"
    med_a = [r["q50"] for r in a["quantiles"] if r["dim_name"] == "engagement"]
    med_b = [r["q50"] for r in b["quantiles"] if r["dim_name"] == "engagement"]
    assert med_a != med_b, "an intervention that changes nothing is not an intervention"


def test_run_records_reproducibility_fields(db, ingested):
    run = Repository(db).run(ingested)
    assert run["seed"] and run["model_version"] and run["inference_method"]
    assert run["config"], "config must be stored or the run is not reproducible"
    assert run["params"]["alpha"], "fitted parameters must be recoverable"
    assert set(run["dim_names"]) == {"engagement", "capability"}


def test_deleting_a_run_removes_its_numbers(db, ingested):
    """Provenance is enforced by cascade: an orphan number is not a result."""
    db.execute("DELETE FROM model_runs WHERE run_id = ?", (ingested,))
    db.conn.commit()
    for table in ("students", "twin_states", "baselines", "metrics", "observations"):
        assert db.scalar(f"SELECT COUNT(*) FROM {table} WHERE run_id = ?", (ingested,)) == 0
    assert db.scalar("SELECT COUNT(*) FROM forecasts") == 0, (
        "forecasts cascade through scenarios")


def test_ingest_is_atomic(db, result, monkeypatch):
    """A half-written run looks like a result and is not one."""
    import student_twin.store.ingest as ing

    boom = ing.explain_trajectory

    def explode(*a, **k):
        raise RuntimeError("simulated failure midway through ingest")

    monkeypatch.setattr(ing, "explain_trajectory", explode)
    with pytest.raises(RuntimeError):
        ingest_run(db, result, config=Config(), scenarios={"x": 0.0},
                   horizon=2, n_particles=20, max_students=3)
    monkeypatch.setattr(ing, "explain_trajectory", boom)
    assert db.scalar("SELECT COUNT(*) FROM model_runs") == 0
    assert db.scalar("SELECT COUNT(*) FROM twin_states") == 0


def test_profiles_are_isolated_from_model_data(db):
    """Deleting a person must not need to touch a model table, and vice versa."""
    repo = Repository(db)
    repo.create_profile("p1", "2026-01-01T00:00:00Z", "Sid", True,
                        json.dumps({"courses": ["ML"]}))
    assert repo.profile("p1")["display_name"] == "Sid"
    assert repo.profile("p1")["observations"] == 0
    assert repo.delete_profile("p1") is True
    assert repo.profile("p1") is None
