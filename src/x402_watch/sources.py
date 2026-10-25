"""Safe public-source retrieval, extraction, and provenance assignment."""

from __future__ import annotations

import hashlib
import os
import socket
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from time import monotonic
from typing import Self
from urllib.parse import urlsplit

import trafilatura
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from trafilatura.metadata import extract_metadata

from .models import EvidenceSource, Lane, SearchHit
from .urls import UnsafeUrlError, canonicalize_url, resolve_public_url


class SourceFetchFailureCategory(str, Enum):
    REQUEST_TIMEOUT = "request_timeout"
    UNSAFE_URL = "unsafe_url"
    REDIRECT_MISSING_TARGET = "redirect_missing_target"
    REDIRECT_LIMIT = "redirect_limit"
    HTTP_STATUS = "http_status"
    NON_HTML_CONTENT = "non_html_content"
    COMPRESSED_RESPONSE = "compressed_response"
    INVALID_CONTENT_LENGTH = "invalid_content_length"
    RESPONSE_TOO_LARGE = "response_too_large"
    REQUEST_LIMIT = "request_limit"
    UNSAFE_REQUEST = "unsafe_request"
    REQUEST_FAILED = "request_failed"
    REDIRECT_HANDLING_FAILED = "redirect_handling_failed"


class SourceFetchError(RuntimeError):
    """Raised when a public source cannot be safely retrieved."""

    def __init__(
        self,
        message: str,
        *,
        category: SourceFetchFailureCategory,
        status_code: int | None = None,
    ):
        super().__init__(message)
        if (category is SourceFetchFailureCategory.HTTP_STATUS) != (
            status_code is not None
        ):
            raise ValueError("HTTP status diagnostics require a matching status code")
        if status_code is not None and not 100 <= status_code <= 599:
            raise ValueError("HTTP status code is invalid")
        self.category = category
        self.status_code = status_code

    @property
    def diagnostic_code(self) -> str:
        if self.status_code is not None:
            return f"http_status_{self.status_code}"
        return self.category.value


class SourceExtractionError(RuntimeError):
    """Raised when retrieved HTML has no usable article text."""


@dataclass(frozen=True)
class FetchedPage:
    url: str
    html: bytes
    content_type: str


_PRIMARY_DOMAINS: dict[Lane, set[str]] = {
    Lane.X402_ACP: {
        "coinbase.com",
        "docs.cdp.coinbase.com",
        "x402.org",
        "stripe.com",
    },
    Lane.GENIUS_ACT: {
        "congress.gov",
        "fdic.gov",
        "federalreserve.gov",
        "occ.gov",
        "sec.gov",
        "treasury.gov",
    },
    Lane.STABLECOIN_VOLUME: {
        "federalreserve.gov",
        "mastercard.com",
        "sec.gov",
        "treasury.gov",
        "visa.com",
    },
    Lane.STRIPE_OPENROUTER: {"openrouter.ai", "stripe.com"},
}


