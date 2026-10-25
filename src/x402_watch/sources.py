"""Safe public-source retrieval, extraction, and provenance assignment."""

from __future__ import annotations

import hashlib
import ipaddress
import socket
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from time import monotonic
from typing import Self
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
import trafilatura
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


class PublicPageFetcher:
    def __init__(
        self,
        *,
        max_bytes: int = 2_000_000,
        max_redirects: int = 4,
        timeout: float = 20.0,
        client: httpx.Client | None = None,
        resolver=socket.getaddrinfo,
    ):
        if max_bytes < 1024 or max_redirects < 0 or timeout <= 0:
            raise ValueError("Source-fetch bounds are invalid")
        self._max_bytes = max_bytes
        self._max_redirects = max_redirects
        self._max_duration = timeout
        self._resolver = resolver
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=timeout,
            trust_env=False,
            follow_redirects=False,
            headers={
                "User-Agent": "x402-watch/0.1 (+local research client)",
                "Accept-Encoding": "identity",
            },
        )

    def fetch(self, url: str) -> FetchedPage:
        current = url
        deadline = monotonic() + self._max_duration
        for redirect_count in range(self._max_redirects + 1):
            if monotonic() >= deadline:
                raise SourceFetchError(
                    "Source request exceeded the time limit",
                    category=SourceFetchFailureCategory.REQUEST_TIMEOUT,
                )
            try:
                safe_url, address = resolve_public_url(
                    current,
                    resolver=self._resolver,
                )
            except UnsafeUrlError as exc:
                raise SourceFetchError(
                    str(exc),
                    category=SourceFetchFailureCategory.UNSAFE_URL,
                ) from exc
            parsed = urlsplit(safe_url)
            ip = ipaddress.ip_address(address)
            pinned_host = f"[{ip.compressed}]" if ip.version == 6 else ip.compressed
            pinned_url = urlunsplit(
                (
                    parsed.scheme,
                    pinned_host,
                    parsed.path,
                    parsed.query,
                    "",
                )
            )
            request = self._client.build_request(
                "GET",
                pinned_url,
                headers={
                    "Host": parsed.netloc,
                    "Accept-Encoding": "identity",
                    "User-Agent": "x402-watch/0.1 (+local research client)",
                },
            )
            if _is_dns_name(parsed.hostname):
                request.extensions["sni_hostname"] = parsed.hostname.encode("idna")
            try:
                with closing(
                    self._client.send(
                        request,
                        stream=True,
                        follow_redirects=False,
                    )
                ) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise SourceFetchError(
                                "Source redirect omitted its target",
                                category=(
                                    SourceFetchFailureCategory.REDIRECT_MISSING_TARGET
                                ),
                            )
                        if redirect_count == self._max_redirects:
                            raise SourceFetchError(
                                "Source exceeded the redirect limit",
                                category=SourceFetchFailureCategory.REDIRECT_LIMIT,
                            )
                        current = urljoin(safe_url, location)
                        continue
                    if response.status_code < 200 or response.status_code >= 300:
                        raise SourceFetchError(
                            f"Source returned HTTP {response.status_code}",
                            category=SourceFetchFailureCategory.HTTP_STATUS,
                            status_code=response.status_code,
                        )
                    content_type = response.headers.get("content-type", "").lower()
                    if not content_type.startswith(
                        ("text/html", "application/xhtml+xml")
                    ):
                        raise SourceFetchError(
                            "Source is not an HTML page",
                            category=SourceFetchFailureCategory.NON_HTML_CONTENT,
                        )
                    content_encoding = response.headers.get(
                        "content-encoding",
                        "identity",
                    ).strip().lower()
                    if content_encoding not in {"", "identity"}:
                        raise SourceFetchError(
                            "Compressed source responses are not supported",
                            category=SourceFetchFailureCategory.COMPRESSED_RESPONSE,
                        )
                    content_length = response.headers.get("content-length")
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
                                category=SourceFetchFailureCategory.RESPONSE_TOO_LARGE,
                            )
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        if monotonic() >= deadline:
                            raise SourceFetchError(
                                "Source request exceeded the time limit",
                                category=SourceFetchFailureCategory.REQUEST_TIMEOUT,
                            )
                        body.extend(chunk)
                        if len(body) > self._max_bytes:
                            raise SourceFetchError(
                                "Source exceeded the byte limit",
                                category=SourceFetchFailureCategory.RESPONSE_TOO_LARGE,
                            )
                    return FetchedPage(
                        url=safe_url,
                        html=bytes(body),
                        content_type=content_type,
                    )
            except httpx.TimeoutException as exc:
                raise SourceFetchError(
                    "Source request timed out",
                    category=SourceFetchFailureCategory.REQUEST_TIMEOUT,
                ) from exc
            except httpx.HTTPError as exc:
                raise SourceFetchError(
                    "Public source request failed",
                    category=SourceFetchFailureCategory.REQUEST_FAILED,
                ) from exc
        raise SourceFetchError(
            "Source redirect handling failed",
            category=SourceFetchFailureCategory.REDIRECT_HANDLING_FAILED,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

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
    "PublicPageFetcher",
    "SourceExtractionError",
    "SourceFetchError",
    "SourceFetchFailureCategory",
    "extract_source",
]


def _is_dns_name(host: str | None) -> bool:
    if host is None:
        return False
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return True
    return False
