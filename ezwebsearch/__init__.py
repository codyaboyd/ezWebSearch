"""Python clients for the ezWebSearch HTTP API."""

from .client import (
    AsyncClient,
    AsyncEzWebSearchClient,
    Client,
    EzWebSearchClient,
    EzWebSearchError,
    EzWebSearchHTTPError,
)

__all__ = [
    "AsyncClient",
    "AsyncEzWebSearchClient",
    "Client",
    "EzWebSearchClient",
    "EzWebSearchError",
    "EzWebSearchHTTPError",
]

__version__ = "0.1.0"
