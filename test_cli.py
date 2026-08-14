from __future__ import annotations

import asyncio
import contextlib
import io
import os
import unittest
from unittest.mock import patch

import cli
from config import Settings


class FakeSearchService:
    settings: Settings | None = None
    instances: list["FakeSearchService"] = []

    def __init__(self, settings: Settings) -> None:
        self.__class__.settings = settings
        self.started = False
        self.closed = False
        self.__class__.instances.append(self)

    async def __aenter__(self) -> "FakeSearchService":
        self.started = True
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.closed = True

    async def search(self, *, query: str, links: int, retries: int):
        return {
            "query": query,
            "complete": True,
            "links": links,
            "retries": retries,
        }


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeSearchService.instances.clear()
        FakeSearchService.settings = None

    def test_default_url_is_the_compose_searxng_port(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            args = cli.build_parser().parse_args(["example query"])

        self.assertEqual(args.searxng_url, "http://127.0.0.1:6667")

    def test_default_url_is_passed_to_the_service(self) -> None:
        args = cli.build_parser().parse_args(["example query", "--links", "2"])
        output = io.StringIO()

        with (
            patch.object(cli, "SearchService", FakeSearchService),
            contextlib.redirect_stdout(output),
        ):
            result = asyncio.run(cli.run(args))

        self.assertEqual(result, 0)
        self.assertEqual(len(FakeSearchService.instances), 1)
        self.assertTrue(FakeSearchService.instances[0].started)
        self.assertTrue(FakeSearchService.instances[0].closed)
        self.assertEqual(
            FakeSearchService.settings.searxng_url,
            "http://127.0.0.1:6667",
        )

    def test_explicit_url_overrides_the_default(self) -> None:
        args = cli.build_parser().parse_args(
            ["example query", "--searxng-url", "http://search.example"]
        )

        with (
            patch.object(cli, "SearchService", FakeSearchService),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            result = asyncio.run(cli.run(args))

        self.assertEqual(result, 0)
        self.assertEqual(
            FakeSearchService.settings.searxng_url,
            "http://search.example",
        )

    def test_service_is_closed_when_search_fails(self) -> None:
        class FailingSearchService(FakeSearchService):
            async def search(self, *, query: str, links: int, retries: int):
                raise RuntimeError("search failed")

        args = cli.build_parser().parse_args(["example query"])
        error_output = io.StringIO()

        with (
            patch.object(cli, "SearchService", FailingSearchService),
            contextlib.redirect_stderr(error_output),
        ):
            result = asyncio.run(cli.run(args))

        self.assertEqual(result, 1)
        self.assertTrue(FailingSearchService.instances[0].closed)
        self.assertIn("search failed", error_output.getvalue())


if __name__ == "__main__":
    unittest.main()
