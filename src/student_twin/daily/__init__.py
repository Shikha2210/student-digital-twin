"""Daily student records: the raw layer.

This package holds everything about a day a student actually lived, and
nothing about the model. That separation is the point of it existing as a
package rather than as three helper functions in the API.

Three modules, in dependency order:

    vocab      the closed vocabularies - activity categories, observation
               metrics and their ranges, reflection prompts, sources. The
               same lists the SQL CHECK constraints in migration 003 use.
    calendar   date -> (week_index, day_of_week) and back. Pure arithmetic
               on dates; the only place week numbering is decided.
    aggregate  raw days -> DERIVED weekly summaries. Pure functions over
               plain dicts, so they are testable without a database.

**Nothing here imports the model, an adapter, or the store**, and nothing
here produces a model quantity. `aggregate` is the boundary at which a
future model integration would attach; the reason it has not attached yet
is written down in `aggregate.py` and in docs/DAILY_RECORDS.md rather
than left for a reader to infer.
"""

from __future__ import annotations

from .aggregate import WeekRollup, rollup_weeks
from .calendar import (
    day_of_week,
    iso_date,
    monday_of,
    week_bounds,
    week_index,
)
from .vocab import (
    ACTIVITY_CATEGORIES,
    ACTIVITY_STATUSES,
    METRIC_RANGES,
    REFLECTION_PROMPTS,
    SOURCES,
    DailyValueError,
    check_metric,
)

__all__ = [
    "ACTIVITY_CATEGORIES",
    "ACTIVITY_STATUSES",
    "METRIC_RANGES",
    "REFLECTION_PROMPTS",
    "SOURCES",
    "DailyValueError",
    "WeekRollup",
    "check_metric",
    "day_of_week",
    "iso_date",
    "monday_of",
    "rollup_weeks",
    "week_bounds",
    "week_index",
]
