"""Configuration from the environment.

No secret, path or origin is hard-coded. Everything here reads an
environment variable with a development-safe default, so the same code
runs on a laptop and behind a reverse proxy without edits.

There is deliberately no secret in this file to leak: the API has no
authentication because it serves one thing - results from a synthetic
research run - and inventing an auth system for that would be security
theatre. The boundary that DOES matter (profiles, which can contain a
real name) is documented in docs/API_SPEC.md under "Security".
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(name)
    if not raw:
        return default
    return [x.strip() for x in raw.split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
    """Resolved runtime configuration."""

    database_path: str = field(
        default_factory=lambda: _env(
            "STUDYTWIN_DB", str(REPO_ROOT / "data" / "studytwin.db")))
    web_dir: str = field(
        default_factory=lambda: _env("STUDYTWIN_WEB_DIR", str(REPO_ROOT / "web")))
    cors_origins: list[str] = field(
        default_factory=lambda: _env_list(
            "STUDYTWIN_CORS_ORIGINS",
            ["http://127.0.0.1:8777", "http://localhost:8777",
             "http://127.0.0.1:8000", "http://localhost:8000"]))
    serve_web: bool = field(default_factory=lambda: _env_bool("STUDYTWIN_SERVE_WEB", True))
    #: Allow POST /api/profiles. Off in any deployment that should not store
    #: anything about a real person.
    allow_profiles: bool = field(
        default_factory=lambda: _env_bool("STUDYTWIN_ALLOW_PROFILES", True))
    max_page_size: int = field(
        default_factory=lambda: int(_env("STUDYTWIN_MAX_PAGE_SIZE", "500")))
    log_level: str = field(default_factory=lambda: _env("STUDYTWIN_LOG_LEVEL", "INFO"))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
