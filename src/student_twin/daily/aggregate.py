"""Days -> weeks. The DERIVED layer, and the boundary the model would attach to.

Everything in this module is a summary of rows a student typed. Nothing
in it is a model quantity, an estimate, or an inference, and the API
labels the result `derived` so a reader never has to guess which of the
three it is holding.

Two properties are load-bearing.

**A summary states its own coverage.** `minutes_logged` is the sum of the
durations that exist, and it travels with `activities_without_duration`.
Reporting "6h 30m this week" over a week where four of nine activities
carry no duration is a number that reads as a total and is not one.
Likewise every metric summary carries `n`: a mean of one day and a mean
of seven days are not the same claim.

**A metric nobody recorded is absent, not zero.** The rollup emits a key
only when at least one day in the week has a row for it, mirroring the
long-format storage. There is no default, so no consumer can render a
figure the student never entered.

------------------------------------------------------------------
WHY THIS DOES NOT FEED THE MODEL
------------------------------------------------------------------
The obvious next line - push these weekly aggregates into the state
filter - is not written, and the reason is specific rather than
cautious.

The filter's emission models are fitted per channel: negative-binomial
on behaviour counts, Bernoulli on submission, Gaussian-on-logit on
score. A weekly mean of a self-reported 1-5 mood scale has no fitted
loading, no dispersion parameter and no place in `TwinParameters`.
Feeding it in would require inventing all three, and an invented loading
is a fabricated result (CLAUDE.md non-negotiable 1).

The schema already names the correct route. `Channel.LIFESTYLE` /
`CanonicalType.ACTIVITY_LOG` and `Channel.SELF_REPORT` /
`CanonicalType.PERCEIVED_LOAD` exist precisely for this data and are
declared **unavailable** by every current adapter, which is what A-07
requires: "adding a survey instrument later is a new adapter, not a
schema migration". So the integration, when it is justified, is a new
adapter that reads these tables, declares those two types available, and
is refitted - not a shortcut from this function into `state/`.

Until that adapter exists and has been refitted, daily data is
**persisted, aggregated and displayed, and consumed by no model.** That
sentence is repeated in the API payload and in docs/DAILY_RECORDS.md
because it is the one claim about this feature that is easy to overstate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .calendar import week_bounds
from .vocab import ACTIVITY_CATEGORIES


@dataclass(frozen=True)
class MetricSummary:
    """One structured metric over one week. Descriptive, never inferred."""

    metric: str
    mean: float
    min: float
    max: float
    #: Days in the week that actually carry this metric. Travels with the
    #: mean so a one-day average cannot be read as a weekly figure.
    n: int

    def as_dict(self) -> dict[str, Any]:
        return {"metric": self.metric, "mean": self.mean, "min": self.min,
                "max": self.max, "n": self.n}


@dataclass(frozen=True)
class CategoryTotal:
    category: str
    n_activities: int
    minutes: int
    #: How many of `n_activities` contributed nothing to `minutes`.
    without_duration: int

    def as_dict(self) -> dict[str, Any]:
        return {"category": self.category, "n_activities": self.n_activities,
                "minutes": self.minutes, "without_duration": self.without_duration}


@dataclass(frozen=True)
class WeekRollup:
    """A derived weekly view over raw daily rows.

    `days_recorded` counts day rows that exist, which is not the same as
    days on which something was entered: a student can open a day and
    record nothing, and `days_with_content` is the count that excludes
    those.
    """

    week: int
    start_date: str
    end_date: str
    days_recorded: int
    days_with_content: int
    n_activities: int
    minutes_logged: int
    activities_without_duration: int
    n_reflections: int
    by_category: list[CategoryTotal] = field(default_factory=list)
    metrics: list[MetricSummary] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "week": self.week,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "days_recorded": self.days_recorded,
            "days_with_content": self.days_with_content,
            "n_activities": self.n_activities,
            "minutes_logged": self.minutes_logged,
            "activities_without_duration": self.activities_without_duration,
            "n_reflections": self.n_reflections,
            "by_category": [c.as_dict() for c in self.by_category],
            "metrics": [m.as_dict() for m in self.metrics],
        }


def _summarise_metrics(values: dict[str, list[float]]) -> list[MetricSummary]:
    return [
        MetricSummary(metric=m, mean=sum(v) / len(v), min=min(v), max=max(v), n=len(v))
        for m, v in values.items()
        if v
    ]


def rollup_week(days: Iterable[dict[str, Any]], week: int,
                term_start: str) -> WeekRollup:
    """Summarise the days belonging to one study week.

    `days` are day payloads as the repository returns them: each a dict
    with `activities` (list), `observations` (metric -> value) and
    `reflections` (prompt -> body). Days from other weeks are ignored
    rather than rejected, so a caller may pass a whole history.
    """
    start, end = week_bounds(week, term_start)
    mine = [d for d in days if int(d.get("week_index", 0)) == week]

    n_act = 0
    minutes = 0
    no_duration = 0
    n_refl = 0
    with_content = 0
    per_cat: dict[str, list[int]] = {}
    metric_values: dict[str, list[float]] = {}

    for d in mine:
        acts = d.get("activities") or []
        obs = d.get("observations") or {}
        refl = d.get("reflections") or {}
        if acts or obs or refl:
            with_content += 1
        n_refl += len(refl)
        for metric, value in obs.items():
            metric_values.setdefault(metric, []).append(float(value))
        for a in acts:
            n_act += 1
            cat = str(a.get("category") or "other")
            mins = a.get("minutes")
            bucket = per_cat.setdefault(cat, [0, 0, 0])   # [n, minutes, no_duration]
            bucket[0] += 1
            if mins is None:
                no_duration += 1
                bucket[2] += 1
            else:
                minutes += int(mins)
                bucket[1] += int(mins)

    # Emit categories in the vocabulary's display order, and only the ones
    # that occurred. A zero row for every unused category would put nine
    # zeros in a week where the student logged one lecture.
    by_cat = [
        CategoryTotal(category=c, n_activities=per_cat[c][0],
                      minutes=per_cat[c][1], without_duration=per_cat[c][2])
        for c in ACTIVITY_CATEGORIES
        if c in per_cat
    ]
    by_cat += [
        CategoryTotal(category=c, n_activities=v[0], minutes=v[1], without_duration=v[2])
        for c, v in sorted(per_cat.items())
        if c not in ACTIVITY_CATEGORIES
    ]

    return WeekRollup(
        week=week, start_date=start, end_date=end,
        days_recorded=len(mine), days_with_content=with_content,
        n_activities=n_act, minutes_logged=minutes,
        activities_without_duration=no_duration, n_reflections=n_refl,
        by_category=by_cat,
        metrics=_summarise_metrics(metric_values),
    )


def rollup_weeks(days: Iterable[dict[str, Any]], term_start: str,
                 weeks: Iterable[int] | None = None) -> list[WeekRollup]:
    """Summarise every week that has at least one day, or a given set.

    With `weeks=None` the returned list covers only weeks the student has
    rows in. It does **not** pad out to twenty, or to today, or to any
    other fixed horizon: how many weeks exist is a property of the data,
    and a run of empty weeks manufactured to fill a strip is fabricated
    structure even when every value inside it is blank.
    """
    materialised = list(days)
    if weeks is None:
        present = sorted({int(d["week_index"]) for d in materialised})
    else:
        present = sorted(set(int(w) for w in weeks))
    return [rollup_week(materialised, w, term_start) for w in present]
