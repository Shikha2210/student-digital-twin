"""FastAPI application.

    uvicorn student_twin.api.app:app --reload

Serves the JSON API under /api and, optionally, the static frontend at /
so the whole product runs from one process. Interactive documentation is
at /api/docs, which for a project that has to be explained to a panel is
worth more than any hand-written endpoint list.

On the dependency decision: docs/architecture.md rejected FastAPI on the
grounds that "the api/ package is an empty placeholder. Nothing consumes
an HTTP API yet." That condition no longer holds - the frontend consumes
one - so the rejection is reversed here and the reversal is recorded in
that document rather than left for a reader to discover.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__ as MODEL_VERSION
from ..store.migrate import migrate
from .routes import router
from .settings import get_settings

log = logging.getLogger("studytwin.api")

DESCRIPTION = """
Read API for the StudyTwin research prototype.

**Every number this API returns was produced by a pipeline run and stored with
its provenance.** Nothing is computed at request time; the API does not contain
a second implementation of the model.

Read the `provenance` block on any payload before reading the payload:

* `synthetic: true` means no real student is described. Every current run is
  synthetic - the model has never been executed against real OULAD data.
* Latent state is **inferred**, not measured. It is not a student's knowledge
  or motivation; the construct-validity test (T4) has never run.
* Anything under `scenarios` is **model-generated and not a causal estimate**.
  No intervention exists in the data, so the sensitivity is assumed.
* The weekly replay is **retrospective**. Nothing here is real-time.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    # Migrating on boot means a fresh clone works after one command. It is
    # forward-only and idempotent, so this is safe to run every start.
    applied = migrate(settings.database_path)
    if applied:
        log.info("applied %d migration(s): %s", len(applied), ", ".join(applied))
    log.info("database: %s", settings.database_path)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="StudyTwin API",
        version=MODEL_VERSION,
        description=DESCRIPTION,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # Explicit origins, never "*". The API is read-only for model data but
    # POST /api/profiles accepts a name, and a wildcard origin on a route
    # that stores anything about a person is careless even locally.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        # A stack trace in the browser is a security problem and a bad user
        # experience. Log it; return something a frontend can render.
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error",
                     "detail": "The server failed to handle this request.",
                     "hint": "Check the server log; the frontend is not at fault."},
        )

    app.include_router(router)

    if settings.serve_web:
        web = Path(settings.web_dir)
        if web.is_dir():
            @app.get("/", include_in_schema=False)
            async def index() -> FileResponse:
                return FileResponse(web / "index.html")

            # Mounted last so /api always wins the path match.
            app.mount("/", StaticFiles(directory=str(web), html=True), name="web")
        else:
            log.warning("web dir %s does not exist; serving API only", web)

    return app


app = create_app()
