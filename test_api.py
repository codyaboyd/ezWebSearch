from __future__ import annotations

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import api


class FakeSearchService:
    def __init__(self, *, fail_start: bool = False) -> None:
        self.settings = SimpleNamespace(searxng_url="http://127.0.0.1:6667")
        self.fail_start = fail_start
        self.started = False
        self.closed = False

    async def start(self) -> None:
        self.started = True
        if self.fail_start:
            raise RuntimeError("service failed to start")

    async def close(self) -> None:
        self.closed = True


class ApiLifecycleTests(unittest.TestCase):
    def test_api_uses_the_configured_searxng_without_managing_it(self) -> None:
        service = FakeSearchService()

        with (
            patch.dict(
                os.environ,
                {"SEARXNG_URL": "http://search.example/"},
                clear=True,
            ),
            patch.object(api, "service", service),
        ):
            asyncio.run(self._run_lifespan())

        self.assertTrue(service.started)
        self.assertTrue(service.closed)
        self.assertEqual(service.settings.searxng_url, "http://search.example")

    def test_api_defaults_to_the_compose_searxng_port(self) -> None:
        service = FakeSearchService()

        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(api, "service", service),
        ):
            asyncio.run(self._run_lifespan())

        self.assertEqual(service.settings.searxng_url, "http://127.0.0.1:6667")

    def test_service_is_closed_if_start_fails(self) -> None:
        service = FakeSearchService(fail_start=True)

        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(api, "service", service),
            self.assertRaisesRegex(RuntimeError, "service failed to start"),
        ):
            asyncio.run(self._run_lifespan())

        self.assertTrue(service.closed)

    @staticmethod
    async def _run_lifespan() -> None:
        async with api.lifespan(api.app):
            pass


if __name__ == "__main__":
    unittest.main()
