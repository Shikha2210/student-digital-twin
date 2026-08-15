"""Write a PipelineResult into the database.

This module is the ONLY writer of model-derived tables. It computes
nothing: every value it stores is read off a `PipelineResult` or a
`SimulationResult` that the research pipeline already produced. If a
quantity is not in one of those objects it does not get a column, and it
certainly does not get invented here.

The consequence worth stating plainly: the database is a cache of a run,
not a second implementation of the model. There is exactly one model.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from .. import __version__ as MODEL_VERSION
from ..config import Config, rng_for
from ..explain import explain_trajectory
from ..features.tier1 import observation_frame
from ..pipeline import PipelineResult
from ..schema import CanonicalType
from ..simulation import Intervention, InterventionScenario, simulate_forward
from .db import Database, transaction

#: How many individual particle paths to retain per scenario. Enough for an
#: honest fan, small enough that the table does not dominate the file.
N_RETAINED_PATHS = 40


def _git_revision() -> str | None:
    """Best-effort code revision. None is an honest answer; a fake sha is not."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
            cwd=str(Path(__file__).resolve().parents[3]),
        )
        return out.stdout.strip() or None if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _jsonable(obj: Any) -> Any:
    """Coerce numpy scalars, arrays and Paths into JSON-safe values.

    Config carries Path objects for the data directories, and numpy types leak
    out of every fitted parameter. Both are stored as strings/lists rather than
    dropped, because the config JSON is what makes a run reproducible.
    """
    if isinstance(obj, np.ndarray):
        return [_jsonable(x) for x in obj.tolist()]
    if isinstance(obj, (np.floating, np.integer)):
        return obj.item()
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(x) for x in obj]
    return obj


def _params_summary(params) -> dict[str, Any]:
    """The fitted parameters, flattened enough to store and read back.

    Stored so that a result can be interpreted years later without rerunning
    anything: alpha and Q define the dynamics, the loadings define what an
    observation is worth, and the shrinkage constant defines how personal the
    set points were allowed to be.
    """
    return _jsonable({
        "n_dims": params.n_dims,
        "dim_names": list(params.dim_names),
        "alpha": params.alpha,
        "Q_diag": np.diag(params.Q),
        "mu0": params.mu0,
        "P0_diag": np.diag(np.asarray(params.P0)),
        "setpoint_shrinkage": params.setpoint_shrinkage,
        "between_var": params.between_var,
        "within_var": params.within_var,
        "context_covariates": list(params.context_covariates),
        "count_params": {
            k: {"intercept": v[0], "loading": v[1], "phi": v[2]}
            for k, v in params.count_params.items()
        },
        "submit_params": (
            None if params.submit_params is None
            else {"intercept": params.submit_params[0], "weights": params.submit_params[1]}
        ),
        "score_params": (
            None if params.score_params is None
            else {"intercept": params.score_params[0], "weights": params.score_params[1],
                  "sigma": params.score_params[2]}
        ),
        "fitted_on": params.fitted_on,
        "synthetic": bool(params.synthetic),
    })


