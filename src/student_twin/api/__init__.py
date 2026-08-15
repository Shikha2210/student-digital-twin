"""HTTP API over stored pipeline results.

    uvicorn student_twin.api.app:app --reload
    open http://127.0.0.1:8000/api/docs

This package reads. It never fits, filters or simulates: those live in
`state/`, `simulation/` and `pipeline.py`, and their output is written to
the database by `store/ingest.py`. If a value is not in a stored run, the
API returns 404 rather than computing something plausible.
"""

from .settings import Settings, get_settings

__all__ = ["Settings", "get_settings"]
