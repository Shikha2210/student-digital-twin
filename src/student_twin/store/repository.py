"""Read queries.

Every SQL statement in the application lives here. Routes call methods on
this object and never see a query string, which means the parameter
binding, the joins and the ordering are all reviewable in one file.

No method computes a model quantity. `own_distribution` computes a mean
and a standard deviation over stored states, which is arithmetic on
already-inferred values and is labelled as such in the API response.
"""

from __future__ import annotations

import json
from typing import Any

from .db import Database


class Repository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # ---------------------------------------------------------------- runs

    def latest_run_id(self, dataset: str | None = None) -> str | None:
        if dataset:
            return self.db.scalar(
                "SELECT run_id FROM model_runs WHERE dataset = ? "
                "ORDER BY created_at DESC LIMIT 1", (dataset,))
        return self.db.scalar(
            "SELECT run_id FROM model_runs ORDER BY created_at DESC LIMIT 1")

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.db.query(
            """SELECT run_id, created_at, dataset, synthetic, seed, model_version,
                      code_revision, inference_method, n_students, n_person_periods,
                      n_events, notes
               FROM model_runs ORDER BY created_at DESC LIMIT ?""", (limit,))
        for r in rows:
            r["synthetic"] = bool(r["synthetic"])
        return rows

    def run(self, run_id: str) -> dict[str, Any] | None:
        r = self.db.one("SELECT * FROM model_runs WHERE run_id = ?", (run_id,))
        if not r:
            return None
        r["synthetic"] = bool(r["synthetic"])
        r["dim_names"] = json.loads(r["dim_names"])
        r["config"] = json.loads(r["config_json"])
        r["params"] = json.loads(r["params_json"]) if r["params_json"] else None
        r.pop("config_json", None)
        r.pop("params_json", None)
        return r

    def coverage(self, run_id: str) -> dict[str, list[str]]:
        rows = self.db.query(
            "SELECT canonical_type, available FROM run_coverage WHERE run_id = ? "
            "ORDER BY canonical_type", (run_id,))
        return {
            "available": [r["canonical_type"] for r in rows if r["available"]],
            "unavailable": [r["canonical_type"] for r in rows if not r["available"]],
        }

    def metrics(self, run_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT model_name, auc, brier, ece, n, positives FROM metrics "
            "WHERE run_id = ? ORDER BY auc", (run_id,))

    def negative_controls(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT control, verdict, auc, is_leakage_test FROM negative_controls "
            "WHERE run_id = ? ORDER BY control", (run_id,))
        for r in rows:
            r["is_leakage_test"] = bool(r["is_leakage_test"])
        return rows

    def capability_tests(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT test_id, name, passed, statistic, threshold, detail "
            "FROM capability_tests WHERE run_id = ? ORDER BY test_id", (run_id,))
        for r in rows:
            r["passed"] = bool(r["passed"])
        return rows

    def primary_dim(self, run_id: str) -> str:
        """The model's FIRST dimension, from the run manifest.

        Not "whichever dim_name SQLite returns first": that is alphabetical in
        practice, so it silently made `capability` primary and every downstream
        chart plotted the wrong series.
        """
        names = self.db.scalar("SELECT dim_names FROM model_runs WHERE run_id = ?", (run_id,))
        return json.loads(names)[0] if names else ""

    def cohort_summary(self, run_id: str, limit: int = 400) -> list[dict[str, Any]]:
        """Per-student mean state, set point and current state.

        The landing page's central argument needs both axes for every student:
        how they compare to everyone (mean level) and how they compare to
        themselves (current minus set point).
        """
        dim = self.primary_dim(run_id)
        return self.db.query(
            """SELECT s.student_id            AS student_id,
                      AVG(ts.mean)            AS mean_state,
                      b.theta                 AS theta,
                      (SELECT mean FROM twin_states x
                        WHERE x.run_id = s.run_id AND x.student_id = s.student_id
                          AND x.dim_name = b.dim_name
                        ORDER BY x.t DESC LIMIT 1) AS last_state
               FROM students s
               JOIN baselines b   ON b.run_id = s.run_id AND b.student_id = s.student_id
               JOIN twin_states ts ON ts.run_id = s.run_id AND ts.student_id = s.student_id
                                  AND ts.dim_name = b.dim_name
               WHERE s.run_id = ? AND b.dim_name = ?
               GROUP BY s.student_id
               ORDER BY s.student_id
               LIMIT ?""",
            (run_id, dim, limit),
        )

    # ------------------------------------------------------------ students

    def list_students(self, run_id: str, limit: int = 50, offset: int = 0
                      ) -> list[dict[str, Any]]:
        rows = self.db.query(
            """SELECT student_id, context_id, n_weeks, event_observed, event_week
               FROM students WHERE run_id = ?
               ORDER BY student_id LIMIT ? OFFSET ?""",
            (run_id, limit, offset))
        for r in rows:
            r["event_observed"] = bool(r["event_observed"])
        return rows

    def count_students(self, run_id: str) -> int:
        return int(self.db.scalar(
            "SELECT COUNT(*) FROM students WHERE run_id = ?", (run_id,)) or 0)

    def student(self, run_id: str, student_id: str) -> dict[str, Any] | None:
        r = self.db.one(
            """SELECT student_id, context_id, n_weeks, event_observed, event_week
               FROM students WHERE run_id = ? AND student_id = ?""",
            (run_id, student_id))
        if r:
            r["event_observed"] = bool(r["event_observed"])
        return r

    def pick_demo_student(self, run_id: str) -> str | None:
        """The student with the largest sustained decline in the first dimension.

        Chosen by the same rule the static exporter used, so the demo is a
        legible story rather than an arbitrary row - and it is recomputed from
        stored states rather than hard-coded to an id.
        """
        dim = self.primary_dim(run_id)
        rows = self.db.query(
            """SELECT student_id,
                      AVG(CASE WHEN t < 6 THEN mean END) AS early,
                      AVG(CASE WHEN t >= (SELECT MAX(t) - 3 FROM twin_states x
                                          WHERE x.run_id = ts.run_id
                                            AND x.student_id = ts.student_id)
                               THEN mean END)            AS late,
                      COUNT(*)                           AS n
               FROM twin_states ts
               WHERE run_id = ? AND dim_name = ?
               GROUP BY student_id HAVING n >= 12""",
            (run_id, dim))
        best, drop = None, float("-inf")
        for r in rows:
            if r["early"] is None or r["late"] is None:
                continue
            d = r["early"] - r["late"]
            if d > drop:
                best, drop = r["student_id"], d
        return best or self.db.scalar(
            "SELECT student_id FROM students WHERE run_id = ? ORDER BY student_id LIMIT 1",
            (run_id,))

    # ------------------------------------------------------------- outputs

    def states(self, run_id: str, student_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            """SELECT t, dim_name, mean, sd, method, n_observations
               FROM twin_states WHERE run_id = ? AND student_id = ?
               ORDER BY t, dim_name""", (run_id, student_id))

    def baseline(self, run_id: str, student_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            """SELECT dim_name, theta, shrinkage_k, context_mean, n_obs
               FROM baselines WHERE run_id = ? AND student_id = ?
               ORDER BY dim_name""", (run_id, student_id))

    def hazards(self, run_id: str, student_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT t, hazard, cum_risk, y FROM hazards "
            "WHERE run_id = ? AND student_id = ? ORDER BY t", (run_id, student_id))

    def observations(self, run_id: str, student_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT t, channel, value FROM observations "
            "WHERE run_id = ? AND student_id = ? ORDER BY t, channel",
            (run_id, student_id))

    def features(self, run_id: str, student_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT t, feature, value FROM features "
            "WHERE run_id = ? AND student_id = ? ORDER BY t, feature",
            (run_id, student_id))

    def attribution(self, run_id: str, student_id: str, dim_name: str,
                    t: int | None = None) -> list[dict[str, Any]]:
        if t is None:
            steps = self.db.query(
                """SELECT t, prior_mean, posterior_mean, shift, residual,
                          prior_sd, posterior_sd
                   FROM attribution_steps
                   WHERE run_id = ? AND student_id = ? AND dim_name = ?
                   ORDER BY t""", (run_id, student_id, dim_name))
        else:
            steps = self.db.query(
                """SELECT t, prior_mean, posterior_mean, shift, residual,
                          prior_sd, posterior_sd
                   FROM attribution_steps
                   WHERE run_id = ? AND student_id = ? AND dim_name = ? AND t = ?""",
                (run_id, student_id, dim_name, t))
        comps = self.db.query(
            """SELECT t, channel, contribution, observed_value
               FROM attribution_components
               WHERE run_id = ? AND student_id = ? AND dim_name = ?
               ORDER BY t, channel""", (run_id, student_id, dim_name))
        by_t: dict[int, list[dict[str, Any]]] = {}
        for c in comps:
            by_t.setdefault(c["t"], []).append(
                {"channel": c["channel"], "contribution": c["contribution"],
                 "observed_value": c["observed_value"]})
        for s in steps:
            s["components"] = sorted(
                by_t.get(s["t"], []), key=lambda c: abs(c["contribution"]), reverse=True)
        return steps

    # ----------------------------------------------------------- scenarios

    def scenarios(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            """SELECT scenario_id, label, interventions_json, is_counterfactual,
                      horizon, n_particles, seed_purpose
               FROM scenarios WHERE run_id = ? ORDER BY rowid""", (run_id,))
        for r in rows:
            r["interventions"] = json.loads(r.pop("interventions_json"))
            r["is_counterfactual"] = bool(r["is_counterfactual"])
        return rows

    def forecast(self, scenario_id: str, student_id: str) -> dict[str, Any]:
        q = self.db.query(
            """SELECT h, t, dim_name, q05, q50, q95, mean FROM forecasts
               WHERE scenario_id = ? AND student_id = ? ORDER BY h, dim_name""",
            (scenario_id, student_id))
        risk = self.db.query(
            "SELECT h, cum_risk FROM forecast_risk "
            "WHERE scenario_id = ? AND student_id = ? ORDER BY h",
            (scenario_id, student_id))
        paths = self.db.query(
            """SELECT particle_ix, h, dim_name, value FROM forecast_paths
               WHERE scenario_id = ? AND student_id = ? ORDER BY particle_ix, h""",
            (scenario_id, student_id))
        return {"quantiles": q, "risk": risk, "paths": paths}

    # ------------------------------------------------------------ profiles

    def create_profile(self, profile_id: str, now: str, display_name: str | None,
                       consent: bool, payload: str) -> None:
        self.db.execute(
            """INSERT INTO profiles
               (profile_id, created_at, updated_at, display_name, consent,
                payload_json, observations)
               VALUES (?,?,?,?,?,?,0)""",
            (profile_id, now, now, display_name, int(bool(consent)), payload))
        self.db.conn.commit()

    def update_profile(self, profile_id: str, now: str, display_name: str | None,
                       consent: bool, payload: str) -> bool:
        cur = self.db.execute(
            """UPDATE profiles SET updated_at = ?, display_name = ?, consent = ?,
                                   payload_json = ?
               WHERE profile_id = ?""",
            (now, display_name, int(bool(consent)), payload, profile_id))
        self.db.conn.commit()
        return cur.rowcount > 0

    def profile(self, profile_id: str) -> dict[str, Any] | None:
        r = self.db.one("SELECT * FROM profiles WHERE profile_id = ?", (profile_id,))
        if not r:
            return None
        r["consent"] = bool(r["consent"])
        r["payload"] = json.loads(r.pop("payload_json"))
        return r

    def delete_profile(self, profile_id: str) -> bool:
        cur = self.db.execute("DELETE FROM profiles WHERE profile_id = ?", (profile_id,))
        self.db.conn.commit()
        return cur.rowcount > 0
