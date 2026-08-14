from __future__ import annotations

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import api


class FakeLocalSearXNG:
    instances: list["FakeLocalSearXNG"] = []

    def __init__(self) -> None:
        self.started = False
        self.closed = False
        self.__class__.instances.append(self)

    async def start(self) -> str:
        self.started = True
        return "http://127.0.0.1:43210"

    async def close(self) -> None:
        self.closed = True


class FakeSearchService:
    def __init__(self, *, fail_start: bool = False) -> None:
        self.settings = SimpleNamespace(searxng_url="http://127.0.0.1:8080")
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
    def setUp(self) -> None:
        FakeLocalSearXNG.instances.clear()

    def test_api_starts_and_stops_local_searxng_without_external_url(self) -> None:
        service = FakeSearchService()

        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(api, "LocalSearXNG", FakeLocalSearXNG),
            patch.object(api, "service", service),
        ):
            asyncio.run(self._run_lifespan())

        self.assertEqual(len(FakeLocalSearXNG.instances), 1)
        local = FakeLocalSearXNG.instances[0]
        self.assertTrue(local.started)
        self.assertTrue(local.closed)
        self.assertTrue(service.started)
        self.assertTrue(service.closed)
        self.assertEqual(service.settings.searxng_url, "http://127.0.0.1:43210")

    def test_api_uses_external_searxng_without_starting_local_instance(self) -> None:
        service = FakeSearchService()

        with (
            patch.dict(
                os.environ,
                {"SEARXNG_URL": "http://search.example/"},
                clear=True,
            ),
            patch.object(api, "LocalSearXNG", FakeLocalSearXNG),
            patch.object(api, "service", service),
        ):
            asyncio.run(self._run_lifespan())

        self.assertEqual(FakeLocalSearXNG.instances, [])
        self.assertEqual(service.settings.searxng_url, "http://search.example")

    def test_local_instance_is_closed_if_service_start_fails(self) -> None:
        service = FakeSearchService(fail_start=True)

        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(api, "LocalSearXNG", FakeLocalSearXNG),
            patch.object(api, "service", service),
            self.assertRaisesRegex(RuntimeError, "service failed to start"),
        ):
            asyncio.run(self._run_lifespan())

        self.assertTrue(FakeLocalSearXNG.instances[0].closed)
        self.assertTrue(service.closed)

    @staticmethod
    async def _run_lifespan() -> None:
        async with api.lifespan(api.app):
            pass


if __name__ == "__main__":
    unittest.main()
