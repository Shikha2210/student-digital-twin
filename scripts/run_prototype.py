#!/usr/bin/env python
"""Run the prototype end to end and print an honest report.

    py -3.13 scripts/run_prototype.py                    # synthetic fixture
    py -3.13 scripts/run_prototype.py --adapter oulad    # real data, if present

Exit code is 0 on a completed run even when tests fail — a failed capability test
is a result, not a crash. It is non-zero only if the pipeline could not run or a
leakage test came back concerning.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from student_twin.config import Config, rng_for
from student_twin.evaluation.metrics import compare, reliability_table
from student_twin.evaluation.negative_controls import leakage_verdict
from student_twin.evaluation.twin_tests import (
    summarise,
    check_T1_sufficiency,
    check_T2_generativity,
)
from student_twin.explain import biggest_movers
from student_twin.pipeline import run_pipeline
from student_twin.simulation import (
    Intervention,
    InterventionScenario,
    simulate_forward,
)
from student_twin.simulation.forward import posterior_predictive_check
from student_twin.state.filter import TwinFilter

BAR = "=" * 78


def _rule(title: str) -> None:
    print(f"\n{BAR}\n{title}\n{BAR}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default="synthetic", choices=["synthetic", "oulad"])
    ap.add_argument("--config", default="configs/prototype.toml")
    ap.add_argument("--students", type=int, default=150)
    ap.add_argument("--weeks", type=int, default=20)
    ap.add_argument("--max-students", type=int, default=None)
    ap.add_argument("--out", default=None, help="directory to write the run manifest")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
    cfg = Config.from_toml(args.config) if Path(args.config).exists() else Config()

    kwargs = (
        dict(n_students=args.students, n_weeks=args.weeks)
        if args.adapter == "synthetic"
        else {}
    )

    _rule("STAGE 1  pipeline")
    try:
        r = run_pipeline(
            cfg, adapter_name=args.adapter, adapter_kwargs=kwargs,
            max_students=args.max_students,
        )
    except FileNotFoundError as exc:
        print(f"\nCANNOT RUN: {exc}\n")
        return 2

    print(json.dumps(r.summary(), indent=2, default=str))
    print(f"\n{r.provenance_banner()}")

    _rule("STAGE 2  baseline ladder, forward-chained")
    print(r.results_table.to_string(index=False))
    print("\nL0 random split (LEAKY — shown only to expose the inflation):")
    print(compare(r.leaky_metrics).to_string(index=False))

    _rule("STAGE 3  calibration of the twin readout")
    twin_p = r.readout.hazard(r.person_period[r.person_period["t"] > 0])
    y = r.person_period[r.person_period["t"] > 0]["y"].to_numpy(int)
    print(reliability_table(y, twin_p, cfg.evaluation.calibration_bins).to_string(index=False))

    _rule("STAGE 4  negative controls")
    for c in r.negative_controls:
        flag = "  <-- CONCERNING" if c.concerning else ""
        print(f"[{c.verdict:9s}] {c.control:26s} auc={c.auc:.3f}{flag}")
        print(f"            {c.interpretation}")
    print(f"\nVERDICT: {leakage_verdict(r.negative_controls)}")

    _rule("STAGE 5  twin capability tests")
    sid = max(r.trajectories, key=lambda s: len(r.trajectories[s]))
    traj = r.trajectories[sid]
    setpoints = getattr(r.params, "student_setpoints", {})
    theta = setpoints.get(sid, r.params.mu0)

    obs_rows = []
    sub = r.person_period[r.person_period["student_id"] == sid]
    obs_frame = r.features  # only used for week alignment below
    from student_twin.features.tier1 import observation_frame

    ofr = observation_frame(r.data.events)
    ofr = ofr[ofr["student_id"] == sid].sort_values("t")
    obs_cols = [c for c in ofr.columns if c not in ("student_id", "context_id", "t")]
    for _, row in ofr.iterrows():
        d = {"t": int(row["t"])}
        for c in obs_cols:
            v = row[c]
            if c == "score":
                if pd.notna(v):
                    d[c] = float(v)
            else:
                d[c] = float(v) if pd.notna(v) else 0.0
        obs_rows.append(d)

    filt = TwinFilter(r.params, cfg.state)
    t1 = check_T1_sufficiency(filt, obs_rows, theta)

    # T2: simulate from mid-course, compare against what actually happened
    checks = []
    hz = r.readout.state_only_params()
    for s in list(r.trajectories)[:40]:
        tr = r.trajectories[s]
        if len(tr) < 10:
            continue
        mid = tr.states[len(tr) // 2]
        th = setpoints.get(s, r.params.mu0)
        sim = simulate_forward(
            mid, th, r.params, InterventionScenario.baseline(),
            horizon=min(6, len(tr) - len(tr) // 2 - 1),
            n_particles=300, hazard_params=hz, rng=rng_for(cfg, f"t2-{s}"),
        )
        act = observation_frame(r.data.events)
        act = act[act["student_id"] == s]
        checks.append(posterior_predictive_check(sim, act, "content_view"))
    t2 = check_T2_generativity(checks)

    print(summarise([t1, t2]).to_string(index=False))
    for t in (t1, t2):
        print(f"\n{t.test_id}: {t.detail}")
        if not t.passed:
            print(f"    CONSEQUENCE: {t.consequence_if_failed}")
    print("\nT3 (intervention stability) and T4 (identifiability): NOT IMPLEMENTED (Phase 1).")

    _rule(f"STAGE 6  state trajectory and explanation — student {sid}")
    print(traj.to_frame(r.params.dim_names).head(10).to_string(index=False))
    print()
    for e in biggest_movers(traj, r.params, dim=0, k=2):
        print(e.to_text())
        print()

    _rule("STAGE 7  scenario comparison")
    base = simulate_forward(
        traj.current, theta, r.params, InterventionScenario.baseline(),
        horizon=cfg.simulation.horizon_weeks, n_particles=cfg.simulation.n_particles,
        hazard_params=hz, rng=rng_for(cfg, "sim-base"),
    )
    scen = InterventionScenario(
        label="engagement support",
        interventions=(Intervention("engagement_support", intensity=1.0),),
    )
    alt = simulate_forward(
        traj.current, theta, r.params, scen,
        horizon=cfg.simulation.horizon_weeks, n_particles=cfg.simulation.n_particles,
        hazard_params=hz, rng=rng_for(cfg, "sim-alt"),
    )
    cmp = pd.DataFrame({
        "week": np.arange(1, cfg.simulation.horizon_weeks + 1) + traj.current.t,
        "risk_baseline": np.round(base.cumulative_risk(), 4),
        "risk_scenario": np.round(alt.cumulative_risk(), 4),
    })
    print(cmp.to_string(index=False))
    print(f"\n{alt.provenance()}")

    if args.out:
        outdir = Path(args.out)
        outdir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "summary": r.summary(),
            "config": cfg.to_dict(),
            "results": r.results_table.to_dict(orient="records"),
            "negative_controls": [c.as_dict() for c in r.negative_controls],
            "twin_tests": [t.as_dict() for t in (t1, t2)],
            "leakage_verdict": leakage_verdict(r.negative_controls),
        }
        (outdir / "run_manifest.json").write_text(
            json.dumps(manifest, indent=2, default=str), encoding="utf-8"
        )
        print(f"\nmanifest written to {outdir / 'run_manifest.json'}")

    concerning = any(c.concerning for c in r.negative_controls)
    return 1 if concerning else 0


if __name__ == "__main__":
    sys.exit(main())
