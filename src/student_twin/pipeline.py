"""End-to-end prototype pipeline.

One function that walks the Gate 1 diagram from raw data to results, returning a
single object the script and the dashboard both consume. Keeping the orchestration
here rather than in the script means the dashboard cannot drift from what the
experiment actually ran.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .adapters import get_adapter
from .config import Config, rng_for
from .evaluation.metrics import MetricSet, compare, evaluate, reliability_table
from .evaluation.negative_controls import NegativeControlResult, run_negative_controls
from .evaluation.splits import forward_chained_split, random_split_LEAKY
from .features.context import build_context_covariates
from .features.tier1 import build_tier1, observation_frame
from .models.baselines import run_baseline_ladder
from .models.readout import HazardReadout, build_person_period
from .schema import AdapterOutput
from .state.filter import TwinFilter
from .state.fit import fit_twin
from .state.model import StateTrajectory, TwinParameters

log = logging.getLogger("student_twin")


@dataclass
class PipelineResult:
    """Everything one run produced. Provenance travels with the numbers."""

    dataset: str
    synthetic: bool
    config: Config
    data: AdapterOutput
    params: TwinParameters
    trajectories: dict[str, StateTrajectory]
    features: pd.DataFrame
    context_frame: pd.DataFrame
    person_period: pd.DataFrame
    readout: HazardReadout
    metrics: list[MetricSet] = field(default_factory=list)
    leaky_metrics: list[MetricSet] = field(default_factory=list)
    negative_controls: list[NegativeControlResult] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def results_table(self) -> pd.DataFrame:
        return compare(self.metrics)

    def provenance_banner(self) -> str:
        if self.synthetic:
            return (
                "SYNTHETIC DATA. Every number below describes the estimator's behaviour "
                "on data generated from a known process. None of it is a finding about "
                "students, and none of it may be reported as an OULAD result."
            )
        return f"Data source: {self.dataset}. Forward-chained evaluation."

    def summary(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "synthetic": self.synthetic,
            "n_students": len(self.trajectories),
            "n_person_period_rows": len(self.person_period),
            "event_rate": float(self.person_period["y"].mean()) if len(self.person_period) else None,
            "seed": self.config.seed,
            "state_dims": list(self.params.dim_names),
            "inference": "laplace_approximate",
            "timings_sec": {k: round(v, 2) for k, v in self.timings.items()},
            "warnings": self.warnings,
        }


def _timed(store: dict[str, float], key: str):
    class _T:
        def __enter__(self):
            self.t0 = time.perf_counter()
            return self

        def __exit__(self, *exc):
            store[key] = time.perf_counter() - self.t0
            return False

    return _T()


def run_pipeline(
    config: Config | None = None,
    *,
    adapter_name: str = "synthetic",
    adapter_kwargs: dict | None = None,
    cutoff_week: int | None = None,
    max_students: int | None = None,
    run_controls: bool = True,
    n_em_iters: int = 0,
) -> PipelineResult:
    """Run the whole pipeline.

    `n_em_iters` defaults to 0 (two-stage fit only). EM is implemented and
    available, but is NOT on by default: on the synthetic fixture it improves
    some parameters and degrades others, with variance collapse on the sparsely
    observed capability dimension. See docs/assumptions.md A-14.
    """
    cfg = config or Config()
    timings: dict[str, float] = {}
    warns: list[str] = []

    # -- load ------------------------------------------------------------
    with _timed(timings, "load"):
        adapter = get_adapter(adapter_name, **(adapter_kwargs or {}))
        if not adapter.is_available():
            raise FileNotFoundError(
                f"adapter {adapter_name!r} reports its raw data is not available. "
                "See data/README.md."
            )
        data = adapter.load()
    log.info("loaded %s: %s", adapter_name, data.summary())

    n_weeks = max((m.n_weeks for m in data.contexts.values()), default=None)

    # -- features --------------------------------------------------------
    with _timed(timings, "features"):
        obs = observation_frame(data.events, n_weeks=n_weeks)
        feats = build_tier1(data.events, cfg.features, n_weeks=n_weeks)
        ctx = build_context_covariates(data.events, data.contexts, n_weeks=n_weeks)

    # -- fit + filter ----------------------------------------------------
    with _timed(timings, "fit"):
        params = fit_twin(data, obs, ctx, cfg, n_em_iters=n_em_iters)
    setpoints = getattr(params, "student_setpoints", {})

    with _timed(timings, "filter"):
        filt = TwinFilter(params, cfg.state)
        trajectories = filt.filter_all(
            obs, ctx, setpoints=setpoints, max_students=max_students
        )
    log.info("filtered %d students", len(trajectories))

    # -- person-period + readout ----------------------------------------
    with _timed(timings, "readout"):
        pp = build_person_period(trajectories, data.outcomes, params, ctx)
        if pp.empty:
            raise RuntimeError("person-period frame is empty; nothing to evaluate")
        if cutoff_week is None:
            cutoff_week = max(cfg.evaluation.min_train_weeks, int(pp["t"].quantile(0.6)))
        train, test = forward_chained_split(pp, cutoff_week)
        if test.empty or train.empty:
            raise RuntimeError(f"forward-chained split at week {cutoff_week} left an empty side")
        readout = HazardReadout.fit(train, params)

    if int(test["y"].sum()) == 0:
        warns.append(
            f"No withdrawal events after week {cutoff_week} in the test split; "
            "AUC is undefined and reported as NaN rather than imputed."
        )

    # -- baseline ladder + twin -----------------------------------------
    with _timed(timings, "evaluate"):
        results: list[MetricSet] = []
        for b in run_baseline_ladder(train, test, feats, seed=cfg.seed):
            results.append(evaluate(b.name, b.y_true, b.predictions,
                                    cfg.evaluation.calibration_bins))
        twin_p = readout.hazard(test)
        results.append(evaluate("twin_state", test["y"].to_numpy(int), twin_p,
                                cfg.evaluation.calibration_bins))

        # L0, reported only to show the inflation
        ltr, lte = random_split_LEAKY(pp, seed=cfg.seed)
        leaky_readout = HazardReadout.fit(ltr, params)
        leaky = [
            evaluate("twin_state_L0_LEAKY", lte["y"].to_numpy(int),
                     leaky_readout.hazard(lte), cfg.evaluation.calibration_bins)
        ]

    # -- negative controls -----------------------------------------------
    controls: list[NegativeControlResult] = []
    if run_controls:
        with _timed(timings, "negative_controls"):
            ref = next((m.auc for m in results if m.name == "twin_state"), float("nan"))

            def _fit_predict(frame: pd.DataFrame):
                tr, te = forward_chained_split(frame, cutoff_week)
                if tr.empty or te.empty or tr["y"].nunique() < 2:
                    return np.array([0, 1]), np.array([0.5, 0.5])
                r = HazardReadout.fit(tr, params)
                return te["y"].to_numpy(int), r.hazard(te)

            controls = run_negative_controls(pp, _fit_predict, ref, seed=cfg.seed)

    return PipelineResult(
        dataset=data.coverage.dataset,
        synthetic=params.synthetic,
        config=cfg,
        data=data,
        params=params,
        trajectories=trajectories,
        features=feats,
        context_frame=ctx,
        person_period=pp,
        readout=readout,
        metrics=results,
        leaky_metrics=leaky,
        negative_controls=controls,
        timings=timings,
        warnings=warns,
    )
