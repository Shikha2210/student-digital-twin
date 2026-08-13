"""Tier-2 context covariates.

These condition the transition (the `B u` term) and the hazard readout. They
describe the *course*, never the institution's identity, and never the student.

`weeks_remaining` and `assessment_due` are time-varying; the rest are constant
within a context. Both kinds are here because the transition needs a per-week
covariate vector.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..schema import CanonicalType, ContextMetadata, EventTable
from .provenance import REGISTRY, FeatureSpec

_SPECS = [
    FeatureSpec(
        name="assessment_due",
        tier=2,
        description="Whether an assessment falls in this week for this context.",
        depends_on=(CanonicalType.SUBMISSION.value, "context_metadata"),
        normalisation="binary indicator, context-derived",
    ),
    FeatureSpec(
        name="weeks_remaining_frac",
        tier=2,
        description="Weeks left in the presentation, as a fraction of its length.",
        depends_on=("context_metadata",),
        normalisation="divided by course length; bounded [0,1]",
    ),
    FeatureSpec(
        name="assessment_density",
        tier=2,
        description="Assessments per week across the presentation.",
        depends_on=("context_metadata",),
        normalisation="per-week rate",
    ),
    FeatureSpec(
        name="is_distance",
        tier=2,
        description="Delivery modality indicator.",
        depends_on=("context_metadata",),
        normalisation="binary indicator",
    ),
    FeatureSpec(
        name="is_stem",
        tier=2,
        description="Discipline indicator.",
        depends_on=("context_metadata",),
        normalisation="binary indicator",
    ),
    FeatureSpec(
        name="log_cohort_size",
        tier=2,
        description="log1p of cohort size; a proxy for how well the context is estimated.",
        depends_on=("context_metadata",),
        normalisation="log transform",
    ),
]

for _s in _SPECS:
    if _s.name not in REGISTRY:
        REGISTRY.register(_s)

CONTEXT_FEATURES: tuple[str, ...] = tuple(s.name for s in _SPECS)

#: Covariates entering the state transition. Deliberately a strict subset:
#: constant-within-context terms cannot drive week-to-week state change, so
#: including them would only add unidentifiable parameters.
TRANSITION_COVARIATES: tuple[str, ...] = ("assessment_due", "weeks_remaining_frac")


def build_context_covariates(
    events: EventTable,
    contexts: dict[str, ContextMetadata],
    *,
    n_weeks: int | None = None,
) -> pd.DataFrame:
    """One row per (context, week) with the tier-2 vector."""
    rows: list[dict] = []

    due_weeks: dict[str, set[int]] = {}
    if len(events):
        sub = events.df[events.df["canonical_type"].astype(str) == CanonicalType.SUBMISSION.value]
        for cid, grp in sub.groupby("context_id", observed=True):
            # a week is an assessment week if a non-trivial share of the cohort submits
            counts = grp.groupby("t", observed=True).size()
            if len(counts):
                threshold = max(1.0, 0.05 * float(counts.max()))
                due_weeks[str(cid)] = {int(t) for t, n in counts.items() if n >= threshold}

    for cid, meta in contexts.items():
        horizon = int(n_weeks if n_weeks is not None else meta.n_weeks)
        due = due_weeks.get(cid, set())
        for t in range(horizon):
            rows.append(
                {
                    "context_id": cid,
                    "t": t,
                    "assessment_due": float(t in due),
                    "weeks_remaining_frac": float(
                        np.clip((meta.n_weeks - t) / max(meta.n_weeks, 1), 0.0, 1.0)
                    ),
                    "assessment_density": float(meta.assessment_density),
                    "is_distance": float(meta.modality == "distance"),
                    "is_stem": float(meta.discipline == "stem"),
                    "log_cohort_size": float(np.log1p(meta.cohort_size)),
                }
            )
    return pd.DataFrame(rows, columns=["context_id", "t", *CONTEXT_FEATURES])
