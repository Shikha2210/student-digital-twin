"""Why did the twin's state change this week?

The explanation is structural, not post-hoc. For a Gaussian-approximate Bayesian
update the mean shift decomposes as

    z_post - z_pred  ~=  P_post @ sum_c grad_c(z_pred)

so each observation channel's contribution is P_post @ grad_c  -  a quantity the
filter already computes on its way to the posterior. Nothing is fitted here and
no surrogate model is involved, which is why the attribution cannot disagree with
the model it is explaining.

What this is NOT: a statement about motivation, effort, or knowledge. It reports
which observations moved a fitted latent coordinate, in the model's own units.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .state.model import StateTrajectory, StepAttribution, TwinParameters

#: Human-readable phrasing for each channel. Kept deliberately behavioural.
_CHANNEL_PHRASE = {
    "content_view": "content views",
    "forum": "forum activity",
    "quiz_attempt": "quiz activity",
    "resource": "resource access",
    "submission": "submission behaviour",
    "score": "assessment score",
}


@dataclass
class WeekExplanation:
    student_id: str
    t: int
    dim_name: str
    shift: float
    direction: str
    contributions: list[tuple[str, float]]
    observations: dict[str, float]
    unexplained: float

    def to_text(self, top_k: int = 3) -> str:
        if abs(self.shift) < 1e-4:
            return f"Week {self.t}: {self.dim_name} state essentially unchanged."
        lines = [f"Week {self.t}: {self.dim_name} state {self.direction} by {abs(self.shift):.3f}"]
        lines.append("because:")
        for name, val in self.contributions[:top_k]:
            if abs(val) < 1e-4:
                continue
            phrase = _CHANNEL_PHRASE.get(name, name)
            obs = self.observations.get(name)
            obs_txt = f" (observed {obs:g})" if obs is not None else ""
            arrow = "pushed up" if val > 0 else "pushed down"
            lines.append(f"  - {phrase}{obs_txt} {arrow} by {abs(val):.3f}")
        if abs(self.unexplained) > 0.05 * max(abs(self.shift), 1e-6):
            lines.append(
                f"  - {self.unexplained:+.3f} not attributable to a single channel "
                "(higher-order term in the update)"
            )
        return "\n".join(lines)


def explain_week(
    attribution: StepAttribution,
    params: TwinParameters,
    dim: int = 0,
    student_id: str = "",
) -> WeekExplanation:
    shift = float(attribution.total_shift[dim])
    return WeekExplanation(
        student_id=student_id,
        t=attribution.t,
        dim_name=params.dim_names[dim],
        shift=shift,
        direction="rose" if shift > 0 else "fell",
        contributions=attribution.ranked(dim),
        observations=attribution.observations,
        unexplained=float(attribution.residual[dim]),
    )


def explain_trajectory(
    traj: StateTrajectory, params: TwinParameters, dim: int = 0
) -> pd.DataFrame:
    """Per-week attribution table for one student and one state dimension."""
    rows = []
    for att in traj.attributions:
        exp = explain_week(att, params, dim=dim, student_id=traj.student_id)
        row = {
            "t": exp.t,
            "dim": exp.dim_name,
            "prior": float(att.prior_mean[dim]),
            "posterior": float(att.posterior_mean[dim]),
            "shift": exp.shift,
            "unexplained": exp.unexplained,
        }
        for name, val in exp.contributions:
            row[f"contrib_{name}"] = val
        rows.append(row)
    return pd.DataFrame(rows)


def biggest_movers(traj: StateTrajectory, params: TwinParameters, dim: int = 0, k: int = 3):
    """The k weeks where this dimension moved most  -  where to look first."""
    scored = sorted(
        traj.attributions, key=lambda a: abs(float(a.total_shift[dim])), reverse=True
    )
    return [explain_week(a, params, dim=dim, student_id=traj.student_id) for a in scored[:k]]
