from __future__ import annotations

import asyncio
import contextlib
import io
import os
import unittest
from unittest.mock import patch

import cli
from search_service import Settings


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
    settings: Settings | None = None

    def __init__(self, settings: Settings) -> None:
        self.__class__.settings = settings

    async def __aenter__(self) -> "FakeSearchService":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        pass

    async def search(self, *, query: str, links: int, retries: int):
        return {
            "query": query,
            "complete": True,
            "links": links,
            "retries": retries,
        }


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeLocalSearXNG.instances.clear()
        FakeSearchService.settings = None

    def test_searxng_url_is_optional_without_environment_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            args = cli.build_parser().parse_args(["example query"])
        self.assertIsNone(args.searxng_url)

    def test_missing_url_starts_and_closes_local_instance(self) -> None:
        args = cli.build_parser().parse_args(["example query", "--links", "2"])
        output = io.StringIO()

        with (
            patch.object(cli, "LocalSearXNG", FakeLocalSearXNG),
            patch.object(cli, "SearchService", FakeSearchService),
            contextlib.redirect_stdout(output),
        ):
            result = asyncio.run(cli.run(args))

        self.assertEqual(result, 0)
        self.assertEqual(len(FakeLocalSearXNG.instances), 1)
        self.assertTrue(FakeLocalSearXNG.instances[0].started)
        self.assertTrue(FakeLocalSearXNG.instances[0].closed)
        self.assertIsNotNone(FakeSearchService.settings)
        self.assertEqual(
            FakeSearchService.settings.searxng_url,
            "http://127.0.0.1:43210",
        )

    def test_explicit_url_does_not_start_local_instance(self) -> None:
        args = cli.build_parser().parse_args(
            ["example query", "--searxng-url", "http://search.example"]
        )

        with (
            patch.object(cli, "LocalSearXNG", FakeLocalSearXNG),
            patch.object(cli, "SearchService", FakeSearchService),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = asyncio.run(cli.run(args))

        self.assertEqual(result, 0)
        self.assertEqual(FakeLocalSearXNG.instances, [])
        self.assertEqual(
            FakeSearchService.settings.searxng_url,
            "http://search.example",
        )

    def test_local_instance_is_closed_when_search_fails(self) -> None:
        class FailingSearchService(FakeSearchService):
            async def search(self, *, query: str, links: int, retries: int):
                raise RuntimeError("search failed")

        args = cli.build_parser().parse_args(["example query"])
        error_output = io.StringIO()

        with (
            patch.object(cli, "LocalSearXNG", FakeLocalSearXNG),
            patch.object(cli, "SearchService", FailingSearchService),
            contextlib.redirect_stderr(error_output),
        ):
            result = asyncio.run(cli.run(args))

        self.assertEqual(result, 1)
        self.assertTrue(FakeLocalSearXNG.instances[0].closed)
        self.assertIn("search failed", error_output.getvalue())


if __name__ == "__main__":
    unittest.main()
