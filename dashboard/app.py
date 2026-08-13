"""Prototype dashboard.

    streamlit run dashboard/app.py

Design rule for this file: nothing model-generated may appear without a label
saying so. The counterfactual panel is the easiest place in the whole project to
mislead someone, so the provenance string is rendered next to the chart rather
than in a footnote.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from student_twin.config import Config, rng_for                      # noqa: E402
from student_twin.evaluation.negative_controls import leakage_verdict  # noqa: E402
from student_twin.explain import explain_trajectory, biggest_movers  # noqa: E402
from student_twin.pipeline import run_pipeline                       # noqa: E402
from student_twin.simulation import (                                # noqa: E402
    Intervention,
    InterventionScenario,
    simulate_forward,
)

st.set_page_config(page_title="Student Digital Twin - prototype", layout="wide")


@st.cache_resource(show_spinner="Running pipeline...")
def load(adapter: str, n_students: int, n_weeks: int):
    cfg = Config()
    kwargs = dict(n_students=n_students, n_weeks=n_weeks) if adapter == "synthetic" else {}
    return cfg, run_pipeline(cfg, adapter_name=adapter, adapter_kwargs=kwargs)


st.title("Student Digital Twin - prototype")

with st.sidebar:
    st.header("Run")
    adapter = st.selectbox("Dataset", ["synthetic", "oulad"], index=0)
    n_students = st.slider("Students (synthetic only)", 40, 400, 150, step=20)
    n_weeks = st.slider("Weeks (synthetic only)", 10, 30, 20)
    st.caption(
        "OULAD requires the raw CSVs in data/raw/oulad. See data/README.md. "
        "Without them the adapter refuses to run rather than substituting synthetic data."
    )

try:
    cfg, R = load(adapter, n_students, n_weeks)
except FileNotFoundError as exc:
    st.error(str(exc))
    st.stop()

if R.synthetic:
    st.error(
        "**SYNTHETIC DATA.** Everything on this page describes the estimator's behaviour "
        "on data generated from a known process. Nothing here is a finding about real "
        "students, and none of it may be reported as an OULAD result.",
        icon=":material/warning:",
    )

tab_student, tab_scenario, tab_eval = st.tabs(
    ["Student twin", "Scenario simulation", "Evaluation and controls"]
)

# ---------------------------------------------------------------- student ---
with tab_student:
    ids = sorted(R.trajectories)
    sid = st.selectbox("Student", ids, index=0)
    traj = R.trajectories[sid]
    frame = traj.to_frame(R.params.dim_names)

    c1, c2, c3, c4 = st.columns(4)
    cur = traj.current
    c1.metric("Weeks observed", len(traj))
    c2.metric(f"{R.params.dim_names[0]} (now)", f"{cur.mean[0]:+.2f}", f"+/- {cur.sd[0]:.2f}")
    if R.params.n_dims > 1:
        c3.metric(f"{R.params.dim_names[1]} (now)", f"{cur.mean[1]:+.2f}", f"+/- {cur.sd[1]:.2f}")
    pp_s = R.person_period[R.person_period["student_id"] == sid]
    if len(pp_s):
        c4.metric("Weekly hazard (latest)", f"{R.readout.hazard(pp_s)[-1]:.3f}")

    st.subheader("State trajectory with uncertainty")
    st.caption(
        "Filtering uncertainty (posterior SD) only. Parameter and transfer uncertainty "
        "are architectural hooks and are NOT yet estimated - see docs/assumptions.md A-05."
    )
    for j, name in enumerate(R.params.dim_names):
        band = pd.DataFrame(
            {
                "t": frame["t"],
                f"{name}": frame[f"{name}_mean"],
                "lower": frame[f"{name}_mean"] - 1.96 * frame[f"{name}_sd"],
                "upper": frame[f"{name}_mean"] + 1.96 * frame[f"{name}_sd"],
            }
        ).set_index("t")
        st.line_chart(band, height=220)

    st.subheader("Why did the state change?")
    dim = st.radio("Dimension", list(range(R.params.n_dims)),
                   format_func=lambda i: R.params.dim_names[i], horizontal=True)
    for e in biggest_movers(traj, R.params, dim=dim, k=3):
        st.code(e.to_text(), language=None)
    with st.expander("Full weekly attribution table"):
        st.dataframe(explain_trajectory(traj, R.params, dim=dim), use_container_width=True)

# --------------------------------------------------------------- scenario ---
with tab_scenario:
    st.subheader("Counterfactual scenario")
    st.warning(
        "**These are simulation controls, not estimated causal effects.** OULAD records "
        "no interventions, so the sensitivity matrix is *assumed*, not fitted. Read every "
        "output below as \"under the model's assumed transition dynamics...\", never as "
        "\"doing this will improve the student's outcome\".",
        icon=":material/science:",
    )

    sid2 = st.selectbox("Student ", sorted(R.trajectories), key="scen_student")
    traj2 = R.trajectories[sid2]
    setpoints = getattr(R.params, "student_setpoints", {})
    theta = setpoints.get(sid2, R.params.mu0)
    hz = R.readout.state_only_params()

    col1, col2 = st.columns(2)
    lever = col1.selectbox("Intervention", list(R.params.intervention_names))
    intensity = col2.slider("Intensity (state units, assumed)", -2.0, 2.0, 1.0, 0.25)
    horizon = st.slider("Horizon (weeks)", 2, 16, cfg.simulation.horizon_weeks)

    base = simulate_forward(
        traj2.current, theta, R.params, InterventionScenario.baseline(),
        horizon=horizon, n_particles=cfg.simulation.n_particles,
        hazard_params=hz, rng=rng_for(cfg, "dash-base"),
    )
    scen = InterventionScenario(
        label=f"{lever} @ {intensity:+.2f}",
        interventions=(Intervention(lever, intensity=intensity),),
    )
    alt = simulate_forward(
        traj2.current, theta, R.params, scen,
        horizon=horizon, n_particles=cfg.simulation.n_particles,
        hazard_params=hz, rng=rng_for(cfg, "dash-alt"),
    )

    weeks = np.arange(1, horizon + 1) + traj2.current.t
    st.markdown("**Cumulative risk: baseline vs scenario (both model-generated)**")
    st.line_chart(
        pd.DataFrame(
            {"baseline": base.cumulative_risk(), "scenario": alt.cumulative_risk()},
            index=weeks,
        ),
        height=260,
    )

    q = cfg.simulation.quantiles
    bq, aq = base.state_quantiles(q), alt.state_quantiles(q)
    nm = R.params.dim_names[0]
    st.markdown(f"**Simulated {nm} trajectory, 5-95% band**")
    st.line_chart(
        pd.DataFrame(
            {
                "baseline median": bq[f"{nm}_q50"],
                "baseline q05": bq[f"{nm}_q05"],
                "baseline q95": bq[f"{nm}_q95"],
                "scenario median": aq[f"{nm}_q50"],
            },
            index=bq["t"],
        ),
        height=260,
    )
    st.info(alt.provenance(), icon=":material/info:")

# ------------------------------------------------------------- evaluation ---
with tab_eval:
    st.subheader("Baseline ladder (forward-chained)")
    st.dataframe(R.results_table, use_container_width=True)
    st.caption(
        "Gate 1 H1 predicts approximate parity on discrimination and an advantage on "
        "calibration. The twin winning AUC here is not the expected outcome and should "
        "not be reported as one until it replicates on real data."
    )

    with st.expander("L0 random split (LEAKY) - shown only to expose the inflation"):
        from student_twin.evaluation.metrics import compare
        st.dataframe(compare(R.leaky_metrics), use_container_width=True)

    st.subheader("Negative controls")
    st.dataframe(
        pd.DataFrame([c.as_dict() for c in R.negative_controls]), use_container_width=True
    )
    v = leakage_verdict(R.negative_controls)
    (st.success if "NO LEAKAGE" in v else st.error)(v)

    st.subheader("Feature provenance")
    from student_twin.features import REGISTRY
    st.dataframe(REGISTRY.as_frame(), use_container_width=True)

    st.subheader("Adapter coverage")
    cov = R.data.coverage
    st.write(f"**{cov.dataset}** supplies {len(cov.available)} canonical types.")
    st.json({"available": sorted(cov.available), "unavailable": sorted(cov.unavailable),
             "notes": cov.notes})