def _is_primary_source(lane: Lane, url: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if host == "github.com":
        path = parsed.path.lower()
        return lane == Lane.X402_ACP and path.startswith(
            ("/coinbase/x402", "/coinbase/agentic")
        )
    return any(
        host == domain or host.endswith(f".{domain}")
        for domain in _PRIMARY_DOMAINS[lane]
    )


class PlaywrightPageFetcher:
    _BLOCKED_RESOURCE_TYPES = frozenset({"font", "image", "media", "websocket"})
    _MAX_BROWSER_REQUESTS = 128

    def __init__(
        self,
        *,
        max_bytes: int = 2_000_000,
        max_redirects: int = 4,
        timeout: float = 20.0,
        resolver=socket.getaddrinfo,
    ):
        if max_bytes < 1024 or max_redirects < 0 or timeout <= 0:
            raise ValueError("Source-fetch bounds are invalid")
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._max_duration = timeout
        self._resolver = resolver

    def fetch(self, url: str) -> FetchedPage:
        try:
            safe_url, _ = resolve_public_url(url, resolver=self._resolver)
        except UnsafeUrlError as exc:
            raise SourceFetchError(
                str(exc),
                category=SourceFetchFailureCategory.UNSAFE_URL,
            ) from exc

        deadline = monotonic() + self._max_duration
        route_failures: list[SourceFetchError] = []
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    env=_browser_environment(),
                    timeout=max(1, int(self._max_duration * 1000)),
                )
                try:
                    context = browser.new_context(
                        accept_downloads=False,
                        service_workers="block",
                    )
                    try:
                        request_count = 0

                        def validate_request(route) -> None:
                            nonlocal request_count
                            request = route.request
                            if request.resource_type in self._BLOCKED_RESOURCE_TYPES:
                                route.abort()
                                return
                            scheme = request.url.partition(":")[0].lower()
                            if scheme in {"about", "blob", "data"}:
                                route.continue_()
                                return
                            request_count += 1
                            if request_count > self._MAX_BROWSER_REQUESTS:
                                route_failures.append(
                                    SourceFetchError(
                                        "Source exceeded the browser request limit",
                                        category=(
                                            SourceFetchFailureCategory.REQUEST_LIMIT
                                        ),
                                    )
                                )
                                route.abort()
                                return
                            if request.method != "GET":
                                route_failures.append(
                                    SourceFetchError(
                                        "Source attempted a non-GET browser request",
                                        category=(
                                            SourceFetchFailureCategory.UNSAFE_REQUEST
                                        ),
                                    )
                                )
                                route.abort()
                                return
                            if (
                                _redirect_count(request, self._max_redirects)
                                > self._max_redirects
                            ):
                                route_failures.append(
                                    SourceFetchError(
                                        "Source exceeded the redirect limit",
                                        category=(
                                            SourceFetchFailureCategory.REDIRECT_LIMIT
                                        ),
                                    )
                                )
                                route.abort()
                                return
                            try:
                                request_url, _ = resolve_public_url(
                                    request.url,
                                    resolver=self._resolver,
                                )
                            except UnsafeUrlError as exc:
                                route_failures.append(
                                    SourceFetchError(
                                        str(exc),
                                        category=(
                                            SourceFetchFailureCategory.UNSAFE_URL
                                        ),
                                    )
                                )
                                route.abort()
                                return
                            if request_url == request.url:
                                route.continue_()
                            else:
                                route.continue_(url=request_url)

                        context.route("**/*", validate_request)
                        page = context.new_page()
                        remaining_ms = int((deadline - monotonic()) * 1000)
                        if remaining_ms <= 0:
                            raise SourceFetchError(
                                "Source request exceeded the time limit",
                                category=(
                                    SourceFetchFailureCategory.REQUEST_TIMEOUT
                                ),
                            )
                        try:
                            response = page.goto(
                                safe_url,
                                wait_until="domcontentloaded",
                                timeout=remaining_ms,
                            )
                        except PlaywrightError:
                            if route_failures:
                                raise route_failures[0]
                            raise
                        if route_failures:
                            raise route_failures[0]
                        if response is None:
                            raise SourceFetchError(
                                "Source navigation returned no response",
                                category=SourceFetchFailureCategory.REQUEST_FAILED,
                            )
                        if response.status < 200 or response.status >= 300:
                            raise SourceFetchError(
                                f"Source returned HTTP {response.status}",
                                category=SourceFetchFailureCategory.HTTP_STATUS,
                                status_code=response.status,
                            )
                        content_type = (
                            response.header_value("content-type") or ""
                        ).lower()
                        if not content_type.startswith(
                            ("text/html", "application/xhtml+xml")
                        ):
                            raise SourceFetchError(
                                "Source is not an HTML page",
                                category=SourceFetchFailureCategory.NON_HTML_CONTENT,
                            )
                        content_length = response.header_value("content-length")
                        if content_length:
                            if not content_length.isdigit():
                                raise SourceFetchError(
                                    "Source returned an invalid content length",
                                    category=(
                                        SourceFetchFailureCategory.INVALID_CONTENT_LENGTH
                                    ),
                                )
                            declared_length = content_length.lstrip("0") or "0"
                            if (
                                len(declared_length) > len(str(self._max_bytes))
                                or int(declared_length) > self._max_bytes
                            ):
                                raise SourceFetchError(
                                    "Source exceeded the byte limit",
                                    category=(
                                        SourceFetchFailureCategory.RESPONSE_TOO_LARGE
                                    ),
                                )
                        try:
                            final_url, _ = resolve_public_url(
                                page.url,
                                resolver=self._resolver,
                            )
                        except UnsafeUrlError as exc:
                            raise SourceFetchError(
                                str(exc),
                                category=SourceFetchFailureCategory.UNSAFE_URL,
                            ) from exc
                        html = page.content().encode("utf-8")
                        if monotonic() >= deadline:
                            raise SourceFetchError(
                                "Source request exceeded the time limit",
                                category=SourceFetchFailureCategory.REQUEST_TIMEOUT,
                            )
                        if len(html) > self._max_bytes:
                            raise SourceFetchError(
                                "Source exceeded the byte limit",
                                category=SourceFetchFailureCategory.RESPONSE_TOO_LARGE,
                            )
                        return FetchedPage(
                            url=final_url,
                            html=html,
                            content_type=content_type,
                        )
                    finally:
                        context.close()
                finally:
                    browser.close()
        except PlaywrightTimeoutError as exc:
            if route_failures:
                raise route_failures[0] from exc
            raise SourceFetchError(
                "Source request timed out",
                category=SourceFetchFailureCategory.REQUEST_TIMEOUT,
            ) from exc
        except PlaywrightError as exc:
            if route_failures:
                raise route_failures[0] from exc
            raise SourceFetchError(
                "Public source browser request failed",
                category=SourceFetchFailureCategory.REQUEST_FAILED,
            ) from exc

    def close(self) -> None:
        return None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


