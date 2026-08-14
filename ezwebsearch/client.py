from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

import httpx


DEFAULT_BASE_URL = "http://127.0.0.1:6666"
DEFAULT_TIMEOUT_SECONDS = 30.0
USER_AGENT = "ezwebsearch-python/0.1.0"


class EzWebSearchError(RuntimeError):
    """Base exception raised by the ezWebSearch clients."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class EzWebSearchHTTPError(EzWebSearchError):
    """Raised when the ezWebSearch API returns a non-success status code."""


def _validate_base_url(base_url: str) -> str:
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("base_url must be a non-empty URL")

    normalized = base_url.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base_url must be an absolute http:// or https:// URL")
    return normalized


def _validate_search_arguments(query: str, links: int, retries: int) -> str:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if isinstance(links, bool) or not isinstance(links, int) or not 1 <= links <= 25:
        raise ValueError("links must be an integer between 1 and 25")
    if (
        isinstance(retries, bool)
        or not isinstance(retries, int)
        or not 0 <= retries <= 10
    ):
        raise ValueError("retries must be an integer between 0 and 10")
    return query.strip()


def _headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    result = {
        "accept": "application/json",
        "user-agent": USER_AGENT,
    }
    if headers:
        result.update(headers)
    return result


def _response_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text.strip()

    if isinstance(payload, dict):
        detail = payload.get("detail") or payload.get("message")
        if detail is not None:
            return str(detail)
    return response.text.strip()


def _decode_response(response: httpx.Response) -> dict[str, Any]:
    if response.is_error:
        detail = _response_detail(response)
        message = f"ezWebSearch API returned HTTP {response.status_code}"
        if detail:
            message += f": {detail}"
        raise EzWebSearchHTTPError(
            message,
            status_code=response.status_code,
            response_body=response.text,
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise EzWebSearchError(
            "ezWebSearch API returned invalid JSON",
            status_code=response.status_code,
            response_body=response.text,
        ) from exc

    if not isinstance(payload, dict):
        raise EzWebSearchError(
            "ezWebSearch API returned a JSON value instead of an object",
            status_code=response.status_code,
            response_body=response.text,
        )
    return payload


class EzWebSearchClient:
    """Synchronous client for a running ezWebSearch API server.

    The client returns the API's JSON objects as dictionaries so callers can
    use the same response shape as the HTTP endpoint.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float | httpx.Timeout = DEFAULT_TIMEOUT_SECONDS,
        headers: Mapping[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        if transport is not None and http_client is not None:
            raise ValueError("provide transport or http_client, not both")

        self.base_url = _validate_base_url(base_url)
        self._owns_http_client = http_client is None
        if http_client is not None:
            self._http_client = http_client
            return

        client_kwargs: dict[str, Any] = {
            "follow_redirects": True,
            "headers": _headers(headers),
            "timeout": timeout,
        }
        if transport is not None:
            client_kwargs["transport"] = transport
        self._http_client = httpx.Client(**client_kwargs)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = self._http_client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise EzWebSearchError(f"Request to ezWebSearch failed: {exc}") from exc
        return _decode_response(response)

    def health(self) -> dict[str, Any]:
        """Return the API health response."""

        return self._request("GET", "/health")

    def search(
        self,
        query: str,
        links: int = 5,
        retries: int = 2,
    ) -> dict[str, Any]:
        """Search for readable pages and return the API response."""

        normalized_query = _validate_search_arguments(query, links, retries)
        return self._request(
            "GET",
            "/search",
            params={
                "query": normalized_query,
                "links": links,
                "retries": retries,
            },
        )

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""

        if self._owns_http_client:
            self._http_client.close()

    def __enter__(self) -> "EzWebSearchClient":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()


class AsyncEzWebSearchClient:
    """Asynchronous client for a running ezWebSearch API server."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float | httpx.Timeout = DEFAULT_TIMEOUT_SECONDS,
        headers: Mapping[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if transport is not None and http_client is not None:
            raise ValueError("provide transport or http_client, not both")

        self.base_url = _validate_base_url(base_url)
        self._owns_http_client = http_client is None
        if http_client is not None:
            self._http_client = http_client
            return

        client_kwargs: dict[str, Any] = {
            "follow_redirects": True,
            "headers": _headers(headers),
            "timeout": timeout,
        }
        if transport is not None:
            client_kwargs["transport"] = transport
        self._http_client = httpx.AsyncClient(**client_kwargs)

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            response = await self._http_client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise EzWebSearchError(f"Request to ezWebSearch failed: {exc}") from exc
        return _decode_response(response)

    async def health(self) -> dict[str, Any]:
        """Return the API health response."""

        return await self._request("GET", "/health")

    async def search(
        self,
        query: str,
        links: int = 5,
        retries: int = 2,
    ) -> dict[str, Any]:
        """Search for readable pages and return the API response."""

        normalized_query = _validate_search_arguments(query, links, retries)
        return await self._request(
            "GET",
            "/search",
            params={
                "query": normalized_query,
                "links": links,
                "retries": retries,
            },
        )

    async def close(self) -> None:
        """Close the underlying HTTP connection pool."""

        if self._owns_http_client:
            await self._http_client.aclose()

    async def __aenter__(self) -> "AsyncEzWebSearchClient":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        await self.close()


Client = EzWebSearchClient
AsyncClient = AsyncEzWebSearchClient


__all__ = [
    "AsyncClient",
    "AsyncEzWebSearchClient",
    "Client",
    "EzWebSearchClient",
    "EzWebSearchError",
    "EzWebSearchHTTPError",
]
