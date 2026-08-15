"""SQLite connection management.

Deliberately no ORM. Three reasons, in order of weight:

1. The schema is the documentation. A capstone team reading
   `001_initial.sql` learns the data model; reading a declarative-base
   class hierarchy teaches them SQLAlchemy.
2. Every query in this project is a straightforward select over a
   composite key. An ORM's value is relationship management we do not
   need, and its cost is a dependency plus an abstraction that hides
   exactly the SQL a reviewer wants to check.
3. `sqlite3` is stdlib, so the persistence layer adds zero packages to
   an install list that has been kept deliberately short.

Every value that reaches SQL does so as a bound parameter. There is no
string interpolation of user input anywhere in this package; the only
interpolated fragments are column lists built from module-level
constants.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def _row_factory(cursor: sqlite3.Cursor, row: tuple) -> dict[str, Any]:
    """Return dicts rather than tuples, so callers never index by position."""
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}


def connect(path: str | Path, *, read_only: bool = False) -> sqlite3.Connection:
    """Open a connection with the pragmas this project depends on.

    `foreign_keys` is OFF by default in SQLite, which quietly turns every
    ON DELETE CASCADE in the schema into a no-op. Turning it on per
    connection is not optional here: the provenance guarantee that
    deleting a run removes its numbers is enforced by those cascades.
    """
    p = Path(path)
    if str(p) != ":memory:":
        p.parent.mkdir(parents=True, exist_ok=True)
    uri = False
    target = str(p)
    if read_only and str(p) != ":memory:":
        target = f"file:{p}?mode=ro"
        uri = True
    conn = sqlite3.connect(target, uri=uri, check_same_thread=False)
    conn.row_factory = _row_factory
    conn.execute("PRAGMA foreign_keys = ON")
    if not read_only:
        # WAL lets the API read while an ingest writes. Without it a long
        # ingest blocks every request on the same file.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """All-or-nothing write.

    A partially ingested run is worse than no run at all: it looks like a
    result and is not one. Any exception rolls the whole thing back.
    """
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


class Database:
    """Thin handle. Holds a connection and the query helpers built on it."""

    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        self.path = str(path)
        self.conn = connect(path, read_only=read_only)

    # -- reads -----------------------------------------------------------

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        return list(self.conn.execute(sql, params))

    def one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        rows = self.conn.execute(sql, params).fetchmany(1)
        return rows[0] if rows else None

    def scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        row = self.one(sql, params)
        if row is None:
            return None
        return next(iter(row.values()))

    # -- writes ----------------------------------------------------------

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def executemany(self, sql: str, rows: Sequence[Sequence[Any]]) -> None:
        if rows:
            self.conn.executemany(sql, rows)

    def close(self) -> None:
        try:
            self.conn.close()
        except sqlite3.Error:
            pass

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
