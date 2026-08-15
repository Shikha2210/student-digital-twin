#!/usr/bin/env python
"""Run the pipeline and persist the result.

    .venv/Scripts/python scripts/ingest_run.py --students 250 --weeks 20

This is the only path by which model numbers enter the database. It runs
the real pipeline, stores what came back, and prints the run_id so the
result can be cited.

The sweep of intervention magnitudes is simulated here, one forward run
per magnitude. The Intervention Lab reads those stops directly; drawing a
curve between two of them would be a picture of a model nobody ran.
"""

from __future__ import annotations

import argparse
import sys

from student_twin.config import Config
from student_twin.pipeline import run_pipeline
from student_twin.store import migrate
from student_twin.store.db import Database
from student_twin.store.ingest import ingest_run, record_capability_tests

#: label -> engagement-support magnitude in latent state units.
DEFAULT_SCENARIOS = {
    "Current dynamics": 0.0,
    "Support +0.25": 0.25,
    "Support +0.50": 0.5,
    "Support +0.75": 0.75,
    "Support +1.00": 1.0,
    "Support +1.25": 1.25,
    "Support +1.50": 1.5,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--adapter", default="synthetic", choices=["synthetic", "oulad"])
    ap.add_argument("--students", type=int, default=250)
    ap.add_argument("--weeks", type=int, default=20)
    ap.add_argument("--db", default=None, help="SQLite path (default: STUDYTWIN_DB)")
    ap.add_argument("--horizon", type=int, default=8)
    ap.add_argument("--particles", type=int, default=600)
    ap.add_argument("--store-students", type=int, default=60,
                    help="How many students to persist in full. Storing every "
                         "student's particle paths is a lot of rows for a demo.")
    ap.add_argument("--notes", default=None)
    args = ap.parse_args()

    from student_twin.api.settings import get_settings
    db_path = args.db or get_settings().database_path

    print(f"migrating {db_path}")
    migrate(db_path, verbose=True)

    cfg = Config()
    kwargs = (dict(n_students=args.students, n_weeks=args.weeks)
              if args.adapter == "synthetic" else {})
    print(f"running pipeline on {args.adapter} ...")
    result = run_pipeline(cfg, adapter_name=args.adapter, adapter_kwargs=kwargs)

    if result.warnings:
        print("pipeline warnings:")
        for w in result.warnings:
            print("  - " + w)

    db = Database(db_path)
    try:
        run_id = ingest_run(
            db, result, config=cfg, scenarios=DEFAULT_SCENARIOS,
            horizon=args.horizon, n_particles=args.particles,
            notes=args.notes, max_students=args.store_students,
        )

        # Capability tests, recorded only if they actually ran. T3 and T4 raise
        # NotImplementedError; an absent row is honest, a fabricated pass is not.
        tests = []
        try:
            from student_twin.evaluation.twin_tests import check_T2_generativity
            from student_twin.simulation.forward import posterior_predictive_check
            # T1 and T2 are executed by scripts/run_prototype.py against the same
            # config; re-deriving them here would duplicate that logic. Only
            # record what this script can compute without copying it.
            _ = (check_T2_generativity, posterior_predictive_check)
        except Exception as exc:                       # pragma: no cover
            print(f"capability tests skipped: {exc}", file=sys.stderr)
        if tests:
            record_capability_tests(db, run_id, tests)

        counts = {
            t: db.scalar(f"SELECT COUNT(*) FROM {t} WHERE run_id = ?", (run_id,))
            for t in ("students", "observations", "features", "twin_states",
                      "baselines", "hazards", "attribution_steps", "metrics")
        }
        n_fc = db.scalar(
            "SELECT COUNT(*) FROM forecasts WHERE scenario_id IN "
            "(SELECT scenario_id FROM scenarios WHERE run_id = ?)", (run_id,))
    finally:
        db.close()

    print(f"\nrun_id = {run_id}")
    for k, v in counts.items():
        print(f"  {k:20} {v}")
    print(f"  {'forecast rows':20} {n_fc}")
    print(f"\nserve it:  uvicorn student_twin.api.app:app --port 8000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
