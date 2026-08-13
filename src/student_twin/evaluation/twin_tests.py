"""Gate 1 twin capability tests T1-T4.

These decide whether the thing we built is a twin or a classifier wearing the
word. They are falsification tests: each has a stated failure consequence, and
failing one is a reportable result rather than something to tune away.

Implemented here: T1 (sufficiency) and T2 (generativity), which are the two that
Gate 1 flags as decisive for weakness 1. T3 (intervention stability) and T4
(identifiability) need repeated refits across seeds and modules and are Phase 1;
their entry points exist and raise NotImplementedError rather than returning a
misleading pass.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..state.filter import TwinFilter
from ..state.model import StateTrajectory, TwinParameters


@dataclass
class TwinTestResult:
    test_id: str
    name: str
    passed: bool
    statistic: float
    threshold: float
    detail: str
    consequence_if_failed: str

    def as_dict(self) -> dict:
        return {
            "test": self.test_id,
            "name": self.name,
            "passed": self.passed,
            "statistic": round(float(self.statistic), 5),
            "threshold": self.threshold,
            "detail": self.detail,
        }


def check_T1_sufficiency(
    filt: TwinFilter,
    obs_rows: list[dict[str, float]],
    theta: np.ndarray,
    context_rows: list[np.ndarray] | None = None,
    *,
    threshold: float = 0.02,
) -> TwinTestResult:
    """T1  -  is the state a sufficient statistic for the history?

    Compares the recursive estimate at week T against re-running the filter from
    scratch over the full history. For a correctly implemented filter these are
    identical by construction, so this is primarily a *regression guard*: it
    catches an implementation that secretly depends on replayed history, or a
    state object that is not actually carrying information forward.

    Failure consequence: the state is bookkeeping, not a twin. Report it.
    """
    full = filt.filter_student("T1", "ctx", obs_rows, theta, context_rows=context_rows)

    # Re-derive the final state by feeding the filter one week at a time and
    # carrying only the state object across calls.
    carried = None
    for i, row in enumerate(obs_rows):
        ctx = [context_rows[i]] if context_rows is not None and i < len(context_rows) else None
        if carried is None:
            step = filt.filter_student("T1", "ctx", [row], theta, context_rows=ctx)
        else:
            m_pred, P_pred = filt.predict(carried, theta,
                                          u=(ctx[0] if ctx else None), d=None)
            m_post, P_post, _, n = filt.update(m_pred, P_pred, row)
            from ..state.model import InferenceMethod, TwinState

            step = StateTrajectory("T1", "ctx")
            step.states.append(
                TwinState("T1", "ctx", int(row.get("t", i)), m_post, P_post,
                          InferenceMethod.LAPLACE, carried.n_observations + n)
            )
        carried = step.states[-1]

    diff = float(np.max(np.abs(carried.mean - full.current.mean)))
    return TwinTestResult(
        test_id="T1",
        name="sufficiency (recursive == full replay)",
        passed=diff <= threshold,
        statistic=diff,
        threshold=threshold,
        detail=(
            f"max |recursive - full-replay| over state dims = {diff:.2e}. "
            "The state carries the history forward without replay."
        ),
        consequence_if_failed=(
            "State is not a sufficient statistic; the twin is bookkeeping over a "
            "feature window and should be described as such."
        ),
    )


def check_T2_generativity(
    checks: list[dict[str, float]], *, coverage_target: float = 0.90,
    coverage_tol: float = 0.07, dispersion_floor: float = 0.5,
    dispersion_ceiling: float = 2.0,
) -> TwinTestResult:
    """T2  -  are simulated trajectories distributionally plausible?

    Consumes the output of `simulation.forward.posterior_predictive_check` across
    students. Three ways to fail, in both directions:

      coverage far from nominal   the bands are the wrong width
      dispersion ratio << 1       simulated futures smoother than real ones  -  the
                                  classic state-space failure, dangerous because
                                  it makes the twin look confident
      dispersion ratio >> 1       bands far too wide. Coverage looks excellent
                                  precisely because the forecast says almost
                                  nothing. Under-confidence is a failure too, and
                                  a coverage-only test would wave it through.

    Failure consequence: counterfactual simulation is not trustworthy and the
    scenario feature must be withdrawn from the dashboard.
    """
    valid = [c for c in checks if np.isfinite(c.get("coverage_90", np.nan))]
    if not valid:
        return TwinTestResult(
            "T2", "generativity (posterior predictive)", False, float("nan"),
            coverage_target, "No overlapping weeks between simulation and held-out data.",
            "Cannot assess; do not claim generative validity.",
        )
    cov = float(np.mean([c["coverage_90"] for c in valid]))
    disps = [c["dispersion_ratio"] for c in valid if np.isfinite(c.get("dispersion_ratio", np.nan))]
    disp = float(np.mean(disps)) if disps else float("nan")

    cov_ok = abs(cov - coverage_target) <= coverage_tol
    disp_ok = (not np.isfinite(disp)) or (dispersion_floor <= disp <= dispersion_ceiling)
    if np.isfinite(disp) and disp > dispersion_ceiling:
        diag = "OVER-DISPERSED: bands too wide, forecast is under-confident"
    elif np.isfinite(disp) and disp < dispersion_floor:
        diag = "UNDER-DISPERSED: simulated futures too smooth, forecast is over-confident"
    else:
        diag = "dispersion within range"
    return TwinTestResult(
        test_id="T2",
        name="generativity (posterior predictive)",
        passed=bool(cov_ok and disp_ok),
        statistic=cov,
        threshold=coverage_target,
        detail=(
            f"90% band covered {cov:.1%} of held-out observations across {len(valid)} "
            f"students (target {coverage_target:.0%} +/- {coverage_tol:.0%}); "
            f"mean dispersion ratio {disp:.2f} "
            f"(acceptable {dispersion_floor}-{dispersion_ceiling}) -> {diag}."
        ),
        consequence_if_failed=(
            "Simulated futures are not distributionally plausible; withdraw the "
            "scenario feature until fixed."
        ),
    )


@dataclass
class SignalDecomposition:
    """Where the predictive signal actually lives.

    `level` is the student's own running mean state - a between-student quantity.
    `deviation` is z_t minus that mean - a within-student, trajectory quantity.
    Both are computed causally (expanding mean over weeks <= t), because using
    the full-trajectory mean would leak the future into the level term.
    """

    auc_full: float
    auc_level_only: float
    auc_deviation_only: float
    n_test: int
    positives: int

    @property
    def trajectory_share(self) -> float:
        """How much discrimination the deviation term adds over the level alone.

        Near 0 means the twin is a level detector and its dynamics are decorative.
        """
        lift_level = max(0.0, self.auc_level_only - 0.5)
        lift_dev = max(0.0, self.auc_deviation_only - 0.5)
        total = lift_level + lift_dev
        if total <= 0:
            return float("nan")
        # Share of the available discrimination that the within-student term
        # supplies. Bounded [0,1] by construction: comparing against auc_full
        # allowed values above 1 whenever the level term scored below chance.
        return float(lift_dev / total)

    @property
    def verdict(self) -> str:
        s = self.trajectory_share
        if np.isnan(s):
            return "UNDEFINED (no discrimination to decompose)"
        if s < 0.15:
            return "LEVEL-DRIVEN: dynamics are not earning their place"
        if s < 0.40:
            return "MIXED: level dominates but trajectory contributes"
        return "TRAJECTORY-DRIVEN: within-student change carries real signal"

    def as_dict(self) -> dict:
        return {
            "auc_full": round(self.auc_full, 4),
            "auc_level_only": round(self.auc_level_only, 4),
            "auc_deviation_only": round(self.auc_deviation_only, 4),
            "trajectory_share": (
                None if np.isnan(self.trajectory_share) else round(self.trajectory_share, 4)
            ),
            "verdict": self.verdict,
            "n_test": self.n_test,
            "positives": self.positives,
        }


def decompose_level_vs_trajectory(
    person_period: pd.DataFrame, params, cutoff_week: int
) -> SignalDecomposition:
    """Split the state into between-student level and within-student deviation.

    This answers Gate 1 weakness 1 directly, rather than inferring it from a
    permutation control. `permute_time` cannot distinguish "level-driven" from
    "leaking" on its own; this can.
    """
    from ..evaluation.metrics import auc as _auc
    from ..evaluation.splits import forward_chained_split
    from ..models.readout import HazardReadout

    zc = [f"z_{n}" for n in params.dim_names]
    pp = person_period.sort_values(["student_id", "t"]).copy()

    g = pp.groupby("student_id", observed=True)
    for c in zc:
        pp[f"{c}__level"] = g[c].transform(lambda s: s.expanding().mean())
        pp[f"{c}__dev"] = pp[c] - pp[f"{c}__level"]

    def _run(cols: list[str]) -> float:
        frame = pp.copy()
        for src, dst in zip(cols, zc):
            frame[dst] = pp[src]
        tr, te = forward_chained_split(frame, cutoff_week)
        if tr.empty or te.empty or tr["y"].nunique() < 2:
            return float("nan")
        r = HazardReadout.fit(tr, params)
        return _auc(te["y"].to_numpy(int), r.hazard(te))

    tr, te = forward_chained_split(pp, cutoff_week)
    return SignalDecomposition(
        auc_full=_run(zc),
        auc_level_only=_run([f"{c}__level" for c in zc]),
        auc_deviation_only=_run([f"{c}__dev" for c in zc]),
        n_test=len(te),
        positives=int(te["y"].sum()) if len(te) else 0,
    )


def check_T3_intervention_stability(*_args, **_kwargs) -> TwinTestResult:
    raise NotImplementedError(
        "T3 requires refitting across seeds and checking sign/magnitude stability of "
        "the intervention response. Phase 1. Returning a pass here would be a lie."
    )


def check_T4_identifiability(*_args, **_kwargs) -> TwinTestResult:
    raise NotImplementedError(
        "T4 requires rotation-aware comparison of latent dimensions across independent "
        "refits and across contexts. Phase 1. Until it runs, the dimension names "
        "'engagement' and 'capability' are labels of convenience, not validated "
        "constructs -- see docs/assumptions.md A-06."
    )


def summarise(results: list[TwinTestResult]) -> pd.DataFrame:
    return pd.DataFrame([r.as_dict() for r in results])
