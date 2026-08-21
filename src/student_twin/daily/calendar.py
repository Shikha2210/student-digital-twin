"""Week numbering. The only place a date becomes a week.

One rule, applied everywhere: **a study week runs Monday to Sunday, and
week 1 is the week containing the profile's `term_start`.** That is why
`monday_of(term_start)` rather than `term_start` itself is the origin -
otherwise a term starting on a Wednesday would put that Wednesday's
Monday and Tuesday in "week 0", and there is no week 0.

Nothing here is model code and nothing here is configurable. A second
week-numbering convention living anywhere else in the codebase is a bug:
the API, the repository and the frontend all read weeks through these
functions or through values the repository derived with them.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

#: Days in a study week. Not a setting. A "week" that is not seven days
#: would silently change what every stored `week_index` means, and the
#: stored values would not be recomputed.
DAYS_PER_WEEK = 7


class DateFormatError(ValueError):
    """A date string is not an ISO-8601 calendar date."""


def parse_date(value: str | date) -> date:
    """Accept `date` or `'YYYY-MM-DD'`. Reject everything else loudly."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise DateFormatError(
            f"{value!r} is not an ISO-8601 date (expected YYYY-MM-DD)"
        ) from exc


def iso_date(value: str | date) -> str:
    """Normalise to `'YYYY-MM-DD'`, the form stored in `day_records.date`."""
    return parse_date(value).isoformat()


def monday_of(value: str | date) -> date:
    """The Monday of the week containing `value`."""
    d = parse_date(value)
    return d - timedelta(days=d.weekday())


def day_of_week(value: str | date) -> int:
    """ISO day number: 1 = Monday ... 7 = Sunday.

    ISO rather than the American Sunday-first convention because the week
    view reads Monday to Sunday and because `date.isoweekday()` already
    is this, so there is no conversion to get wrong.
    """
    return parse_date(value).isoweekday()


def week_index(value: str | date, term_start: str | date) -> int:
    """Which study week `value` falls in. 1-based.

    Dates before the term's first Monday give a number below 1. The
    caller decides what to do about that - the API rejects it with a 422
    rather than silently filing a date in week 1, because a day recorded
    against the wrong week is worse than a day refused.
    """
    origin = monday_of(term_start)
    delta = (parse_date(value) - origin).days
    return delta // DAYS_PER_WEEK + 1


def week_bounds(week: int, term_start: str | date) -> tuple[str, str]:
    """Inclusive `(monday, sunday)` ISO dates for a study week.

    Returned as strings because every consumer either puts them in a SQL
    BETWEEN or renders them, and both want the stored representation.
    """
    if week < 1:
        raise ValueError(f"week must be 1 or greater, got {week}")
    start = monday_of(term_start) + timedelta(days=(week - 1) * DAYS_PER_WEEK)
    return start.isoformat(), (start + timedelta(days=DAYS_PER_WEEK - 1)).isoformat()


def week_dates(week: int, term_start: str | date) -> list[str]:
    """The seven ISO dates of a study week, Monday first.

    The week view renders seven slots whether or not rows exist for them,
    so it needs the dates themselves and not only the bounds. A slot with
    no row is rendered as "no data", never as an empty set of values.
    """
    start = monday_of(term_start) + timedelta(days=(week - 1) * DAYS_PER_WEEK)
    return [(start + timedelta(days=i)).isoformat() for i in range(DAYS_PER_WEEK)]


def default_term_start(dates: list[str]) -> str | None:
    """A term anchor derived from recorded days, when none was declared.

    The Monday of the earliest recorded day. Returns `None` for an empty
    history: a profile with no days has no observable anchor, and picking
    "today" would silently renumber every day the student later back-fills.
    """
    if not dates:
        return None
    return monday_of(min(dates)).isoformat()
