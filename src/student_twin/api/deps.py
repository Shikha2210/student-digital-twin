"""Request-scoped dependencies.

One SQLite connection per request, closed on the way out. SQLite handles
this cheaply (opening a connection is a file handle, not a network round
trip) and it keeps every request isolated, which matters because WAL lets
a long ingest write while the API reads.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Query

from ..store.db import Database
from ..store.repository import Repository
from .settings import Settings, get_settings


def get_db() -> Iterator[Database]:
    settings = get_settings()
    db = Database(settings.database_path, read_only=False)
    try:
        yield db
    finally:
        db.close()


def get_repo(db: Database = Depends(get_db)) -> Repository:
    return Repository(db)


def resolve_run(
    run_id: str | None = Query(
        default=None,
        description="Model run to read. Omit for the most recent run.",
    ),
    repo: Repository = Depends(get_repo),
) -> str:
    """Resolve an explicit run_id, or fall back to the latest.

    Falling back rather than 400-ing keeps the common case ("show me the
    current twin") a single URL, while every response still names the run it
    used so nothing is ambiguous after the fact.
    """
    resolved = run_id or repo.latest_run_id()
    if not resolved:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "no_model_run",
                "detail": "The database contains no model run.",
                "hint": "Run: python scripts/ingest_run.py --students 250 --weeks 20",
            },
        )
    if repo.run(resolved) is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "run_not_found", "detail": f"run {resolved!r} does not exist"},
        )
    return resolved


def get_settings_dep() -> Settings:
    return get_settings()