def ingest_run(
    db: Database,
    result: PipelineResult,
    *,
    config: Config | None = None,
    scenarios: dict[str, float] | None = None,
    horizon: int = 8,
    n_particles: int = 600,
    notes: str | None = None,
    max_students: int | None = None,
) -> str:
    """Persist one pipeline run. Returns the new run_id.

    `scenarios` maps a label to an engagement-support magnitude in latent state
    units. Each becomes its own forward simulation for every stored student -
    magnitudes are NOT interpolated later, because a curve drawn between two
    simulations is a picture of a model that was never run.
    """
    cfg = config or result.config
    run_id = uuid.uuid4().hex
    params = result.params
    dim_names = tuple(params.dim_names)
    setpoints = getattr(params, "student_setpoints", {}) or {}

    students = list(result.trajectories.items())
    if max_students is not None:
        students = students[:max_students]
    keep = {sid for sid, _ in students}

    pp = result.person_period
    outcomes = result.data.outcomes.df.set_index("student_id")

    with transaction(db.conn):
        # ---- provenance ------------------------------------------------
        db.execute(
            """INSERT INTO model_runs
               (run_id, created_at, dataset, synthetic, seed, model_version,
                code_revision, inference_method, n_dims, dim_names, config_json,
                params_json, n_students, n_person_periods, n_events, notes)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                run_id,
                datetime.now(UTC).isoformat(timespec="seconds"),
                result.dataset,
                int(bool(result.synthetic)),
                int(cfg.seed),
                MODEL_VERSION,
                _git_revision(),
                "laplace_approximate",
                int(params.n_dims),
                json.dumps(list(dim_names)),
                json.dumps(_jsonable(asdict(cfg))),
                json.dumps(_params_summary(params)),
                len(keep),
                int(len(pp)),
                int(pp["y"].sum()) if len(pp) else 0,
                notes,
            ),
        )

        cov = result.data.coverage
        db.executemany(
            "INSERT INTO run_coverage (run_id, canonical_type, available) VALUES (?,?,?)",
            [(run_id, str(c), 1) for c in sorted(cov.available)]
            + [(run_id, str(c), 0) for c in sorted(cov.unavailable)],
        )

        # ---- contexts and students -------------------------------------
        ctx_counts: dict[str, list[int]] = {}
        for sid, traj in students:
            b = ctx_counts.setdefault(traj.context_id, [0, 0])
            b[0] += 1
            b[1] = max(b[1], len(traj))
        db.executemany(
            "INSERT INTO contexts (run_id, context_id, n_students, n_weeks) VALUES (?,?,?,?)",
            [(run_id, cid, v[0], v[1]) for cid, v in ctx_counts.items()],
        )

        srows = []
        for sid, traj in students:
            observed, ev_week = 0, None
            if sid in outcomes.index:
                rec = outcomes.loc[sid]
                if hasattr(rec, "iloc") and getattr(rec, "ndim", 1) > 1:
                    rec = rec.iloc[0]
                observed = int(bool(rec["event_observed"]))
                w = rec["event_week"]
                ev_week = int(w) if w == w and w is not None else None  # NaN-safe
            srows.append((run_id, sid, traj.context_id, sid, len(traj), observed, ev_week))
        db.executemany(
            """INSERT INTO students
               (run_id, student_id, context_id, external_id, n_weeks, event_observed, event_week)
               VALUES (?,?,?,?,?,?,?)""",
            srows,
        )

        # ---- observations ----------------------------------------------
        # Re-derived from the stored events by the same function the filter
        # consumed, rather than carried on PipelineResult. It is a deterministic
        # reshape of the input, not a recomputation of any model quantity.
        obs_df = observation_frame(result.data.events)
        channels = [c.value for c in CanonicalType if c.value in obs_df.columns]
        if len(obs_df) and channels:
            sub = obs_df[obs_df["student_id"].isin(keep)]
            orows = []
            for _, r in sub.iterrows():
                for ch in channels:
                    v = r[ch]
                    if v is None or v != v:      # NaN means "not observed"
                        continue
                    orows.append((run_id, str(r["student_id"]), int(r["t"]), ch, float(v)))
            db.executemany(
                "INSERT OR IGNORE INTO observations "
                "(run_id, student_id, t, channel, value) VALUES (?,?,?,?,?)",
                orows,
            )

        # ---- tier-1 features -------------------------------------------
        feat = result.features
        fcols = [c for c in feat.columns if c not in ("student_id", "context_id", "t")]
        frows = []
        for _, r in feat[feat["student_id"].isin(keep)].iterrows():
            for c in fcols:
                v = r[c]
                if v is None or v != v:
                    continue
                frows.append((run_id, str(r["student_id"]), int(r["t"]), c, float(v)))
        db.executemany(
            "INSERT OR IGNORE INTO features (run_id, student_id, t, feature, value) "
            "VALUES (?,?,?,?,?)",
            frows,
        )

        # ---- states, baselines, attribution ----------------------------
        shrink = np.atleast_1d(np.asarray(params.setpoint_shrinkage, dtype=float))
        st_rows, base_rows, step_rows, comp_rows = [], [], [], []
        for sid, traj in students:
            theta = np.asarray(setpoints.get(sid, params.mu0), dtype=float)
            ctx_mean = np.asarray(
                params.context_means.get(traj.context_id, params.mu0), dtype=float)
            for s in traj.states:
                for j, name in enumerate(dim_names):
                    st_rows.append((run_id, sid, int(s.t), name, float(s.mean[j]),
                                    float(s.sd[j]), str(s.method), int(s.n_observations)))
            for j, name in enumerate(dim_names):
                base_rows.append((
                    run_id, sid, name, float(theta[j]),
                    float(shrink[j] if j < len(shrink) else shrink[0]),
                    float(ctx_mean[j]), len(traj),
                ))

            # The filter retained the one-step-ahead prior covariance; index it
            # by week so the PREDICT step's uncertainty travels with its mean.
            prior_sd_at = {}
            post_sd_at = {}
            for i, s in enumerate(traj.states):
                if i < len(traj.predicted_covs):
                    pc = np.asarray(traj.predicted_covs[i], dtype=float)
                    prior_sd_at[int(s.t)] = np.sqrt(np.clip(np.diag(pc), 0.0, None))
                post_sd_at[int(s.t)] = s.sd

            for dim, name in enumerate(dim_names):
                att = explain_trajectory(traj, params, dim=dim).fillna(0.0)
                for _, row in att.iterrows():
                    t = int(row["t"])
                    psd = prior_sd_at.get(t)
                    osd = post_sd_at.get(t)
                    step_rows.append((run_id, sid, t, name, float(row["prior"]),
                                      float(row["posterior"]), float(row["shift"]),
                                      float(row["unexplained"]),
                                      None if psd is None else float(psd[dim]),
                                      None if osd is None else float(osd[dim])))
                obs_by_t = {a.t: a.observations for a in traj.attributions}
                for _, row in att.iterrows():
                    t = int(row["t"])
                    for c in att.columns:
                        if not c.startswith("contrib_"):
                            continue
                        ch = c[len("contrib_"):]
                        val = float(row[c])
                        if abs(val) < 1e-12:
                            continue
                        comp_rows.append((run_id, sid, t, name, ch, val,
                                          obs_by_t.get(t, {}).get(ch)))
        db.executemany(
            """INSERT INTO twin_states
               (run_id, student_id, t, dim_name, mean, sd, method, n_observations)
               VALUES (?,?,?,?,?,?,?,?)""", st_rows)
        db.executemany(
            """INSERT INTO baselines
               (run_id, student_id, dim_name, theta, shrinkage_k, context_mean, n_obs)
               VALUES (?,?,?,?,?,?,?)""", base_rows)
        db.executemany(
            """INSERT OR IGNORE INTO attribution_steps
               (run_id, student_id, t, dim_name, prior_mean, posterior_mean, shift,
                residual, prior_sd, posterior_sd)
               VALUES (?,?,?,?,?,?,?,?,?,?)""", step_rows)
        db.executemany(
            """INSERT OR IGNORE INTO attribution_components
               (run_id, student_id, t, dim_name, channel, contribution, observed_value)
               VALUES (?,?,?,?,?,?,?)""", comp_rows)

        # ---- hazards ----------------------------------------------------
        if len(pp):
            risk = result.readout.cumulative_risk(pp[pp["student_id"].isin(keep)])
            db.executemany(
                "INSERT OR IGNORE INTO hazards (run_id, student_id, t, hazard, cum_risk, y) "
                "VALUES (?,?,?,?,?,?)",
                [(run_id, str(r["student_id"]), int(r["t"]), float(r["hazard"]),
                  float(r["cum_risk"]), int(r["y"])) for _, r in risk.iterrows()],
            )

        # ---- evaluation --------------------------------------------------
        db.executemany(
            "INSERT INTO metrics (run_id, model_name, auc, brier, ece, n, positives) "
            "VALUES (?,?,?,?,?,?,?)",
            [(run_id, m.name, float(m.auc), float(m.brier), float(m.ece), int(m.n),
              int(m.positives)) for m in result.metrics],
        )
        db.executemany(
            "INSERT INTO negative_controls (run_id, control, verdict, auc, is_leakage_test) "
            "VALUES (?,?,?,?,?)",
            [(run_id, c.control, c.verdict, float(c.auc), int(bool(c.is_leakage_test)))
             for c in result.negative_controls],
        )

        # ---- scenarios ---------------------------------------------------
        scen = scenarios if scenarios is not None else {"Current dynamics": 0.0}
        hz = result.readout.state_only_params()
        for label, magnitude in scen.items():
            scenario_id = uuid.uuid4().hex
            purpose = f"sim-{label}".replace(" ", "-").lower()
            iv = () if magnitude == 0 else (Intervention("engagement_support", float(magnitude)),)
            sc_obj = (InterventionScenario.baseline() if not iv
                      else InterventionScenario(label, iv))
            db.execute(
                """INSERT INTO scenarios
                   (scenario_id, run_id, label, interventions_json, is_counterfactual,
                    horizon, n_particles, seed_purpose)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (scenario_id, run_id, label,
                 json.dumps([{"name": "engagement_support", "magnitude": float(magnitude)}]
                            if iv else []),
                 int(bool(iv)), horizon, n_particles, purpose),
            )

            f_rows, r_rows, p_rows = [], [], []
            for sid, traj in students:
                theta = np.asarray(setpoints.get(sid, params.mu0), dtype=float)
                sim = simulate_forward(
                    traj.current, theta, params, sc_obj,
                    horizon=horizon, n_particles=n_particles,
                    hazard_params=hz, rng=rng_for(cfg, f"{purpose}-{sid}"),
                )
                q = sim.state_quantiles((0.05, 0.5, 0.95))
                for h, (_, row) in enumerate(q.iterrows()):
                    for name in dim_names:
                        f_rows.append((scenario_id, sid, h, int(row["t"]), name,
                                       float(row[f"{name}_q05"]), float(row[f"{name}_q50"]),
                                       float(row[f"{name}_q95"]), float(row[f"{name}_mean"])))
                cr = sim.cumulative_risk()
                if cr is not None:
                    r_rows += [(scenario_id, sid, h, float(v)) for h, v in enumerate(cr)]
                take = min(N_RETAINED_PATHS, sim.states.shape[0])
                pick = rng_for(cfg, f"{purpose}-paths-{sid}").choice(
                    sim.states.shape[0], size=take, replace=False)
                for ix, pi in enumerate(pick):
                    for h in range(horizon):
                        for j, name in enumerate(dim_names):
                            p_rows.append((scenario_id, sid, ix, h, name,
                                           float(sim.states[pi, h, j])))
            db.executemany(
                """INSERT INTO forecasts
                   (scenario_id, student_id, h, t, dim_name, q05, q50, q95, mean)
                   VALUES (?,?,?,?,?,?,?,?,?)""", f_rows)
            db.executemany(
                "INSERT INTO forecast_risk (scenario_id, student_id, h, cum_risk) "
                "VALUES (?,?,?,?)", r_rows)
            db.executemany(
                """INSERT INTO forecast_paths
                   (scenario_id, student_id, particle_ix, h, dim_name, value)
                   VALUES (?,?,?,?,?,?)""", p_rows)

    return run_id


def record_capability_tests(db: Database, run_id: str, results: list) -> None:
    """Store T1-T4 outcomes.

    Only tests that actually ran are stored. T3 and T4 raise
    NotImplementedError upstream, so they are absent here rather than
    recorded as passing - an absent row and a failing row are both honest;
    a fabricated pass is not.
    """
    with transaction(db.conn):
        db.executemany(
            """INSERT OR REPLACE INTO capability_tests
               (run_id, test_id, name, passed, statistic, threshold, detail)
               VALUES (?,?,?,?,?,?,?)""",
            [(run_id, r.test_id, r.name, int(bool(r.passed)), float(r.statistic),
              float(r.threshold), r.detail) for r in results],
        )
