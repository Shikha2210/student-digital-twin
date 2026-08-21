"""Queries.

Every SQL statement in the application lives here. Routes call methods on
this object and never see a query string, which means the parameter
binding, the joins and the ordering are all reviewable in one file.

Reads are the bulk of it. The writes are confined to the two things a
person owns rather than a pipeline run - their profile, and their daily
records - and both are keyed by `profile_id` so a route cannot reach one
account's rows while holding another's id. Model data has exactly one
writer and it is `store/ingest.py`, not this file.

No method computes a model quantity. `cohort_summary` averages stored
states and the daily methods count stored rows; both are arithmetic over
values that already exist, and the API labels them accordingly.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from ..daily import calendar as cal
from .db import Database, transaction


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
                       consent: bool, payload: str,
                       term_start: str | None = None) -> None:
        """`term_start` is normalised to a Monday before it is stored.

        Week numbering runs Monday to Sunday, so an anchor that is not a
        Monday would make week 1 shorter than seven days and every
        `week_bounds` call disagree with the stored `week_index`.
        """
        self.db.execute(
            """INSERT INTO profiles
               (profile_id, created_at, updated_at, display_name, consent,
                payload_json, observations, term_start)
               VALUES (?,?,?,?,?,?,0,?)""",
            (profile_id, now, now, display_name, int(bool(consent)), payload,
             cal.monday_of(term_start).isoformat() if term_start else None))
        self.db.conn.commit()

    def update_profile(self, profile_id: str, now: str, display_name: str | None,
                       consent: bool, payload: str,
                       term_start: str | None = None) -> bool:
        """Replace a profile. A changed anchor re-derives every stored week.

        `set_term_start` is called rather than an inline UPDATE precisely
        so that the re-derivation cannot be forgotten here: a profile edit
        that moved the anchor and left `day_records.week_index` alone
        would silently misfile the student's whole history.
        """
        cur = self.db.execute(
            """UPDATE profiles SET updated_at = ?, display_name = ?, consent = ?,
                                   payload_json = ?
               WHERE profile_id = ?""",
            (now, display_name, int(bool(consent)), payload, profile_id))
        self.db.conn.commit()
        if cur.rowcount == 0:
            return False
        current = self.term_start(profile_id)
        wanted = cal.monday_of(term_start).isoformat() if term_start else None
        if wanted != current:
            self.set_term_start(profile_id, wanted)
        return True

    def profile(self, profile_id: str) -> dict[str, Any] | None:
        r = self.db.one("SELECT * FROM profiles WHERE profile_id = ?", (profile_id,))
        if not r:
            return None
        r["consent"] = bool(r["consent"])
        r["payload"] = json.loads(r.pop("payload_json"))
        # Counted here rather than denormalised onto the row: a stored count
        # is one missed decrement away from claiming days that are not there.
        r["days_recorded"] = int(self.db.scalar(
            "SELECT COUNT(*) FROM day_records WHERE profile_id = ?",
            (profile_id,)) or 0)
        return r

    def delete_profile(self, profile_id: str) -> bool:
        cur = self.db.execute("DELETE FROM profiles WHERE profile_id = ?", (profile_id,))
        self.db.conn.commit()
        return cur.rowcount > 0

    # ================================================================
    # DAILY RECORDS
    # ----------------------------------------------------------------
    # Raw student-entered days. Three properties hold across every method
    # below, and each is a deliberate choice rather than a convention:
    #
    #  1. EVERY read and write takes `profile_id` and reaches a day only
    #     through it. There is no `day_by_id(day_id)`, because a method
    #     that resolves a day without its owner is one route parameter
    #     away from serving one student another student's history.
    #
    #  2. `week_index` is DERIVED here, never accepted from a caller.
    #     `daily.calendar` is the single place a date becomes a week; a
    #     client that could send its own number could file Thursday in
    #     week 3 and Friday in week 40 of the same week.
    #
    #  3. Absence is preserved. Observations and reflections are stored
    #     long, so "not recorded" is a missing row rather than a zero or
    #     an empty string, all the way out to the API payload.
    # ================================================================

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat(timespec="seconds")

    # ---------------------------------------------------------- anchor

    def term_start(self, profile_id: str) -> str | None:
        """The declared study-period anchor, or `None` if never set."""
        return self.db.scalar(
            "SELECT term_start FROM profiles WHERE profile_id = ?", (profile_id,))

    def effective_term_start(self, profile_id: str) -> str | None:
        """The anchor week numbering actually uses.

        The declared `term_start` when there is one; otherwise the Monday
        of the earliest recorded day. `None` when the profile has neither,
        which is the honest answer for an account that has recorded
        nothing - there is no week 1 yet for anything to be relative to.
        """
        declared = self.term_start(profile_id)
        if declared:
            return cal.monday_of(declared).isoformat()
        earliest = self.db.scalar(
            "SELECT MIN(date) FROM day_records WHERE profile_id = ?", (profile_id,))
        return cal.monday_of(earliest).isoformat() if earliest else None

    def set_term_start(self, profile_id: str, term_start: str | None) -> bool:
        """Declare the anchor and re-derive every stored `week_index`.

        Recomputed rather than left alone because `week_index` is a cached
        derivation of `date`. Moving the anchor without rewriting the
        cache would leave rows whose stored week disagrees with the week
        the same date resolves to - the exact drift that makes a
        denormalised column untrustworthy.

        The recomputation runs through `daily.calendar.week_index`, not
        through SQL date arithmetic, so there is only ever one
        implementation of week numbering in the project.
        """
        if self.db.one("SELECT 1 FROM profiles WHERE profile_id = ?",
                       (profile_id,)) is None:
            return False
        now = self._now()
        anchor = cal.monday_of(term_start).isoformat() if term_start else None
        with transaction(self.db.conn):
            self.db.execute(
                "UPDATE profiles SET term_start = ?, updated_at = ? WHERE profile_id = ?",
                (anchor, now, profile_id))
            rows = self.db.query(
                "SELECT day_id, date FROM day_records WHERE profile_id = ?",
                (profile_id,))
            basis = anchor or (cal.monday_of(min(r["date"] for r in rows)).isoformat()
                               if rows else None)
            if basis:
                self.db.executemany(
                    "UPDATE day_records SET week_index = ?, updated_at = ? "
                    "WHERE day_id = ?",
                    [(cal.week_index(r["date"], basis), now, r["day_id"]) for r in rows])
        return True

    # ------------------------------------------------------------ days

    def day_id_for(self, profile_id: str, date: str) -> str | None:
        """Resolve one day, scoped to its owner. The only id lookup there is."""
        return self.db.scalar(
            "SELECT day_id FROM day_records WHERE profile_id = ? AND date = ?",
            (profile_id, cal.iso_date(date)))

    def create_day(self, profile_id: str, date: str, *, source: str = "student",
                   term_start: str | None = None) -> str:
        """Insert one day. Raises `sqlite3.IntegrityError` on a duplicate date.

        The UNIQUE (profile_id, date) constraint is allowed to surface
        rather than being pre-empted by a SELECT: check-then-insert is a
        race, and the route turns the integrity error into a 409 naming
        the date that already exists.

        BACK-FILLING. When the anchor is INFERRED - no declared `term_start` -
        it is the Monday of the earliest recorded day, so recording an EARLIER
        day moves it. Without the re-anchor below, back-filling produced
        `week_index = 0`, which the CHECK rejected, which surfaced as an
        IntegrityError, which the create route could only read as "that date
        already exists". A student writing up last week after this week's would
        have been told their day was a duplicate.

        A DECLARED anchor never moves here. It is the student's statement about
        when their study period began, and a day before it is refused by the
        route with a reason rather than silently redefining week 1.
        """
        iso = cal.iso_date(date)
        declared = term_start or self.term_start(profile_id)
        if declared:
            basis = cal.monday_of(declared).isoformat()
        else:
            # The row does not exist yet, so `effective_term_start` cannot see
            # it. Fold this date in: when it is the new earliest, it becomes
            # the anchor and this day is week 1.
            current = self.effective_term_start(profile_id)
            basis = cal.monday_of(min(current, iso) if current else iso).isoformat()
        now = self._now()
        day_id = uuid.uuid4().hex
        self.db.execute(
            """INSERT INTO day_records
               (day_id, profile_id, date, week_index, day_of_week, source,
                created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (day_id, profile_id, iso, cal.week_index(iso, basis),
             cal.day_of_week(iso), source, now, now))
        self.db.conn.commit()
        # If this row IS the new earliest, every other row's week is now
        # measured from the wrong Monday. Re-derive against the complete set.
        if not declared:
            self._reanchor_inferred(profile_id)
        return day_id

    def _reanchor_inferred(self, profile_id: str) -> None:
        """Re-derive every `week_index` against the earliest recorded day.

        Only for profiles with no DECLARED anchor. Cheap and idempotent: it
        rewrites only the rows whose stored week disagrees with the week their
        date resolves to, so the common case - adding a day that is not the new
        earliest - writes nothing.
        """
        rows = self.db.query(
            "SELECT day_id, date, week_index FROM day_records WHERE profile_id = ?",
            (profile_id,))
        if not rows:
            return
        basis = cal.monday_of(min(r["date"] for r in rows)).isoformat()
        stale = [(cal.week_index(r["date"], basis), r["day_id"]) for r in rows
                 if cal.week_index(r["date"], basis) != r["week_index"]]
        if stale:
            self.db.executemany(
                "UPDATE day_records SET week_index = ? WHERE day_id = ?", stale)
            self.db.conn.commit()

    def touch_day(self, day_id: str) -> None:
        """Mark a day edited. Called by every write to its children.

        Without it, adding an activity would leave the day's `updated_at`
        reporting when the day row was created, and "last edited" would be
        wrong for every day that was filled in over time.
        """
        self.db.execute("UPDATE day_records SET updated_at = ? WHERE day_id = ?",
                        (self._now(), day_id))

    def delete_day(self, profile_id: str, date: str) -> bool:
        """Erase a day and, by cascade, its activities, metrics and prose."""
        cur = self.db.execute(
            "DELETE FROM day_records WHERE profile_id = ? AND date = ?",
            (profile_id, cal.iso_date(date)))
        self.db.conn.commit()
        return cur.rowcount > 0

    def _day_rows(self, profile_id: str, where: str,
                  params: tuple[Any, ...]) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT day_id, date, week_index, day_of_week, source, created_at, "
            f"updated_at FROM day_records WHERE profile_id = ? {where} ORDER BY date",
            (profile_id, *params))

    def days_between(self, profile_id: str, start: str, end: str) -> list[dict[str, Any]]:
        """Days in an inclusive date range, fully populated.

        Four queries regardless of how many days are asked for: one for
        the day rows and one each for activities, metrics and prose. Every
        one joins back through `day_records.profile_id`, so isolation
        holds inside the child queries rather than depending on the caller
        having filtered correctly.
        """
        lo, hi = cal.iso_date(start), cal.iso_date(end)
        days = self._day_rows(profile_id, "AND date BETWEEN ? AND ?", (lo, hi))
        return self._populate(profile_id, days, "AND d.date BETWEEN ? AND ?", (lo, hi))

    def days_for_week(self, profile_id: str, week: int) -> list[dict[str, Any]]:
        days = self._day_rows(profile_id, "AND week_index = ?", (week,))
        return self._populate(profile_id, days, "AND d.week_index = ?", (week,))

    def all_days(self, profile_id: str) -> list[dict[str, Any]]:
        days = self._day_rows(profile_id, "", ())
        return self._populate(profile_id, days, "", ())

    def day(self, profile_id: str, date: str) -> dict[str, Any] | None:
        iso = cal.iso_date(date)
        days = self._day_rows(profile_id, "AND date = ?", (iso,))
        if not days:
            return None
        return self._populate(profile_id, days, "AND d.date = ?", (iso,))[0]

    def _populate(self, profile_id: str, days: list[dict[str, Any]], join_where: str,
                  params: tuple[Any, ...]) -> list[dict[str, Any]]:
        """Attach activities, observations and reflections to day rows.

        Every child query joins `day_records` and filters on `profile_id`
        again. That looks redundant next to `days` having already been
        filtered, and it is not: a future caller that assembles the day
        list some other way still cannot pull another profile's children
        through.

        `join_where` is a literal built at the call site from code, never
        from a request; every value is bound.
        """
        by_id = {d["day_id"]: d for d in days}
        for d in days:
            d["activities"] = []
            d["observations"] = {}
            d["reflections"] = {}
        if not by_id:
            return days

        acts = self.db.query(
            """SELECT a.activity_id, a.day_id, a.seq, a.title, a.category, a.detail,
                      a.subject, a.start_time, a.end_time, a.minutes, a.importance,
                      a.status, a.source, a.created_at, a.updated_at
               FROM day_activities a
               JOIN day_records d ON d.day_id = a.day_id
               WHERE d.profile_id = ? """ + join_where
            + " ORDER BY d.date, a.seq, a.created_at",
            (profile_id, *params))
        for a in acts:
            target = by_id.get(a["day_id"])
            if target is not None:
                target["activities"].append(a)

        obs = self.db.query(
            """SELECT o.day_id, o.metric, o.value
               FROM day_observations o
               JOIN day_records d ON d.day_id = o.day_id
               WHERE d.profile_id = ? """ + join_where + " ORDER BY o.metric",
            (profile_id, *params))
        for o in obs:
            target = by_id.get(o["day_id"])
            if target is not None:
                target["observations"][o["metric"]] = o["value"]

        refl = self.db.query(
            """SELECT r.day_id, r.prompt, r.body
               FROM day_reflections r
               JOIN day_records d ON d.day_id = r.day_id
               WHERE d.profile_id = ? """ + join_where + " ORDER BY r.prompt",
            (profile_id, *params))
        for r in refl:
            target = by_id.get(r["day_id"])
            if target is not None:
                target["reflections"][r["prompt"]] = r["body"]
        return days

    def week_counts(self, profile_id: str) -> list[dict[str, Any]]:
        """Per-week row counts, for the timeline strip.

        One grouped query rather than loading every day: the strip needs
        "does this week hold anything, and how much", not the content.
        """
        return self.db.query(
            """SELECT d.week_index                     AS week,
                      COUNT(DISTINCT d.day_id)         AS days_recorded,
                      MIN(d.date)                      AS first_date,
                      MAX(d.date)                      AS last_date,
                      (SELECT COUNT(*) FROM day_activities a
                        JOIN day_records x ON x.day_id = a.day_id
                        WHERE x.profile_id = d.profile_id
                          AND x.week_index = d.week_index) AS n_activities
               FROM day_records d
               WHERE d.profile_id = ?
               GROUP BY d.week_index
               ORDER BY d.week_index""",
            (profile_id,))

    # ----------------------------------------------------- day content

    def replace_observations(self, day_id: str, values: dict[str, float]) -> None:
        """Replace the day's metrics wholesale.

        Delete-then-insert rather than upsert, because the payload is the
        complete set: a metric the client omitted has been CLEARED, and an
        upsert would leave a stale mood sitting under a form the student
        just emptied.
        """
        with transaction(self.db.conn):
            self.db.execute("DELETE FROM day_observations WHERE day_id = ?", (day_id,))
            self.db.executemany(
                "INSERT INTO day_observations (day_id, metric, value) VALUES (?,?,?)",
                [(day_id, m, float(v)) for m, v in sorted(values.items())])
            self.touch_day(day_id)

    def replace_reflections(self, day_id: str, bodies: dict[str, str]) -> None:
        """Replace the day's prose wholesale. Same reasoning as the metrics.

        Blank and whitespace-only answers are dropped rather than stored:
        an empty row would make "unanswered" and "answered with nothing"
        indistinguishable, and the CHECK constraint refuses them anyway.
        """
        with transaction(self.db.conn):
            self.db.execute("DELETE FROM day_reflections WHERE day_id = ?", (day_id,))
            self.db.executemany(
                "INSERT INTO day_reflections (day_id, prompt, body) VALUES (?,?,?)",
                [(day_id, p, b.strip()) for p, b in sorted(bodies.items())
                 if b and b.strip()])
            self.touch_day(day_id)

    # ------------------------------------------------------ activities

    def next_activity_seq(self, day_id: str) -> int:
        return int(self.db.scalar(
            "SELECT COALESCE(MAX(seq), -1) + 1 FROM day_activities WHERE day_id = ?",
            (day_id,)) or 0)

    def create_activity(self, day_id: str, fields: dict[str, Any]) -> str:
        now = self._now()
        activity_id = uuid.uuid4().hex
        seq = fields.get("seq")
        if seq is None:
            seq = self.next_activity_seq(day_id)
        with transaction(self.db.conn):
            self.db.execute(
                """INSERT INTO day_activities
                   (activity_id, day_id, seq, title, category, detail, subject,
                    start_time, end_time, minutes, importance, status, source,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (activity_id, day_id, seq, fields["title"], fields["category"],
                 fields.get("detail"), fields.get("subject"), fields.get("start_time"),
                 fields.get("end_time"), fields.get("minutes"),
                 fields.get("importance"), fields.get("status"),
                 fields.get("source", "student"), now, now))
            self.touch_day(day_id)
        return activity_id

    def activity_day(self, profile_id: str, activity_id: str) -> dict[str, Any] | None:
        """The day an activity belongs to, only if this profile owns it.

        Every activity route resolves through here first. An update keyed
        on `activity_id` alone would let one account edit another's row by
        guessing a uuid; joining the owner in makes that structurally
        impossible rather than a rule somebody has to remember.
        """
        return self.db.one(
            """SELECT d.day_id, d.date, d.week_index
               FROM day_activities a
               JOIN day_records d ON d.day_id = a.day_id
               WHERE a.activity_id = ? AND d.profile_id = ?""",
            (activity_id, profile_id))

    #: Columns an update may touch. A class-level constant, so the only
    #: interpolated SQL fragment below is built from code and never from a
    #: request body.
    _ACTIVITY_UPDATABLE = ("title", "category", "detail", "subject", "start_time",
                           "end_time", "minutes", "importance", "status", "seq")

    def update_activity(self, activity_id: str, fields: dict[str, Any]) -> bool:
        cols = [c for c in self._ACTIVITY_UPDATABLE if c in fields]
        if not cols:
            return False
        assigns = ", ".join(f"{c} = ?" for c in cols)
        day_id = self.db.scalar(
            "SELECT day_id FROM day_activities WHERE activity_id = ?", (activity_id,))
        with transaction(self.db.conn):
            cur = self.db.execute(
                f"UPDATE day_activities SET {assigns}, updated_at = ? "
                "WHERE activity_id = ?",
                (*[fields[c] for c in cols], self._now(), activity_id))
            if day_id:
                self.touch_day(day_id)
        return cur.rowcount > 0

    def delete_activity(self, activity_id: str) -> bool:
        day_id = self.db.scalar(
            "SELECT day_id FROM day_activities WHERE activity_id = ?", (activity_id,))
        with transaction(self.db.conn):
            cur = self.db.execute(
                "DELETE FROM day_activities WHERE activity_id = ?", (activity_id,))
            if day_id:
                self.touch_day(day_id)
        return cur.rowcount > 0
