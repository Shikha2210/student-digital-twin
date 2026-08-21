"""Closed vocabularies for daily records.

Every list here is duplicated as a SQL CHECK constraint in migration
`003_daily_records.sql`. The duplication is deliberate and follows the
precedent already set by `model_runs.n_dims`: a constraint that only
Python enforces is a constraint a stray script can route around by
opening the database file directly.

Why closed vocabularies at all. A free-text `category` becomes forty
spellings of "studying" inside a week, and every aggregate over it then
means nothing. The cost is that adding a category is a migration; that
cost is correct, because adding one changes what a weekly summary counts.

Source files in this project are ASCII (see CLAUDE.md), so the human
labels here avoid typographic punctuation.
"""

from __future__ import annotations


class DailyValueError(ValueError):
    """A daily record violates a vocabulary or a range.

    Raised at the boundary rather than coerced. A value silently clamped
    into range is a value the student did not enter.
    """


#: What a student was doing. Ordered for display, not alphabetically:
#: the teaching-and-work categories first, then the rest of a life.
ACTIVITY_CATEGORIES: tuple[str, ...] = (
    "class",
    "study",
    "assignment",
    "project",
    "exam",
    "quiz",
    "extracurricular",
    "meeting",
    "personal",
    "other",
)

#: Human labels for the categories above. The frontend reads these from
#: the API rather than hard-coding its own copy, so a category cannot be
#: renamed in one place and not the other.
CATEGORY_LABELS: dict[str, str] = {
    "class": "Class or lecture",
    "study": "Studying",
    "assignment": "Assignment",
    "project": "Project",
    "exam": "Exam",
    "quiz": "Quiz or test",
    "extracurricular": "Extracurricular",
    "meeting": "Meeting",
    "personal": "Personal",
    "other": "Other",
}

#: Where a piece of work stands. Optional - most activities are not work
#: with a completion state, and `None` says so rather than defaulting to
#: "pending" and inventing an obligation the student never recorded.
ACTIVITY_STATUSES: tuple[str, ...] = ("done", "partial", "pending", "missed")

STATUS_LABELS: dict[str, str] = {
    "done": "Completed",
    "partial": "Partly done",
    "pending": "Still pending",
    "missed": "Missed",
}

#: Structured daily state. `(low, high)` inclusive.
#:
#: Eight of the nine are 1-5 Likert scales because that is what a person
#: can answer about a day without instrumentation. `sleep_hours` is a
#: duration and is on its own scale; conflating the two - "rate your
#: sleep 1-5" standing in for hours - would lose the only quantity here
#: with a real unit.
#:
#: A metric a student did not record has NO ROW. There is deliberately no
#: default and no sentinel: `0` is a legitimate value for sleep_hours and
#: could not double as "unknown" even if we wanted it to.
METRIC_RANGES: dict[str, tuple[float, float]] = {
    "mood": (1.0, 5.0),
    "stress": (1.0, 5.0),
    "focus": (1.0, 5.0),
    "motivation": (1.0, 5.0),
    "energy": (1.0, 5.0),
    "workload": (1.0, 5.0),
    "productivity": (1.0, 5.0),
    "sleep_quality": (1.0, 5.0),
    "sleep_hours": (0.0, 24.0),
}

#: Display order and labels. Sleep last because it describes the night
#: before rather than the day itself.
METRIC_ORDER: tuple[str, ...] = (
    "mood",
    "energy",
    "focus",
    "motivation",
    "stress",
    "workload",
    "productivity",
    "sleep_hours",
    "sleep_quality",
)

METRIC_LABELS: dict[str, str] = {
    "mood": "Mood",
    "energy": "Energy",
    "focus": "Focus",
    "motivation": "Motivation",
    "stress": "Stress",
    "workload": "Workload",
    "productivity": "Productivity",
    "sleep_hours": "Sleep",
    "sleep_quality": "Sleep quality",
}

#: Unit shown beside a value. Empty string where the scale is the unit.
METRIC_UNITS: dict[str, str] = {m: ("h" if m == "sleep_hours" else "/5")
                                 for m in METRIC_RANGES}

#: The reflection prompts, in the order the day view asks them.
REFLECTION_PROMPTS: tuple[str, ...] = (
    "difficult",
    "learned",
    "went_well",
    "went_badly",
    "events",
    "notes",
)

PROMPT_LABELS: dict[str, str] = {
    "difficult": "What did you find difficult?",
    "learned": "What did you learn?",
    "went_well": "What went well?",
    "went_badly": "What did not go well?",
    "events": "Important events",
    "notes": "Additional notes",
}

#: Provenance of a row. Only `student` has a writer today; the other
#: three exist so that a future importer has somewhere honest to declare
#: itself instead of masquerading as a person typing. Nothing in the
#: codebase branches on them yet, and the API does not accept anything
#: but `student` from a browser.
SOURCES: tuple[str, ...] = ("student", "system", "import", "other")

#: The longest free-text body accepted. Not a database constraint - it is
#: a request-size guard, and the database has no opinion about prose.
MAX_REFLECTION_CHARS = 4000
MAX_TITLE_CHARS = 200
MAX_DETAIL_CHARS = 2000


def check_metric(metric: str, value: float) -> float:
    """Validate one observation. Returns the value; never coerces it.

    Raises `DailyValueError` for an unknown metric or an out-of-range
    value, because both mean the caller believes something about the
    vocabulary that is not true, and quietly clamping would hide it.
    """
    rng = METRIC_RANGES.get(metric)
    if rng is None:
        raise DailyValueError(
            f"unknown daily metric {metric!r}. Known metrics: "
            f"{', '.join(sorted(METRIC_RANGES))}"
        )
    lo, hi = rng
    v = float(value)
    if not (lo <= v <= hi):
        raise DailyValueError(
            f"{metric} must be between {lo:g} and {hi:g}, got {v:g}"
        )
    return v


def check_category(category: str) -> str:
    if category not in ACTIVITY_CATEGORIES:
        raise DailyValueError(
            f"unknown activity category {category!r}. Known categories: "
            f"{', '.join(ACTIVITY_CATEGORIES)}"
        )
    return category


def check_prompt(prompt: str) -> str:
    if prompt not in REFLECTION_PROMPTS:
        raise DailyValueError(
            f"unknown reflection prompt {prompt!r}. Known prompts: "
            f"{', '.join(REFLECTION_PROMPTS)}"
        )
    return prompt


def vocabulary() -> dict[str, object]:
    """The whole vocabulary, in one serialisable structure.

    Served by `GET /api/daily/vocabulary` so the frontend renders the
    same categories, metrics, ranges and labels the database enforces.
    A form whose options are typed out again in JavaScript drifts from
    the CHECK constraint the first time either changes.
    """
    return {
        "activity_categories": [
            {"value": c, "label": CATEGORY_LABELS[c]} for c in ACTIVITY_CATEGORIES
        ],
        "activity_statuses": [
            {"value": s, "label": STATUS_LABELS[s]} for s in ACTIVITY_STATUSES
        ],
        "metrics": [
            {
                "value": m,
                "label": METRIC_LABELS[m],
                "min": METRIC_RANGES[m][0],
                "max": METRIC_RANGES[m][1],
                "unit": METRIC_UNITS[m],
                "step": 0.5 if m == "sleep_hours" else 1.0,
            }
            for m in METRIC_ORDER
        ],
        "reflection_prompts": [
            {"value": p, "label": PROMPT_LABELS[p]} for p in REFLECTION_PROMPTS
        ],
        "sources": list(SOURCES),
    }
