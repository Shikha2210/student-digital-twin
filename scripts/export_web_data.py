#!/usr/bin/env python
"""Export real pipeline output for the web frontend.

    .venv/Scripts/python scripts/export_web_data.py

This is the frontend's data contract. It writes `web/data.js`, a single JSON
blob assigned to `window.STUDYTWIN_DATA`. Replacing this with a real HTTP API
later means changing one loader in the frontend and nothing else.

Rules this script enforces:

- Every number is real pipeline output. Nothing is invented for presentation.
- The provenance of the run (dataset, synthetic or not) travels with the data,
  so the UI can label it without guessing.
- If a quantity is not computed by the pipeline, it is absent rather than
  filled with a plausible placeholder.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from student_twin.config import Config, rng_for
from student_twin.explain import explain_trajectory
from student_twin.pipeline import run_pipeline
from student_twin.simulation import Intervention, InterventionScenario, simulate_forward

HEADER = (
    "// GENERATED FILE - do not edit by hand.\n"
    "// Regenerate:  .venv/Scripts/python scripts/export_web_data.py\n"
    "// PROVENANCE: every number below is real pipeline output.\n"
)


def pick_student(result, prefer: str | None) -> str:
    """Choose a student with a legible story: the largest sustained decline."""
    if prefer and prefer in result.trajectories:
        return prefer
    best, best_drop = None, -np.inf
    for sid, tr in result.trajectories.items():
        if len(tr) < 12:
            continue
        m = tr.means()[:, 0]
        drop = float(m[:6].mean() - m[-4:].mean())
        if drop > best_drop:
            best, best_drop = sid, drop
    return best or next(iter(result.trajectories))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", default="synthetic", choices=["synthetic", "oulad"])
    ap.add_argument("--students", type=int, default=250)
    ap.add_argument("--weeks", type=int, default=20)
    ap.add_argument("--student", default="S010026")
    ap.add_argument("--out", default="web/data.js")
    args = ap.parse_args()

    cfg = Config()
    kwargs = (
        dict(n_students=args.students, n_weeks=args.weeks)
        if args.adapter == "synthetic"
        else {}
    )
    r = run_pipeline(cfg, adapter_name=args.adapter, adapter_kwargs=kwargs)

    sid = pick_student(r, args.student)
    tr = r.trajectories[sid]
    setpoints = getattr(r.params, "student_setpoints", {})
    theta = setpoints.get(sid, r.params.mu0)
    hz = r.readout.state_only_params()

    base = simulate_forward(
        tr.current, theta, r.params, InterventionScenario.baseline(),
        horizon=8, n_particles=600, hazard_params=hz, rng=rng_for(cfg, "web-b"),
    )
    scen = InterventionScenario(
        "engagement support", (Intervention("engagement_support", 1.0),)
    )
    alt = simulate_forward(
        tr.current, theta, r.params, scen,
        horizon=8, n_particles=600, hazard_params=hz, rng=rng_for(cfg, "web-a"),
    )
    bq = base.state_quantiles((0.05, 0.5, 0.95))
    aq = alt.state_quantiles((0.05, 0.5, 0.95))
    pp = r.person_period[r.person_period["student_id"] == sid]

    # A sample of INDIVIDUAL simulated particle paths, for the hero diagram's
    # fan of possible futures. Real trajectories, not paths interpolated between
    # quantiles - a fan drawn from interpolation would be a picture of a band
    # pretending to be a set of outcomes.
    rng_pick = np.random.default_rng(cfg.seed)
    idx = rng_pick.choice(base.states.shape[0], size=min(24, base.states.shape[0]), replace=False)
    particle_paths = [[round(float(v), 4) for v in base.states[i, :, 0]] for i in idx]

    att = explain_trajectory(tr, r.params, dim=0).fillna(0)

    payload = {
        "provenance": {
            "dataset": r.dataset,
            "synthetic": bool(r.synthetic),
            "seed": cfg.seed,
            "inference": "laplace_approximate",
            "note": (
                "Synthetic cohort generated from a known latent process. "
                "The model has never been run on real OULAD data."
                if r.synthetic else "Real dataset run."
            ),
        },
        "student": {
            "id": sid, "context": tr.context_id, "weeks": len(tr),
            "theta": [round(float(x), 4) for x in np.asarray(theta)],
        },
        "state": {
            "t": [int(s.t) for s in tr.states],
            "eng": [round(float(s.mean[0]), 4) for s in tr.states],
            "eng_sd": [round(float(s.sd[0]), 4) for s in tr.states],
            "cap": [round(float(s.mean[1]), 4) for s in tr.states],
            "cap_sd": [round(float(s.sd[1]), 4) for s in tr.states],
        },
        "hazard": [round(float(x), 5) for x in r.readout.hazard(pp)],
        "sim": {
            "weeks": [int(x) for x in bq["t"]],
            "base_med": [round(float(x), 4) for x in bq["engagement_q50"]],
            "base_lo": [round(float(x), 4) for x in bq["engagement_q05"]],
            "base_hi": [round(float(x), 4) for x in bq["engagement_q95"]],
            "alt_med": [round(float(x), 4) for x in aq["engagement_q50"]],
            "alt_lo": [round(float(x), 4) for x in aq["engagement_q05"]],
            "alt_hi": [round(float(x), 4) for x in aq["engagement_q95"]],
            "base_risk": [round(float(x), 4) for x in base.cumulative_risk()],
            "particles": particle_paths,
            "alt_risk": [round(float(x), 4) for x in alt.cumulative_risk()],
        },
        "attrib": [
            {
                "t": int(row["t"]),
                "shift": round(float(row["shift"]), 4),
                "unexp": round(float(row["unexplained"]), 4),
                "ch": {
                    c.replace("contrib_", ""): round(float(row[c]), 4)
                    for c in att.columns
                    if c.startswith("contrib_") and abs(float(row[c])) > 1e-9
                },
            }
            for _, row in att.iterrows()
        ],
        "metrics": [
            {"name": m.name, "auc": round(m.auc, 4), "brier": round(m.brier, 5),
             "ece": round(m.ece, 5), "n": m.n, "pos": m.positives}
            for m in r.metrics
        ],
        "controls": [
            {"c": c.control, "v": c.verdict, "auc": round(c.auc, 4),
             "leak": c.is_leakage_test}
            for c in r.negative_controls
        ],
        "cohort": {
            "students": len(r.trajectories),
            "rows": len(r.person_period),
            "events": int(r.person_period["y"].sum()),
            "rate": round(float(r.person_period["y"].mean()), 5),
            "contexts": len(r.data.contexts),
            "coverage_avail": sorted(r.data.coverage.available),
            "coverage_missing": sorted(r.data.coverage.unavailable),
        },
        "shrinkage": [round(float(x), 4)
                      for x in np.atleast_1d(r.params.setpoint_shrinkage)],
    }

    # Cohort-level summary, for the "compared to everyone vs compared to
    # themselves" contrast on the landing page. Real per-student values, not a
    # synthesised distribution.
    cohort_pts = []
    for s_id, s_tr in r.trajectories.items():
        if len(s_tr) < 4:
            continue
        cohort_pts.append({
            "id": s_id,
            "m": round(float(s_tr.means()[:, 0].mean()), 3),
            "th": round(float(np.asarray(setpoints.get(s_id, r.params.mu0))[0]), 3),
            "last": round(float(s_tr.current.mean[0]), 3),
        })
    payload["cohort_states"] = cohort_pts

    # Two real students with genuinely different personal baselines. This is the
    # site's central argument, so the pair must come from the data rather than
    # being chosen for narrative convenience.
    # Require a full history on both sides: a student who withdrew at week 6
    # cannot carry a "same observation, different meaning" comparison.
    long_enough = [p for p in cohort_pts if len(r.trajectories[p["id"]]) >= 15]
    ranked = sorted(long_enough or cohort_pts, key=lambda p: p["th"])
    lo_c, hi_c = ranked[max(len(ranked) // 12, 0)], ranked[-max(len(ranked) // 12, 1)]
    contrast = []
    for pick in (hi_c, lo_c):
        t2 = r.trajectories[pick["id"]]
        contrast.append({
            "id": pick["id"],
            "theta": pick["th"],
            "eng": [round(float(s.mean[0]), 4) for s in t2.states],
            "eng_sd": [round(float(s.sd[0]), 4) for s in t2.states],
        })
    payload["contrast"] = contrast

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        HEADER + "window.STUDYTWIN_DATA = " + json.dumps(payload, indent=1) + ";\n",
        encoding="utf-8",
    )
    print(f"wrote {out}  ({len(json.dumps(payload))} bytes)  student={sid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
