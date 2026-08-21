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
from datetime import date
from typing import Any

from ..daily import calendar as cal
from ..daily.aggregate import WeekRollup, rollup_week, rollup_weeks
from ..store.repository import Repository
from .schemas import (
    ActivityOut,
    AttributionComponent,
    AttributionStep,
    BaselineEstimate,
    CategoryTotalOut,
    CohortPoint,
    DailyTimeline,
    DayDetail,
    DaySlot,
    ForecastQuantiles,
    HazardPoint,
    MetricSummaryOut,
    OwnDistribution,
    Provenance,
    ScenarioForecast,
    StateSeries,
    StudentSummary,
    TimelineWeek,
    TwinPayload,
    WeekDetail,
    WeekObservations,
    WeekRollupOut,
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


# ================================================================
# DAILY RECORDS
# ----------------------------------------------------------------
# Assembly of the raw daily rows into the payloads the day, week and
# timeline screens read. Same rule as everything above: shaping only.
# The single piece of arithmetic here is delegated to
# `student_twin.daily.aggregate`, which is a pure function over plain
# dicts and is tested without a database or an HTTP client.
#
# The distinction this section exists to hold:
#
#     raw       rows the student wrote        -> DayDetail
#     derived   arithmetic over those rows    -> WeekRollupOut
#     model     nothing here                  -> model_input: false
#
# `model_input: false` is on every daily payload for the same reason
# it is on a profile: a client cannot render this data without also
# receiving the fact that no model consumes it.
# ================================================================

#: What "today" is, for rejecting days that have not happened. The
#: server's local date rather than UTC: a student in UTC+11 logging their
#: evening would otherwise be told their own day is in the future.
def _today() -> str:
    return date.today().isoformat()


WEEKDAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday",
                 "Friday", "Saturday", "Sunday")

#: Said on the timeline and on every day. Kept as one constant so the
#: sentence cannot drift between screens the way a re-typed caption does.
DAILY_MODEL_NOTE = (
    "RAW STUDENT-ENTERED DATA. Persisted, aggregated into weekly summaries and "
    "displayed. It is consumed by no model: the state filter reads weekly "
    "behavioural channels from a pipeline run, and no emission model has been "
    "fitted for self-reported daily scales. See docs/DAILY_RECORDS.md."
)


