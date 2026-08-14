from __future__ import annotations

import os
from dataclasses import dataclass
from collections.abc import Mapping
from pathlib import Path

from dotenv import load_dotenv


def _as_int(env: Mapping[str, str], name: str, default: int) -> int:
    value = env.get(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _as_float(env: Mapping[str, str], name: str, default: float) -> float:
    value = env.get(name)
    if value is None or not value.strip():
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


def _as_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    value = env.get(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _as_optional_string(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name, "").strip()
    return value.rstrip("/") or None


@dataclass(slots=True)
class Settings:
    """All runtime settings used by the API, CLI, and search service.

    ``Settings.from_env()`` is the normal entry point. Keeping environment
    parsing here means the API and CLI cannot silently disagree about the
    same option, and it avoids reading environment variables at import time.
    """

    searxng_url: str | None = None
    searxng_backend: str = "auto"
    searxng_docker_image: str = "docker.io/searxng/searxng:latest"
    searxng_startup_timeout_seconds: float = 120.0
    http_concurrency: int = 10
    browser_concurrency: int = 3
    page_timeout_seconds: float = 15.0
    search_timeout_seconds: float = 10.0
    browser_timeout_ms: int = 20_000
    browser_settle_ms: int = 750
    max_page_bytes: int = 5 * 1024 * 1024
    min_text_length: int = 300
    allow_private_urls: bool = False
    host: str = "0.0.0.0"
    port: int = 3000

    def __post_init__(self) -> None:
        if self.searxng_url:
            self.searxng_url = self.searxng_url.strip().rstrip("/")
        else:
            self.searxng_url = None
        self.searxng_backend = self.searxng_backend.strip().lower()
        if self.searxng_backend not in {"auto", "docker", "python"}:
            raise ValueError("SEARXNG_BACKEND must be auto, docker, or python")
        if self.http_concurrency < 1 or self.browser_concurrency < 1:
            raise ValueError("concurrency values must be positive")
        if (
            self.page_timeout_seconds <= 0
            or self.search_timeout_seconds <= 0
            or self.searxng_startup_timeout_seconds <= 0
            or self.browser_timeout_ms <= 0
            or self.browser_settle_ms < 0
        ):
            raise ValueError("timeout values are invalid")
        if self.max_page_bytes < 1 or self.min_text_length < 0:
            raise ValueError("page size and text length limits are invalid")
        if self.port < 1 or self.port > 65535:
            raise ValueError("PORT must be between 1 and 65535")

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        """Load settings from ``.env`` and the process environment.

        Process variables win because ``load_dotenv`` never overwrites an
        existing environment variable. A mapping can be supplied by tests or
        embedding applications to make configuration deterministic.
        """

        if env is None:
            dotenv_path = os.getenv("ENV_FILE") or (Path.cwd() / ".env")
            load_dotenv(dotenv_path=dotenv_path)
            env = os.environ

        return cls(
            searxng_url=_as_optional_string(env, "SEARXNG_URL"),
            searxng_backend=env.get("SEARXNG_BACKEND") or "auto",
            searxng_docker_image=env.get(
                "SEARXNG_DOCKER_IMAGE",
                "docker.io/searxng/searxng:latest",
            )
            or "docker.io/searxng/searxng:latest",
            searxng_startup_timeout_seconds=_as_float(
                env,
                "SEARXNG_STARTUP_TIMEOUT_SECONDS",
                120.0,
            ),
            http_concurrency=_as_int(env, "HTTP_CONCURRENCY", 10),
            browser_concurrency=_as_int(env, "BROWSER_CONCURRENCY", 3),
            page_timeout_seconds=_as_float(env, "PAGE_TIMEOUT_SECONDS", 15.0),
            search_timeout_seconds=_as_float(
                env,
                "SEARCH_TIMEOUT_SECONDS",
                10.0,
            ),
            browser_timeout_ms=_as_int(env, "BROWSER_TIMEOUT_MS", 20_000),
            browser_settle_ms=_as_int(env, "BROWSER_SETTLE_MS", 750),
            max_page_bytes=_as_int(env, "MAX_PAGE_BYTES", 5 * 1024 * 1024),
            min_text_length=_as_int(env, "MIN_TEXT_LENGTH", 300),
            allow_private_urls=_as_bool(env, "ALLOW_PRIVATE_URLS", False),
            host=env.get("HOST") or "0.0.0.0",
            port=_as_int(env, "PORT", 3000),
        )
