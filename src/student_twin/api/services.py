"""Assembly of API payloads from stored rows.

The routes are thin on purpose: they parse a request, call one function
here, and serialise the result. All the shaping - long rows into series,
scenarios into branches - happens in this module, where it can be tested
without an HTTP client.

Nothing here estimates anything. `own_distribution` summarises stored
states with a mean and a standard deviation, which is arithmetic over
values the model already produced, and the response says so.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..store.repository import Repository
from .schemas import (
    AttributionComponent,
    AttributionStep,
    BaselineEstimate,
    CohortPoint,
    ForecastQuantiles,
    HazardPoint,
    OwnDistribution,
    Provenance,
    ScenarioForecast,
    StateSeries,
    StudentSummary,
    TwinPayload,
    WeekObservations,
)

SIM_DISCLAIMER = (
    "MODEL-GENERATED SCENARIO. NOT A CAUSAL ESTIMATE. The dataset records no "
    "interventions, so the sensitivity of the state to a support action is "
    "ASSUMED, not fitted. These trajectories show what the model's assumed "
    "transition dynamics imply, never what an action would achieve for a real "
    "student."
)


class NotFound(Exception):
    """Requested resource does not exist. Raised, never papered over."""


def provenance_of(repo: Repository, run_id: str) -> Provenance:
    run = repo.run(run_id)
    if not run:
        raise NotFound(f"run {run_id!r} does not exist")
    note = (
        "SYNTHETIC DATA. Generated from a known latent process. Nothing here "
        "describes a real student, and no figure may be reported as a result "
        "about OULAD or any other real cohort."
        if run["synthetic"] else
        f"Real dataset run: {run['dataset']}. Forward-chained evaluation."
    )
    return Provenance(
        run_id=run["run_id"], dataset=run["dataset"], synthetic=run["synthetic"],
        seed=run["seed"], model_version=run["model_version"],
        code_revision=run["code_revision"], inference_method=run["inference_method"],
        created_at=run["created_at"], note=note,
    )


def _series(rows: list[dict[str, Any]], order: list[str] | None = None) -> list[StateSeries]:
    by_dim: dict[str, dict[str, list]] = defaultdict(
        lambda: {"t": [], "mean": [], "sd": [], "method": []})
    for r in rows:
        b = by_dim[r["dim_name"]]
        b["t"].append(r["t"])
        b["mean"].append(r["mean"])
        b["sd"].append(r["sd"])
        b["method"].append(r["method"])
    # Emit in the model's dimension order, not SQLite's. Alphabetical ordering
    # put `capability` first and every consumer that took series[0] as the
    # primary dimension plotted the wrong one.
    names = [d for d in (order or []) if d in by_dim] +             [d for d in by_dim if not order or d not in order]
    return [
        StateSeries(dim_name=d, t=by_dim[d]["t"], mean=by_dim[d]["mean"],
                    sd=by_dim[d]["sd"],
                    method=by_dim[d]["method"][0] if by_dim[d]["method"] else "unknown")
        for d in names
    ]


def _own_distribution(series: list[StateSeries],
                      baseline: list[BaselineEstimate]) -> list[OwnDistribution]:
    theta_of = {b.dim_name: b.theta for b in baseline}
    out: list[OwnDistribution] = []
    for s in series:
        theta = theta_of.get(s.dim_name)
        if theta is None or not s.mean:
            continue
        n = len(s.mean)
        mu = sum(s.mean) / n
        var = sum((x - mu) ** 2 for x in s.mean) / n
        below = [x < theta for x in s.mean]
        longest = run = 0
        for b in below:
            run = run + 1 if b else 0
            longest = max(longest, run)
        current = 0
        for b in reversed(below):
            if not b:
                break
            current += 1
        out.append(OwnDistribution(
            dim_name=s.dim_name, mean=mu, sd=var ** 0.5, n=n,
            weeks_below_theta=sum(below), longest_run_below=longest,
            current_run_below=current,
        ))
    return out


def _observations(obs_rows: list[dict], feat_rows: list[dict]) -> list[WeekObservations]:
    ch: dict[int, dict[str, float]] = defaultdict(dict)
    for r in obs_rows:
        ch[r["t"]][r["channel"]] = r["value"]
    ft: dict[int, dict[str, float]] = defaultdict(dict)
    for r in feat_rows:
        ft[r["t"]][r["feature"]] = r["value"]
    weeks = sorted(set(ch) | set(ft))
    return [WeekObservations(t=t, channels=ch.get(t, {}), features=ft.get(t, {}))
            for t in weeks]


def _attribution(rows: list[dict], dim_name: str) -> list[AttributionStep]:
    return [
        AttributionStep(
            t=r["t"], dim_name=dim_name,
            prior_mean=r["prior_mean"], prior_sd=r.get("prior_sd"),
            posterior_mean=r["posterior_mean"], posterior_sd=r.get("posterior_sd"),
            shift=r["shift"], residual=r["residual"],
            components=[AttributionComponent(**c) for c in r.get("components", [])],
        )
        for r in rows
    ]


def scenario_forecasts(repo: Repository, run_id: str, student_id: str,
                       primary_dim: str) -> list[ScenarioForecast]:
    out: list[ScenarioForecast] = []
    for sc in repo.scenarios(run_id):
        f = repo.forecast(sc["scenario_id"], student_id)
        if not f["quantiles"]:
            continue
        by_dim: dict[str, dict[str, list]] = defaultdict(
            lambda: {"h": [], "t": [], "q05": [], "q50": [], "q95": [], "mean": []})
        for r in f["quantiles"]:
            b = by_dim[r["dim_name"]]
            for k in ("h", "t", "q05", "q50", "q95", "mean"):
                b[k].append(r[k])
        quantiles = [ForecastQuantiles(dim_name=d, **v) for d, v in by_dim.items()]

        paths: dict[int, list[float]] = defaultdict(list)
        for r in f["paths"]:
            if r["dim_name"] == primary_dim:
                paths[r["particle_ix"]].append(r["value"])

        out.append(ScenarioForecast(
            scenario_id=sc["scenario_id"], label=sc["label"],
            interventions=sc["interventions"], is_counterfactual=sc["is_counterfactual"],
            horizon=sc["horizon"], n_particles=sc["n_particles"],
            quantiles=quantiles,
            cum_risk=[r["cum_risk"] for r in f["risk"]],
            paths=[paths[k] for k in sorted(paths)],
            disclaimer=SIM_DISCLAIMER,
        ))
    return out


def twin_payload(repo: Repository, run_id: str, student_id: str) -> TwinPayload:
    """The composite the dashboard boots from."""
    student = repo.student(run_id, student_id)
    if not student:
        raise NotFound(f"student {student_id!r} is not in run {run_id!r}")
    run = repo.run(run_id)
    dim_names: list[str] = run["dim_names"]
    primary = dim_names[0]

    series = _series(repo.states(run_id, student_id), dim_names)
    order = {d: i for i, d in enumerate(dim_names)}
    baseline = sorted((BaselineEstimate(**b) for b in repo.baseline(run_id, student_id)),
                      key=lambda b: order.get(b.dim_name, 99))

    return TwinPayload(
        provenance=provenance_of(repo, run_id),
        student=StudentSummary(**student),
        dim_names=dim_names,
        state=series,
        baseline=baseline,
        hazard=[HazardPoint(**h) for h in repo.hazards(run_id, student_id)],
        observations=_observations(repo.observations(run_id, student_id),
                                   repo.features(run_id, student_id)),
        attribution=_attribution(repo.attribution(run_id, student_id, primary), primary),
        scenarios=scenario_forecasts(repo, run_id, student_id, primary),
        own_distribution=_own_distribution(series, baseline),
        cohort_theta=[c["theta"] for c in repo.cohort_summary(run_id)
                      if c["theta"] is not None],
    )


def cohort_points(repo: Repository, run_id: str, limit: int = 400) -> list[CohortPoint]:
    return [
        CohortPoint(student_id=r["student_id"], mean_state=r["mean_state"],
                    theta=r["theta"], last_state=r["last_state"])
        for r in repo.cohort_summary(run_id, limit)
        if r["mean_state"] is not None and r["theta"] is not None
        and r["last_state"] is not None
    ]


def contrast_pair(repo: Repository, run_id: str):
    """Pick two students at opposite ends of the fitted set-point distribution.

    Both must have a full history: a student who withdrew at week 6 cannot
    carry a "same observation, different meaning" comparison, because there is
    not enough of their own normal to compare against.
    """
    from .schemas import ContrastPair, ContrastStudent

    run = repo.run(run_id)
    dim = run["dim_names"][0]
    pts = [c for c in repo.cohort_summary(run_id, limit=2000) if c["theta"] is not None]
    if len(pts) < 2:
        raise NotFound("not enough students with fitted set points to form a pair")
    full = [c for c in pts
            if (repo.student(run_id, c["student_id"]) or {}).get("n_weeks", 0)
            >= 0.75 * max(s["n_weeks"] for s in repo.list_students(run_id, limit=500))]
    pool = full if len(full) >= 2 else pts
    pool.sort(key=lambda c: c["theta"])
    lo, hi = pool[max(len(pool) // 12, 0)], pool[-max(len(pool) // 12, 1)]

    def one(rec) -> ContrastStudent:
        rows = [r for r in repo.states(run_id, rec["student_id"]) if r["dim_name"] == dim]
        return ContrastStudent(
            student_id=rec["student_id"], theta=rec["theta"], dim_name=dim,
            t=[r["t"] for r in rows], mean=[r["mean"] for r in rows],
            sd=[r["sd"] for r in rows])

    return ContrastPair(provenance=provenance_of(repo, run_id), high=one(hi), low=one(lo))


#: Capability tests that have no implementation. Listed explicitly so the API
#: can report "never ran" rather than letting an empty row read as a pass.
NEVER_RUN = [
    "T3 (intervention stability) - NOT IMPLEMENTED. Requires refitting across "
    "seeds and checking sign and magnitude stability of the intervention response.",
    "T4 (identifiability / construct validity) - NOT IMPLEMENTED. Until it runs, "
    "the dimension names are labels of convenience, not validated constructs.",
]
