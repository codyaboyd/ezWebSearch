from __future__ import annotations

import asyncio
import unittest

import httpx

from ezwebsearch import (
    AsyncEzWebSearchClient,
    EzWebSearchClient,
    EzWebSearchError,
    EzWebSearchHTTPError,
)


class ClientTests(unittest.TestCase):
    def test_search_sends_expected_request_and_returns_json(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={"complete": True, "results": []},
                request=request,
            )

        with EzWebSearchClient(
            "http://search.example/",
            transport=httpx.MockTransport(handler),
        ) as client:
            result = client.search("  python clients  ", links=3, retries=1)

        self.assertEqual(result, {"complete": True, "results": []})
        self.assertEqual(len(requests), 1)
        self.assertEqual(
            str(requests[0].url.copy_with(query=None)),
            "http://search.example/search",
        )
        self.assertEqual(
            dict(requests[0].url.params),
            {"query": "python clients", "links": "3", "retries": "1"},
        )
        self.assertEqual(requests[0].headers["accept"], "application/json")

    def test_health_uses_health_endpoint(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"status": "ok"}, request=request)

        with EzWebSearchClient(
            "http://search.example",
            transport=httpx.MockTransport(handler),
        ) as client:
            self.assertEqual(client.health(), {"status": "ok"})

    def test_http_errors_include_status_and_api_detail(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                422,
                json={"detail": "links must be between 1 and 25"},
                request=request,
            )

        with EzWebSearchClient(
            "http://search.example",
            transport=httpx.MockTransport(handler),
        ) as client:
            with self.assertRaises(EzWebSearchHTTPError) as caught:
                client.search("example")

        self.assertEqual(caught.exception.status_code, 422)
        self.assertIn("links must be between 1 and 25", str(caught.exception))

    def test_invalid_arguments_fail_before_request(self) -> None:
        with EzWebSearchClient(
            "http://search.example",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(500, request=request)
            ),
        ) as client:
            with self.assertRaises(ValueError):
                client.search("", links=1)
            with self.assertRaises(ValueError):
                client.search("example", links=26)

    def test_transport_errors_are_wrapped(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("unavailable", request=request)

        with EzWebSearchClient(
            "http://search.example",
            transport=httpx.MockTransport(handler),
        ) as client:
            with self.assertRaises(EzWebSearchError) as caught:
                client.health()

        self.assertIn("Request to ezWebSearch failed", str(caught.exception))

    def test_async_client_search(self) -> None:
        async def run() -> dict[str, object]:
            def handler(request: httpx.Request) -> httpx.Response:
                return httpx.Response(
                    200,
                    json={"query": "async", "complete": False},
                    request=request,
                )

            async with AsyncEzWebSearchClient(
                "http://search.example",
                transport=httpx.MockTransport(handler),
            ) as client:
                return await client.search("async", links=1, retries=0)

        self.assertEqual(
            asyncio.run(run()),
            {"query": "async", "complete": False},
        )


if __name__ == "__main__":
    unittest.main()