def extract_source(
    lane: Lane,
    hit: SearchHit,
    page: FetchedPage,
    retrieved_at: datetime | None = None,
) -> EvidenceSource:
    retrieved = retrieved_at or datetime.now(UTC)
    try:
        html = page.html.decode("utf-8", errors="replace")
        text = trafilatura.extract(
            html,
            url=page.url,
            include_comments=False,
            include_tables=False,
        )
        metadata = extract_metadata(html, default_url=page.url)
    except (ValueError, TypeError) as exc:
        raise SourceExtractionError("Source text extraction failed") from exc
    if not text or not text.strip():
        raise SourceExtractionError("Source has no extractable article text")
    normalized_text = " ".join(text.split())
    excerpt = normalized_text[:1800]
    canonical = canonicalize_url(page.url)
    try:
        publisher = metadata.sitename if metadata and metadata.sitename else ""
        published_at = metadata.date if metadata and metadata.date else None
    except AttributeError:
        publisher = ""
        published_at = None
    host = urlsplit(canonical).hostname or "unknown publisher"
    publisher = publisher.strip() or host
    source_id = hashlib.sha256(
        f"{canonical}\n{hashlib.sha256(normalized_text.encode()).hexdigest()}".encode()
    ).hexdigest()[:16]
    content_hash = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()
    try:
        return EvidenceSource(
            source_id=source_id,
            lane=lane,
            title=hit.title.strip() or publisher,
            url=page.url,
            canonical_url=canonical,
            publisher=publisher[:300],
            published_at=published_at,
            retrieved_at=retrieved.isoformat(timespec="seconds").replace("+00:00", "Z"),
            content_hash=content_hash,
            excerpt=excerpt,
            primary_source=_is_primary_source(lane, canonical),
        )
    except ValueError as exc:
        raise SourceExtractionError("Extracted source metadata is invalid") from exc


__all__ = [
    "FetchedPage",
    "PlaywrightPageFetcher",
    "SourceExtractionError",
    "SourceFetchError",
    "SourceFetchFailureCategory",
    "extract_source",
]


def _redirect_count(request, max_redirects: int) -> int:
    count = 0
    redirected_from = request.redirected_from
    while redirected_from is not None:
        count += 1
        if count > max_redirects:
            return count
        redirected_from = redirected_from.redirected_from
    return count


def _browser_environment() -> dict[str, str]:
    allowed = {"HOME", "PATH", "LANG", "LC_ALL", "TMPDIR"}
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in allowed
    }
    environment.setdefault("HOME", os.path.expanduser("~"))
    return environment
