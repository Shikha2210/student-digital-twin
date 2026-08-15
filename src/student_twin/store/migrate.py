"""Forward-only SQL migrations.

The whole mechanism is: numbered `.sql` files, applied in order, each
recorded in `schema_migrations` so it runs exactly once. No downgrade
path, because a downgrade that drops a table containing model results
destroys provenance, and "restore from a copy of the file" is both
simpler and safer for a single-file database.

Usage:
    python -m student_twin.store.migrate --db data/studytwin.db
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .db import connect

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_LEDGER = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     TEXT PRIMARY KEY,
    applied_at  TEXT NOT NULL,
    checksum    TEXT NOT NULL
)
"""


def _discover() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"), key=lambda p: p.name)


def applied_migrations(conn: sqlite3.Connection) -> dict[str, str]:
    conn.execute(_LEDGER)
    return {r["version"]: r["checksum"] for r in conn.execute(
        "SELECT version, checksum FROM schema_migrations")}


def migrate(db_path: str | Path, *, verbose: bool = False) -> list[str]:
    """Apply every pending migration. Returns the versions applied."""
    conn = connect(db_path)
    try:
        done = applied_migrations(conn)
        applied: list[str] = []
        for path in _discover():
            version = path.stem
            sql = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()[:16]

            if version in done:
                # A changed checksum means somebody edited a migration that has
                # already run somewhere. Silently ignoring that is how two
                # environments end up with different schemas and nobody knows.
                if done[version] != checksum:
                    raise RuntimeError(
                        f"migration {version} has already been applied but its "
                        f"contents changed (stored {done[version]}, now {checksum}). "
                        "Add a new migration instead of editing an applied one."
                    )
                continue

            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at, checksum) VALUES (?,?,?)",
                (version, datetime.now(UTC).isoformat(timespec="seconds"), checksum),
            )
            conn.commit()
            applied.append(version)
            if verbose:
                print(f"applied {version}")
        return applied
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Apply StudyTwin database migrations.")
    ap.add_argument("--db", default=None, help="path to the SQLite file")
    args = ap.parse_args()
    from ..api.settings import get_settings

    db = args.db or get_settings().database_path
    applied = migrate(db, verbose=True)
    print(f"{len(applied)} migration(s) applied to {db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
