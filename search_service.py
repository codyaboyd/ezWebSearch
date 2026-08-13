from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from playwright.async_api import Browser, Playwright, async_playwright
from trafilatura import bare_extraction


TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "dclid",
    "msclkid",
    "mc_cid",
    "mc_eid",
}


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Settings:
    searxng_url: str = os.getenv("SEARXNG_URL", "http://127.0.0.1:8080").rstrip("/")
    http_concurrency: int = int(os.getenv("HTTP_CONCURRENCY", "10"))
    browser_concurrency: int = int(os.getenv("BROWSER_CONCURRENCY", "3"))
    page_timeout_seconds: float = float(os.getenv("PAGE_TIMEOUT_SECONDS", "15"))
    search_timeout_seconds: float = float(os.getenv("SEARCH_TIMEOUT_SECONDS", "10"))
    browser_timeout_ms: int = int(os.getenv("BROWSER_TIMEOUT_MS", "20000"))
    browser_settle_ms: int = int(os.getenv("BROWSER_SETTLE_MS", "750"))
    max_page_bytes: int = int(os.getenv("MAX_PAGE_BYTES", str(5 * 1024 * 1024)))
    min_text_length: int = int(os.getenv("MIN_TEXT_LENGTH", "300"))
    allow_private_urls: bool = _env_bool("ALLOW_PRIVATE_URLS", False)


