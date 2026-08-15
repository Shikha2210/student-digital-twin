"""Persistence layer.

The research pipeline is stateless: it reads an adapter, fits, filters, and
returns a `PipelineResult` in memory. That is the right shape for research and
the wrong shape for a product, because every page load would refit the model.

This package is the boundary between the two. It stores what a run produced so
the API can serve it in milliseconds, and it stores enough provenance that any
stored number can be traced back to the run, seed, model version and code
revision that produced it.

Rules this layer enforces:

- Nothing is written without a `run_id`. An orphan number has no provenance and
  is therefore not a result.
- The database NEVER recomputes model quantities. If a value is not in a
  `PipelineResult` it is not in the database either.
- `synthetic` travels with the run, not with the reader's memory.
"""

from .db import Database, connect, transaction
from .migrate import MIGRATIONS_DIR, applied_migrations, migrate

__all__ = [
    "Database",
    "connect",
    "transaction",
    "migrate",
    "applied_migrations",
    "MIGRATIONS_DIR",
]
