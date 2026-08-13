"""Deterministic synthetic cohort.

Purpose and limits
------------------
This exists for two legitimate reasons:

1. Pipeline tests that must not depend on a 500MB download.
2. Ground truth. Because the cohort is generated from a *known* latent process,
   it is the only place where we can check whether the estimator recovers the
   dynamics it is supposed to recover  -  Gate 1 experiment E6. Observational data
   cannot do that.

It is NOT a substitute for OULAD. Any number produced from this adapter is a
statement about our estimator, never about students. Every artefact derived from
it is stamped `synthetic=True` and the dashboard refuses to hide that.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..schema import (
    AdapterOutput,
    CanonicalType,
    ContextMetadata,
    CoverageManifest,
    EventTable,
    OutcomeTable,
)
from . import DatasetAdapter

# Ground-truth generating parameters. The estimator is not given these.
TRUE_ALPHA = np.array([0.35, 0.18])
TRUE_Q = np.diag([0.20, 0.10])
TRUE_LOADINGS = {
    CanonicalType.CONTENT_VIEW: (2.85, 0.95),   # (intercept, loading on engagement)
    CanonicalType.FORUM: (1.30, 0.70),
    CanonicalType.QUIZ_ATTEMPT: (0.90, 0.55),
    CanonicalType.RESOURCE: (1.90, 0.80),
}
TRUE_SUBMIT = (1.20, 0.80, 0.45)   # intercept, engagement weight, capability weight
TRUE_SCORE = (0.15, 0.85, 0.45)    # intercept, capability weight, sd on logit scale
TRUE_HAZARD = (-3.4, -0.85, -0.35)  # intercept, engagement weight, capability weight


def _sigmoid(x: np.ndarray | float) -> np.ndarray | float:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


class SyntheticAdapter(DatasetAdapter):
    """A small cohort drawn from the Gate 1 generative model."""

    name = "synthetic"

    def __init__(
        self,
        n_students: int = 120,
        n_weeks: int = 20,
        n_contexts: int = 2,
        seed: int = 20260813,
    ) -> None:
        self.n_students = n_students
        self.n_weeks = n_weeks
        self.n_contexts = n_contexts
        self.seed = seed
        self._truth: dict[str, np.ndarray] = {}

    def is_available(self) -> bool:
        return True  # generated on demand

    def coverage(self) -> CoverageManifest:
        available = {
            CanonicalType.CONTENT_VIEW.value,
            CanonicalType.FORUM.value,
            CanonicalType.QUIZ_ATTEMPT.value,
            CanonicalType.RESOURCE.value,
            CanonicalType.SUBMISSION.value,
            CanonicalType.SCORE.value,
            CanonicalType.REGISTER.value,
            CanonicalType.WITHDRAW.value,
        }
        return CoverageManifest(
            dataset=self.name,
            available=frozenset(available),
            unavailable=frozenset({t.value for t in CanonicalType} - available),
            notes={
                "provenance": "SYNTHETIC. Generated from a known latent process. "
                              "Not real students; never report as an empirical result.",
                "purpose": "pipeline tests and E6 ground-truth recovery checks",
            },
        )

    @property
    def true_states(self) -> dict[str, np.ndarray]:
        """Latent trajectories used to generate the data, keyed by student_id.

        Available only after `load()`. Used by E6 to score state recovery.
        """
        if not self._truth:
            raise RuntimeError("call load() before requesting ground-truth states")
        return self._truth

    def load(self) -> AdapterOutput:
        rng = np.random.default_rng(self.seed)
        rows: list[dict] = []
        outcome_rows: list[dict] = []
        contexts: dict[str, ContextMetadata] = {}

        per_ctx = max(1, self.n_students // self.n_contexts)

        for c in range(self.n_contexts):
            cid = f"SYN{c}_2026A"
            # Contexts differ in base rate and assessment rhythm on purpose: this is
            # what makes the fixture usable for divergence-curve smoke tests.
            hazard_shift = -0.5 + 1.0 * c
            assess_every = 3 + c
            contexts[cid] = ContextMetadata(
                context_id=cid,
                n_weeks=self.n_weeks,
                modality="distance",
                discipline="stem" if c % 2 == 0 else "social_science",
                cohort_size=per_ctx,
                assessment_density=1.0 / assess_every,
                has_high_stakes_exam=(c == 0),
                mean_credit_load=60.0,
                source_dataset=self.name,
            )

            for i in range(per_ctx):
                sid = f"S{c:02d}{i:04d}"
                theta = rng.normal([0.0, 0.0], [0.9, 0.8])
                z = theta + rng.normal(0, 0.5, size=2)
                traj = np.zeros((self.n_weeks, 2))

                withdrew, wweek = False, np.nan
                rows.append(dict(student_id=sid, context_id=cid, t=0,
                                 channel="enrolment",
                                 canonical_type=CanonicalType.REGISTER.value, value=1.0))

                for t in range(self.n_weeks):
                    traj[t] = z
                    # emissions
                    for ctype, (b0, load) in TRUE_LOADINGS.items():
                        mu = np.exp(b0 + load * z[0])
                        # negative binomial via gamma-Poisson mixture
                        shape = 4.0
                        lam = rng.gamma(shape, mu / shape)
                        count = rng.poisson(lam)
                        if count > 0:
                            rows.append(dict(student_id=sid, context_id=cid, t=t,
                                             channel="behavior",
                                             canonical_type=ctype.value, value=float(count)))
                    if t % assess_every == 0 and t > 0:
                        p_sub = _sigmoid(TRUE_SUBMIT[0] + TRUE_SUBMIT[1] * z[0]
                                         + TRUE_SUBMIT[2] * z[1])
                        if rng.random() < p_sub:
                            rows.append(dict(student_id=sid, context_id=cid, t=t,
                                             channel="assessment",
                                             canonical_type=CanonicalType.SUBMISSION.value,
                                             value=1.0))
                            logit_s = (TRUE_SCORE[0] + TRUE_SCORE[1] * z[1]
                                       + rng.normal(0, TRUE_SCORE[2]))
                            rows.append(dict(student_id=sid, context_id=cid, t=t,
                                             channel="assessment",
                                             canonical_type=CanonicalType.SCORE.value,
                                             value=float(np.clip(_sigmoid(logit_s), 0.01, 0.99))))
                    # hazard
                    h = _sigmoid(TRUE_HAZARD[0] + hazard_shift
                                 + TRUE_HAZARD[1] * z[0] + TRUE_HAZARD[2] * z[1])
                    if rng.random() < h:
                        withdrew, wweek = True, t
                        rows.append(dict(student_id=sid, context_id=cid, t=t,
                                         channel="enrolment",
                                         canonical_type=CanonicalType.WITHDRAW.value, value=1.0))
                        break
                    # transition
                    z = (z + TRUE_ALPHA * (theta - z)
                         + rng.multivariate_normal([0, 0], TRUE_Q))

                self._truth[sid] = traj[: (int(wweek) + 1 if withdrew else self.n_weeks)]
                outcome_rows.append(dict(
                    student_id=sid, context_id=cid,
                    event_week=float(wweek) if withdrew else np.nan,
                    event_observed=bool(withdrew),
                    final_result="Withdrawn" if withdrew else "Pass",
                ))

        events = EventTable(pd.DataFrame(rows))
        outcomes = OutcomeTable(pd.DataFrame(outcome_rows))
        rates = outcomes.df.groupby("context_id", observed=True)["event_observed"].mean().to_dict()
        contexts = {
            cid: ContextMetadata(**{**vars(m), "observed_base_rate": rates.get(cid, float("nan"))})
            for cid, m in contexts.items()
        }
        return AdapterOutput(
            events=events, contexts=contexts, outcomes=outcomes, coverage=self.coverage()
        )