class SearchService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.http: httpx.AsyncClient | None = None
        self.playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.http_sem = asyncio.Semaphore(self.settings.http_concurrency)
        self.browser_sem = asyncio.Semaphore(self.settings.browser_concurrency)

    async def start(self) -> None:
        if self.http is None:
            self.http = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=5.0,
                    read=self.settings.page_timeout_seconds,
                    write=5.0,
                    pool=5.0,
                ),
                limits=httpx.Limits(
                    max_connections=max(20, self.settings.http_concurrency * 2),
                    max_keepalive_connections=max(10, self.settings.http_concurrency),
                ),
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/150.0 Safari/537.36 "
                        "ezWebSearch/1.0"
                    ),
                    "Accept": (
                        "text/html,application/xhtml+xml,"
                        "text/plain;q=0.9,*/*;q=0.1"
                    ),
                },
            )

        if self.playwright is None:
            self.playwright = await async_playwright().start()

        if self.browser is None:
            self.browser = await self.playwright.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage"],
            )

    async def close(self) -> None:
        if self.browser is not None:
            await self.browser.close()
            self.browser = None

        if self.playwright is not None:
            await self.playwright.stop()
            self.playwright = None

        if self.http is not None:
            await self.http.aclose()
            self.http = None

    async def __aenter__(self) -> "SearchService":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    @staticmethod
    def clean_text(text: str | None) -> str:
        if not text:
            return ""
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" *\n *", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def normalize_url(raw_url: str) -> str | None:
        try:
            parsed = urlparse(raw_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                return None

            query_params: list[tuple[str, str]] = []
            for key, value in parse_qsl(parsed.query, keep_blank_values=True):
                lower_key = key.lower()
                if lower_key.startswith("utm_") or lower_key in TRACKING_PARAMETERS:
                    continue
                query_params.append((key, value))

            normalized = parsed._replace(
                query=urlencode(query_params),
                fragment="",
            )
            return urlunparse(normalized)
        except Exception:
            return None

    async def _assert_public_url(self, url: str) -> None:
        if self.settings.allow_private_urls:
            return

        parsed = urlparse(url)
        host = parsed.hostname
        if not host:
            raise ValueError("URL has no hostname")

        if host.lower() == "localhost":
            raise ValueError("Private/local URLs are blocked")

        try:
            direct_ip = ipaddress.ip_address(host)
            addresses = [direct_ip]
        except ValueError:
            loop = asyncio.get_running_loop()
            try:
                infos = await loop.run_in_executor(
                    None,
                    lambda: socket.getaddrinfo(
                        host,
                        parsed.port or (443 if parsed.scheme == "https" else 80),
                        type=socket.SOCK_STREAM,
                    ),
                )
            except socket.gaierror as exc:
                raise ValueError(f"Could not resolve hostname: {host}") from exc

            addresses = []
            for info in infos:
                addr = info[4][0]
                try:
                    addresses.append(ipaddress.ip_address(addr))
                except ValueError:
                    continue

        if not addresses:
            raise ValueError("Hostname resolved to no usable IP addresses")

        for addr in addresses:
            if (
                addr.is_private
                or addr.is_loopback
                or addr.is_link_local
                or addr.is_multicast
                or addr.is_reserved
                or addr.is_unspecified
            ):
                raise ValueError(f"Blocked non-public address: {addr}")

    async def search_searxng(self, query: str, page: int) -> list[dict[str, Any]]:
        if self.http is None:
            raise RuntimeError("Service is not started")

        response = await self.http.get(
            f"{self.settings.searxng_url}/search",
            params={
                "q": query,
                "format": "json",
                "categories": "general",
                "pageno": page,
            },
            timeout=self.settings.search_timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        results = data.get("results", [])
        return results if isinstance(results, list) else []

    async def download_page(self, url: str) -> dict[str, Any]:
        if self.http is None:
            raise RuntimeError("Service is not started")

        await self._assert_public_url(url)

        async with self.http_sem:
            async with self.http.stream("GET", url) as response:
                response.raise_for_status()

                final_url = str(response.url)
                await self._assert_public_url(final_url)

                content_type = response.headers.get("content-type", "").lower()
                allowed = ("text/html", "application/xhtml+xml", "text/plain")
                if not any(item in content_type for item in allowed):
                    raise ValueError(f"Unsupported content type: {content_type}")

                length_header = response.headers.get("content-length")
                if length_header:
                    try:
                        if int(length_header) > self.settings.max_page_bytes:
                            raise ValueError("Page exceeds maximum size")
                    except ValueError:
                        if length_header.isdigit():
                            raise

                chunks: list[bytes] = []
                total_size = 0
                async for chunk in response.aiter_bytes():
                    total_size += len(chunk)
                    if total_size > self.settings.max_page_bytes:
                        raise ValueError("Page exceeds maximum size")
                    chunks.append(chunk)

                raw = b"".join(chunks)
                encoding = response.encoding or "utf-8"
                try:
                    html = raw.decode(encoding, errors="replace")
                except LookupError:
                    html = raw.decode("utf-8", errors="replace")

                return {
                    "html": html,
                    "url": final_url,
                    "content_type": content_type,
                }

    def extract_page(self, html: str, url: str) -> dict[str, Any]:
        document = bare_extraction(
            html,
            url=url,
            include_comments=False,
            include_tables=False,
            deduplicate=True,
            favor_precision=True,
            with_metadata=True,
        )

        if document is None:
            raise ValueError("Trafilatura could not extract content")

        data = document.as_dict()
        text = self.clean_text(data.get("text") or data.get("raw_text") or "")

        if len(text) < self.settings.min_text_length:
            raise ValueError(
                f"Not enough useful text extracted ({len(text)} characters)"
            )

        return {
            "title": data.get("title"),
            "author": data.get("author"),
            "date": data.get("date"),
            "hostname": data.get("hostname"),
            "description": data.get("description"),
            "sitename": data.get("sitename"),
            "language": data.get("language"),
            "text": text,
            "characters": len(text),
        }

    async def render_page(self, url: str) -> dict[str, Any]:
        if self.browser is None:
            raise RuntimeError("Browser is not started")

        await self._assert_public_url(url)

        async with self.browser_sem:
            context = await self.browser.new_context(
                java_script_enabled=True,
                ignore_https_errors=True,
            )
            page = await context.new_page()

            async def route_handler(route) -> None:
                request = route.request
                resource_type = request.resource_type

                if resource_type in {"image", "media", "font"}:
                    await route.abort()
                    return

                request_url = request.url
                normalized = self.normalize_url(request_url)
                if normalized is None:
                    await route.abort()
                    return

                try:
                    await self._assert_public_url(normalized)
                except Exception:
                    await route.abort()
                    return

                await route.continue_()

            await page.route("**/*", route_handler)

            try:
                await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self.settings.browser_timeout_ms,
                )

                try:
                    await page.wait_for_load_state(
                        "networkidle",
                        timeout=5000,
                    )
                except Exception:
                    pass

                if self.settings.browser_settle_ms > 0:
                    await page.wait_for_timeout(self.settings.browser_settle_ms)

                final_url = page.url
                await self._assert_public_url(final_url)

                html = await page.content()
                title = await page.title()

                if len(html.encode("utf-8", errors="ignore")) > self.settings.max_page_bytes:
                    raise ValueError("Rendered page exceeds maximum size")

                return {
                    "html": html,
                    "url": final_url,
                    "title": title,
                }
            finally:
                await context.close()

    async def process_result(self, search_result: dict[str, Any]) -> dict[str, Any]:
        raw_url = search_result.get("url")
        if not raw_url:
            raise ValueError("Search result has no URL")

        url = self.normalize_url(str(raw_url))
        if not url:
            raise ValueError("Invalid URL")

        http_error: str | None = None

        try:
            downloaded = await self.download_page(url)
            extracted = await asyncio.to_thread(
                self.extract_page,
                downloaded["html"],
                downloaded["url"],
            )
            return {
                "url": downloaded["url"],
                "search_title": search_result.get("title"),
                "search_snippet": search_result.get("content"),
                "rendered": False,
                "extraction_method": "http",
                **extracted,
            }
        except Exception as exc:
            http_error = str(exc)

        try:
            rendered = await self.render_page(url)
            extracted = await asyncio.to_thread(
                self.extract_page,
                rendered["html"],
                rendered["url"],
            )
            return {
                "url": rendered["url"],
                "search_title": search_result.get("title"),
                "search_snippet": search_result.get("content"),
                "rendered": True,
                "extraction_method": "playwright",
                "http_attempt_error": http_error,
                **extracted,
            }
        except Exception as browser_exc:
            raise ValueError(
                f"HTTP extraction failed: {http_error}; "
                f"Playwright extraction failed: {browser_exc}"
            ) from browser_exc

    async def _process_candidates(
        self,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        async def worker(result: dict[str, Any]) -> dict[str, Any]:
            try:
                page = await self.process_result(result)
                return {"success": True, "result": page}
            except Exception as exc:
                return {
                    "success": False,
                    "url": result.get("url"),
                    "title": result.get("title"),
                    "error": str(exc),
                }

        return await asyncio.gather(*(worker(result) for result in candidates))

    async def search(
        self,
        query: str,
        links: int = 5,
        retries: int = 2,
    ) -> dict[str, Any]:
        query = query.strip()

        if not query:
            raise ValueError("query cannot be empty")
        if not 1 <= links <= 25:
            raise ValueError("links must be between 1 and 25")
        if not 0 <= retries <= 10:
            raise ValueError("retries must be between 0 and 10")

        successful: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        search_pages_used = 0

        # retries means additional SearXNG result pages:
        # retries=0 -> page 1 only
        # retries=3 -> pages 1, 2, 3, and 4 if needed
        for attempt in range(retries + 1):
            if len(successful) >= links:
                break

            search_page = attempt + 1

            try:
                search_results = await self.search_searxng(query, search_page)
                search_pages_used += 1
            except Exception as exc:
                failures.append(
                    {
                        "type": "search",
                        "search_page": search_page,
                        "error": str(exc),
                    }
                )
                continue

            candidates: list[dict[str, Any]] = []

            for result in search_results:
                raw_url = result.get("url")
                if not raw_url:
                    continue

                normalized = self.normalize_url(str(raw_url))
                if not normalized or normalized in seen_urls:
                    continue

                seen_urls.add(normalized)
                item = dict(result)
                item["url"] = normalized
                candidates.append(item)

            if not candidates:
                continue

            batch_results = await self._process_candidates(candidates)

            for item in batch_results:
                if item["success"]:
                    if len(successful) >= links:
                        break
                    page_result = item["result"]
                    page_result["rank"] = len(successful) + 1
                    successful.append(page_result)
                else:
                    failures.append(
                        {
                            "type": "page",
                            "url": item.get("url"),
                            "title": item.get("title"),
                            "error": item.get("error"),
                        }
                    )

        return {
            "query": query,
            "requested_links": links,
            "returned_links": len(successful),
            "missing_links": max(0, links - len(successful)),
            "complete": len(successful) >= links,
            "retries_allowed": retries,
            "search_pages_used": search_pages_used,
            "results": successful,
            "failures": failures,
        }
