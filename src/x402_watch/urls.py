"""URL canonicalization and public-destination checks for source retrieval."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class UnsafeUrlError(ValueError):
    """Raised when a source URL is not safe to fetch."""


_TRACKING_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
}


def canonicalize_url(url: str) -> str:
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in url):
        raise UnsafeUrlError("Source URL contains a control character")
    try:
        parsed = urlsplit(url.strip())
    except ValueError as exc:
        raise UnsafeUrlError("Source URL is malformed") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        raise UnsafeUrlError("Only HTTP(S) source URLs are allowed")
    if not parsed.hostname or parsed.username or parsed.password:
        raise UnsafeUrlError("Source URL has no public host or contains user info")
    host = parsed.hostname.lower().rstrip(".")
    if not host:
        raise UnsafeUrlError("Source URL has no public host or contains user info")
    if ":" not in host:
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise UnsafeUrlError("Source URL has an invalid hostname") from exc
    try:
        port = parsed.port
    except ValueError as exc:
        raise UnsafeUrlError("Source URL has an invalid port") from exc
    if port == 0:
        raise UnsafeUrlError("Source URL has an invalid port")
    if port is not None and not (
        (parsed.scheme.lower() == "http" and port == 80)
        or (parsed.scheme.lower() == "https" and port == 443)
    ):
        raise UnsafeUrlError("Only standard HTTP(S) ports are allowed")
    netloc = f"[{host}]" if ":" in host else host
    if port and port not in {80, 443}:
        netloc = f"{netloc}:{port}"
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_KEYS
    ]
    return urlunsplit(
        (
            parsed.scheme.lower(),
            netloc,
            parsed.path or "/",
            urlencode(query, doseq=True),
            "",
        )
    )


def validate_public_url(
    url: str,
    resolver=socket.getaddrinfo,
) -> str:
    canonical, _ = resolve_public_url(url, resolver=resolver)
    return canonical


def resolve_public_url(
    url: str,
    resolver=socket.getaddrinfo,
) -> tuple[str, str]:
    canonical = canonicalize_url(url)
    parsed = urlsplit(canonical)
    host = parsed.hostname
    if host is None or host in {"localhost"} or host.endswith((".localhost", ".local")):
        raise UnsafeUrlError("Local hostnames are not allowed")
    port = 443 if parsed.scheme == "https" else 80
    try:
        records = resolver(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise UnsafeUrlError("Source hostname could not be resolved") from exc
    addresses: list[str] = []
    for record in records:
        try:
            address = record[4][0]
            ip = ipaddress.ip_address(address)
        except (IndexError, TypeError, ValueError) as exc:
            raise UnsafeUrlError("DNS returned an invalid address") from exc
        if not ip.is_global:
            raise UnsafeUrlError("Private, reserved, and local destinations are blocked")
        normalized_address = ip.compressed
        if normalized_address not in addresses:
            addresses.append(normalized_address)
    if not addresses:
        raise UnsafeUrlError("Source hostname has no addresses")
    return canonical, addresses[0]


__all__ = [
    "UnsafeUrlError",
    "canonicalize_url",
    "resolve_public_url",
    "validate_public_url",
]
