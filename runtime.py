from __future__ import annotations

from collections.abc import Callable
from typing import Any

from config import Settings
from local_searxng import LocalSearXNG
from search_service import SearchService


class SearchRuntime:
    """Own the SearXNG and browser lifecycles for one application process."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        service: SearchService | Any | None = None,
        local_searxng_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.service = (
            service
            if service is not None
            else SearchService(settings or Settings.from_env())
        )
        self.settings = settings or self.service.settings
        self.local_searxng_factory = local_searxng_factory
        self.local_searxng: Any | None = None
        self._service_context_active = False
        self._started = False

    def _create_local_searxng(self) -> Any:
        factory = self.local_searxng_factory
        if factory is not None:
            # Test and embedding factories are often deliberately minimal.
            return factory()
        return LocalSearXNG(
            startup_timeout_seconds=self.settings.searxng_startup_timeout_seconds,
            backend=self.settings.searxng_backend,
            docker_image=self.settings.searxng_docker_image,
        )

    async def start(self) -> None:
        if self._started:
            return
        try:
            if not self.service.settings.searxng_url:
                self.local_searxng = self._create_local_searxng()
                self.service.settings.searxng_url = await self.local_searxng.start()

            if hasattr(self.service, "start"):
                await self.service.start()
            elif hasattr(self.service, "__aenter__"):
                await self.service.__aenter__()
                self._service_context_active = True
            else:
                raise TypeError(
                    "search service must provide start() or an async context manager"
                )
            self._started = True
        except Exception:
            await self.close()
            raise

    async def close(self) -> None:
        try:
            if self._service_context_active:
                await self.service.__aexit__(None, None, None)
                self._service_context_active = False
            elif hasattr(self.service, "close"):
                await self.service.close()
        finally:
            if self.local_searxng is not None:
                await self.local_searxng.close()
                self.local_searxng = None
            self._started = False

    async def __aenter__(self) -> "SearchRuntime":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()