def _activity_out(row: dict[str, Any]) -> ActivityOut:
    return ActivityOut(
        activity_id=row["activity_id"], day_id=row["day_id"], seq=row["seq"],
        title=row["title"], category=row["category"], detail=row["detail"],
        subject=row["subject"], start_time=row["start_time"],
        end_time=row["end_time"], minutes=row["minutes"],
        importance=row["importance"], status=row["status"], source=row["source"],
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def day_detail(profile_id: str, row: dict[str, Any]) -> DayDetail:
    return DayDetail(
        day_id=row["day_id"], profile_id=profile_id, date=row["date"],
        week=row["week_index"], day_of_week=row["day_of_week"],
        source=row["source"], created_at=row["created_at"],
        updated_at=row["updated_at"],
        activities=[_activity_out(a) for a in row.get("activities", [])],
        observations=row.get("observations", {}),
        reflections=row.get("reflections", {}),
    )


def _rollup_out(r: WeekRollup) -> WeekRollupOut:
    return WeekRollupOut(
        week=r.week, start_date=r.start_date, end_date=r.end_date,
        days_recorded=r.days_recorded, days_with_content=r.days_with_content,
        n_activities=r.n_activities, minutes_logged=r.minutes_logged,
        activities_without_duration=r.activities_without_duration,
        n_reflections=r.n_reflections,
        by_category=[CategoryTotalOut(**c.as_dict()) for c in r.by_category],
        metrics=[MetricSummaryOut(**m.as_dict()) for m in r.metrics],
    )


def resolve_anchor(repo: Repository, profile_id: str) -> tuple[str, bool]:
    """`(term_start, declared)` for a profile that may have neither.

    Falls back to today's Monday only when the profile has no declared
    anchor AND no recorded days - the case where the student is about to
    write their first day and there is nothing to anchor against yet.
    The boolean travels with it so the UI can say the numbering is
    provisional rather than presenting an invented week 1 as settled.
    """
    declared = repo.term_start(profile_id)
    if declared:
        return cal.monday_of(declared).isoformat(), True
    effective = repo.effective_term_start(profile_id)
    if effective:
        return effective, False
    return cal.monday_of(_today()).isoformat(), False


def week_detail(repo: Repository, profile_id: str, week: int) -> WeekDetail:
    """One study week: seven slots, the days behind them, and the summary.

    Seven slots are always returned, whether or not rows exist. That is
    the point of the screen: a week is Monday to Sunday regardless of how
    much of it the student filled in, and a slot with no row renders as
    "no data" with an add action rather than as absent from the list.
    """
    anchor, declared = resolve_anchor(repo, profile_id)
    start, end = cal.week_bounds(week, anchor)
    rows = repo.days_for_week(profile_id, week)
    by_date = {r["date"]: r for r in rows}
    today = _today()

    slots: list[DaySlot] = []
    for iso in cal.week_dates(week, anchor):
        row = by_date.get(iso)
        dow = cal.day_of_week(iso)
        slots.append(DaySlot(
            date=iso, day_of_week=dow, weekday=WEEKDAY_NAMES[dow - 1],
            recorded=row is not None,
            day_id=row["day_id"] if row else None,
            n_activities=len(row["activities"]) if row else 0,
            n_metrics=len(row["observations"]) if row else 0,
            n_reflections=len(row["reflections"]) if row else 0,
            is_future=iso > today,
        ))

    return WeekDetail(
        profile_id=profile_id, week=week, start_date=start, end_date=end,
        term_start=anchor, term_start_declared=declared,
        slots=slots,
        days=[day_detail(profile_id, r) for r in rows],
        rollup=_rollup_out(rollup_week(rows, week, anchor)),
    )


def timeline(repo: Repository, profile_id: str) -> DailyTimeline:
    """Every study week this profile has, with the shape of its history.

    The span runs from week 1 to whichever is later: the last week that
    holds data, or the week containing today. Today is included so a
    student always has somewhere to put today's entry; nothing beyond it
    is manufactured.

    There is deliberately no constant in this function. A hard-coded
    twenty would make the timeline a fixed-length strip that happens to
    be mostly empty, which is a different claim from "this is how long
    the history is".
    """
    declared_raw = repo.term_start(profile_id)
    anchor, declared = resolve_anchor(repo, profile_id)
    counts = {int(c["week"]): c for c in repo.week_counts(profile_id)}
    today = _today()

    last_recorded = max(counts) if counts else 0
    current = cal.week_index(today, anchor)
    span = max(last_recorded, current if current >= 1 else 1, 1)

    weeks: list[TimelineWeek] = []
    for w in range(1, span + 1):
        start, end = cal.week_bounds(w, anchor)
        c = counts.get(w)
        weeks.append(TimelineWeek(
            week=w, start_date=start, end_date=end,
            days_recorded=int(c["days_recorded"]) if c else 0,
            n_activities=int(c["n_activities"] or 0) if c else 0,
            has_data=c is not None,
        ))

    # Rollups only for weeks that hold something. A rollup of an empty
    # week is a row of zeros, and a strip of those reads as measurement.
    all_days = repo.all_days(profile_id) if counts else []
    rollups = [_rollup_out(r) for r in rollup_weeks(all_days, anchor)]

    dates = [d["date"] for d in all_days]
    return DailyTimeline(
        profile_id=profile_id,
        term_start=cal.monday_of(declared_raw).isoformat() if declared_raw else (
            anchor if counts else None),
        term_start_declared=declared,
        n_weeks=len(weeks), weeks=weeks,
        days_recorded=len(all_days),
        first_date=min(dates) if dates else None,
        last_date=max(dates) if dates else None,
        today=today,
        rollups=rollups,
    )
