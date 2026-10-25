"""Brave Search API client with bounded, validated result handling."""

from __future__ import annotations

from typing import Any, Self
from urllib.parse import urlsplit

import httpx

from .config import ConfigurationError
from .models import SearchHit


class SearchError(RuntimeError):
    """Raised when Brave search fails or returns an invalid response."""


_BRAVE_SEARCH_ENDPOINT = "https://api.search.brave.com/res/v1/web/search"


class BraveSearchClient:
    def __init__(
        self,
        api_key: str,
        endpoint: str = "https://api.search.brave.com/res/v1/web/search",
        *,
        client: httpx.Client | None = None,
        timeout: float = 20.0,
    ):
        if not api_key.strip():
            raise ValueError("A Brave API key is required")
        try:
            parsed_endpoint = urlsplit(endpoint)
            endpoint_port = parsed_endpoint.port
        except ValueError as exc:
            raise ConfigurationError("The Brave endpoint is invalid") from exc
        if (
            parsed_endpoint.scheme.lower() != "https"
            or parsed_endpoint.hostname != "api.search.brave.com"
            or parsed_endpoint.path != "/res/v1/web/search"
            or parsed_endpoint.username is not None
            or parsed_endpoint.password is not None
            or endpoint_port not in {None, 443}
            or parsed_endpoint.query
            or parsed_endpoint.fragment
        ):
            raise ConfigurationError(
                "Brave credentials may only be sent to the official Brave Search API"
            )
        self._api_key = api_key
        self._endpoint = _BRAVE_SEARCH_ENDPOINT
        self._timeout = timeout
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=timeout,
            trust_env=False,
            follow_redirects=False,
        )

    def search(
        self,
        query: str,
        count: int = 5,
        freshness: str = "pd",
    ) -> list[SearchHit]:
        if not query.strip() or not 1 <= count <= 20:
            raise ValueError("Search query and result count are invalid")
        if freshness not in {"pd", "pw", "pm", "py"}:
            raise ValueError("Search freshness must be a supported Brave interval")
        try:
            response = self._client.get(
                self._endpoint,
                params={"q": query, "count": count, "freshness": freshness},
                headers={
                    "Accept": "application/json",
                    "X-Subscription-Token": self._api_key,
                },
                timeout=self._timeout,
            )
        except httpx.HTTPError as exc:
            raise SearchError("Brave Search request failed") from exc
        if response.status_code != 200:
            raise SearchError(
                f"Brave Search returned HTTP {response.status_code}"
            )
        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise SearchError("Brave Search returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise SearchError("Brave Search response has an invalid structure")
        web = payload.get("web")
        if not isinstance(web, dict):
            raise SearchError("Brave Search response has no web results")
        results = web.get("results")
        if not isinstance(results, list):
            raise SearchError("Brave Search response has an invalid result list")

        hits: list[SearchHit] = []
        for item in results[:count]:
            if not isinstance(item, dict):
                raise SearchError("Brave Search returned an invalid result")
            title = item.get("title")
            url = item.get("url")
            snippet = item.get("description", "")
            page_age = item.get("page_age")
            if not isinstance(title, str) or not isinstance(url, str):
                raise SearchError("Brave Search result is missing title or URL")
            if not isinstance(snippet, str):
                snippet = ""
            if page_age is not None and not isinstance(page_age, str):
                page_age = None
            try:
                hits.append(
                    SearchHit(
                        title=title[:500],
                        url=url,
                        snippet=snippet[:4000],
                        published_hint=page_age,
                    )
                )
            except ValueError as exc:
                raise SearchError("Brave Search returned an invalid result") from exc
        return hits

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


__all__ = ["BraveSearchClient", "SearchError"]
