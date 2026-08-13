"""Negative controls  -  Gate 1 experiment E8.

Each control destroys a structure the model might be exploiting, then asks what
survives. The point is diagnosis, not a green tick.

An important correction discovered while building the prototype
---------------------------------------------------------------
"AUC collapses to chance" is NOT the right expectation for every control, and
treating it as one produces false alarms. Specifically:

  permute_time shuffles week order *within* a student. That preserves the
  student's mean state exactly. A model whose signal is the student's overall
  engagement *level* will therefore keep almost all of its AUC  -  correctly, with
  no leakage anywhere. Reading that as a leak would be wrong.

So each control carries its own expectation, and `verdict` distinguishes three
outcomes rather than pass/fail:

  COLLAPSED      performance fell toward chance
  SURVIVED       performance held up
  UNDEFINED      the permuted data had no positives to score

What each outcome *means* is control-specific and is spelled out in
`interpretation`. The single genuine leakage test here is
`permute_student_identity`: it severs the link between a trajectory and its
outcome, and nothing legitimate can survive it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd


@dataclass
class NegativeControlResult:
    control: str
    what_it_destroys: str
    auc: float
    reference_auc: float
    verdict: str                 # COLLAPSED | SURVIVED | UNDEFINED
    is_leakage_test: bool
    concerning: bool             # True only when this outcome should worry us
    interpretation: str

    def as_dict(self) -> dict:
        return {
            "control": self.control,
            "destroys": self.what_it_destroys,
            "auc": self.auc,
            "reference_auc": self.reference_auc,
            "verdict": self.verdict,
            "leakage_test": self.is_leakage_test,
            "concerning": self.concerning,
            "interpretation": self.interpretation,
        }


def permute_time(pp: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    """Shuffle week order within each student.

    Destroys temporal ordering while preserving each student's marginal
    distribution of states  -  and therefore their mean level exactly.
    """
    rng = np.random.default_rng(seed)
    out = pp.copy()
    feat_cols = [c for c in out.columns if c.startswith(("z_", "sd_"))]
    parts = []
    for _, grp in out.groupby("student_id", observed=True, sort=False):
        g = grp.copy()
        g[feat_cols] = g[feat_cols].to_numpy()[rng.permutation(len(g))]
        parts.append(g)
    return pd.concat(parts, ignore_index=True) if parts else out


def permute_student_identity(pp: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    """Reassign outcomes across students, keeping each trajectory intact.

    The real leakage test. Severs trajectory-to-outcome linkage entirely; any
    surviving signal is coming from somewhere it should not.
    """
    rng = np.random.default_rng(seed)
    out = pp.copy()
    per_student = out.groupby("student_id", observed=True)["y"].max()
    shuffled = pd.Series(rng.permutation(per_student.to_numpy()), index=per_student.index)
    out["y"] = 0
    last = out.groupby("student_id", observed=True)["t"].transform("max")
    out.loc[(out["t"] == last) & (out["student_id"].map(shuffled) == 1), "y"] = 1
    return out


def permute_context_labels(pp: pd.DataFrame, seed: int = 0) -> pd.DataFrame:
    """Shuffle context assignment across students.

    Isolates the contribution of tier-2 covariates. State dimensions are left
    untouched, so a level-driven model is expected to survive this.
    """
    rng = np.random.default_rng(seed)
    out = pp.copy()
    ctxs = out["context_id"].unique()
    if len(ctxs) < 2:
        return out
    out["context_id"] = out["context_id"].map(dict(zip(ctxs, rng.permutation(ctxs))))
    return out


_SPECS = [
    {
        "fn": permute_time,
        "name": "permute_time",
        "destroys": "temporal ordering within a student",
        "leakage_test": False,
        "collapse_expected": False,
        "on_survived": (
            "Model is driven by the student's overall state LEVEL, not by trajectory "
            "shape  -  within-student permutation preserves the mean exactly. Not a leak. "
            "It does mean the twin is not yet earning its dynamics, which is Gate 1 "
            "weakness 1 and is what tests T1/T2 exist to pin down."
        ),
        "on_collapsed": (
            "Model genuinely depends on temporal ordering  -  the dynamics are carrying "
            "information beyond the level."
        ),
    },
    {
        "fn": permute_student_identity,
        "name": "permute_student_identity",
        "destroys": "trajectory-to-outcome linkage",
        "leakage_test": True,
        "collapse_expected": True,
        "on_survived": (
            "SERIOUS. Predictive signal survived severing the link between a student's "
            "trajectory and their outcome. Something other than the student's behaviour "
            "is driving predictions. Every other result is void until this is explained."
        ),
        "on_collapsed": "Collapsed toward chance, as required. No evidence of leakage.",
    },
    {
        "fn": permute_context_labels,
        "name": "permute_context_labels",
        "destroys": "student-to-context assignment",
        "leakage_test": False,
        "collapse_expected": False,
        "on_survived": (
            "Context covariates are not carrying the signal; the state dimensions are. "
            "Expected here, and informative for the transfer work  -  it means tier-2 "
            "terms are not acting as identity proxies."
        ),
        "on_collapsed": (
            "Context covariates carry substantial signal. Check they are not proxying "
            "institution identity before any transfer claim."
        ),
    },
]


def run_negative_controls(
    pp: pd.DataFrame,
    fit_predict: Callable[[pd.DataFrame], tuple[np.ndarray, np.ndarray]],
    reference_auc: float,
    *,
    seed: int = 0,
    collapse_threshold: float = 0.60,
) -> list[NegativeControlResult]:
    """Run every control through a caller-supplied fit/predict function.

    `fit_predict(person_period) -> (y_true, p)` keeps this module agnostic about
    which model is under audit.
    """
    from .metrics import auc as _auc

    results: list[NegativeControlResult] = []
    for spec in _SPECS:
        try:
            y, p = fit_predict(spec["fn"](pp, seed=seed))
            a = _auc(y, p)
        except Exception as exc:
            results.append(
                NegativeControlResult(
                    control=spec["name"], what_it_destroys=spec["destroys"],
                    auc=float("nan"), reference_auc=reference_auc, verdict="UNDEFINED",
                    is_leakage_test=spec["leakage_test"], concerning=True,
                    interpretation=f"CONTROL FAILED TO RUN: {type(exc).__name__}: {exc}",
                )
            )
            continue

        if np.isnan(a):
            verdict, concerning = "UNDEFINED", False
            interp = "No positive cases after permutation; AUC undefined."
        elif a <= collapse_threshold:
            verdict = "COLLAPSED"
            concerning = not spec["collapse_expected"] and False
            interp = spec["on_collapsed"]
        else:
            verdict = "SURVIVED"
            concerning = spec["collapse_expected"]
            interp = spec["on_survived"]

        results.append(
            NegativeControlResult(
                control=spec["name"], what_it_destroys=spec["destroys"], auc=a,
                reference_auc=reference_auc, verdict=verdict,
                is_leakage_test=spec["leakage_test"], concerning=concerning,
                interpretation=interp,
            )
        )
    return results


def leakage_verdict(results: list[NegativeControlResult]) -> str:
    """One-line summary keyed on the controls that actually test leakage."""
    tests = [r for r in results if r.is_leakage_test]
    if not tests:
        return "NO LEAKAGE TEST RUN"
    if any(r.concerning for r in tests):
        return "LEAKAGE SUSPECTED  -  results not trustworthy"
    if all(r.verdict == "UNDEFINED" for r in tests):
        return "INCONCLUSIVE  -  leakage tests had no positives to score"
    return "NO LEAKAGE DETECTED"
