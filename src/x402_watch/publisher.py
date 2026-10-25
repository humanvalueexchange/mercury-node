"""Repository-scoped GitHub App publisher for private daily briefs."""

from __future__ import annotations

import base64
import re
import time
from datetime import date
from typing import Self
from urllib.parse import urlsplit

import httpx
import jwt

from .config import ConfigurationError, Settings


class GitHubPublishError(RuntimeError):
    """Raised when scoped GitHub publication fails."""


class GitHubAppPublisher:
    def __init__(self, settings: Settings, *, client: httpx.Client | None = None):
        settings.validate_publisher()
        try:
            api = urlsplit(settings.github_api)
            api_port = api.port
        except ValueError as exc:
            raise ConfigurationError("GitHub API URL is invalid") from exc
        if (
            api.scheme.lower() != "https"
            or api.hostname != "api.github.com"
            or api.path not in {"", "/"}
            or api.username is not None
            or api.password is not None
            or api_port not in {None, 443}
            or api.query
            or api.fragment
        ):
            raise ConfigurationError("Publisher must use the official GitHub API")
        self._settings = settings
        self._api_root = "https://api.github.com"
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=30,
            trust_env=False,
            follow_redirects=False,
        )

    def publish(self, brief_date: date, markdown: str) -> str:
        path = f"briefs/{brief_date.isoformat()}.md"
        if not re.fullmatch(r"briefs/\d{4}-\d{2}-\d{2}\.md", path):
            raise GitHubPublishError("Brief path is invalid")
        token = self._installation_token()
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        repository_url = (
            f"{self._api_root}/repos/{self._settings.github_owner}/"
            f"{self._settings.github_repo}"
        )
        repository = self._api_request("GET", repository_url, headers=headers)
        if repository.status_code != 200:
            raise GitHubPublishError(
                f"GitHub repository verification returned HTTP {repository.status_code}"
            )
        try:
            is_private = repository.json()["private"] is True
        except (KeyError, TypeError, ValueError) as exc:
            raise GitHubPublishError(
                "GitHub returned an invalid repository visibility response"
            ) from exc
        if not is_private:
            raise GitHubPublishError("The target repository is not private")

        content_url = (
            f"{self._api_root}/repos/{self._settings.github_owner}/"
            f"{self._settings.github_repo}/contents/{path}"
        )
        params = {"ref": self._settings.github_branch}
        existing = self._api_request(
            "GET",
            content_url,
            headers=headers,
            params=params,
        )
        sha: str | None = None
        if existing.status_code == 200:
            try:
                sha = existing.json()["sha"]
            except (KeyError, TypeError, ValueError) as exc:
                raise GitHubPublishError(
                    "GitHub returned an invalid existing-file response"
                ) from exc
            if not isinstance(sha, str) or not sha:
                raise GitHubPublishError("GitHub returned an invalid file SHA")
        elif existing.status_code != 404:
            raise GitHubPublishError(
                f"GitHub content lookup returned HTTP {existing.status_code}"
            )

        body = {
            "message": f"Publish x402 Watch brief {brief_date.isoformat()}",
            "content": base64.b64encode(markdown.encode("utf-8")).decode("ascii"),
            "branch": self._settings.github_branch,
        }
        if sha is not None:
            body["sha"] = sha
        response = self._api_request(
            "PUT",
            content_url,
            headers=headers,
            json=body,
        )
        if response.status_code not in {200, 201}:
            raise GitHubPublishError(
                f"GitHub content write returned HTTP {response.status_code}"
            )
        try:
            commit = response.json()["commit"]["sha"]
        except (KeyError, TypeError, ValueError) as exc:
            raise GitHubPublishError("GitHub returned an invalid commit response") from exc
        if not isinstance(commit, str) or not commit:
            raise GitHubPublishError("GitHub returned an invalid commit SHA")
        return commit

    def _installation_token(self) -> str:
        private_key = self._settings.credential("github_app_private_key")
        now = int(time.time())
        try:
            app_jwt = jwt.encode(
                {
                    "iat": now - 60,
                    "exp": now + 540,
                    "iss": self._settings.github_app_id,
                },
                private_key,
                algorithm="RS256",
            )
        except (jwt.PyJWTError, TypeError, ValueError) as exc:
            raise GitHubPublishError("GitHub App signing key is invalid") from exc
        url = (
            f"{self._api_root}/app/installations/"
            f"{self._settings.github_installation_id}/access_tokens"
        )
        try:
            response = self._api_request(
                "POST",
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {app_jwt}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json={
                    "repositories": [self._settings.github_repo],
                    "permissions": {"contents": "write"},
                },
            )
        except GitHubPublishError as exc:
            raise GitHubPublishError("GitHub App token request failed") from exc
        if response.status_code != 201:
            raise GitHubPublishError(
                f"GitHub App token request returned HTTP {response.status_code}"
            )
        try:
            token_data = response.json()
            token = token_data["token"]
            selection = token_data["repository_selection"]
            repositories = token_data["repositories"]
            permissions = token_data["permissions"]
        except (KeyError, TypeError, ValueError) as exc:
            raise GitHubPublishError("GitHub returned an invalid App token response") from exc
        if not isinstance(token, str) or not token:
            raise GitHubPublishError("GitHub returned an invalid App token")
        target = f"{self._settings.github_owner}/{self._settings.github_repo}".casefold()
        if (
            selection != "selected"
            or not isinstance(repositories, list)
            or len(repositories) != 1
            or not isinstance(repositories[0], dict)
            or not isinstance(repositories[0].get("full_name"), str)
            or repositories[0]["full_name"].casefold() != target
        ):
            raise GitHubPublishError(
                "GitHub App token is not restricted to the target repository"
            )
        if (
            not isinstance(permissions, dict)
            or permissions.get("contents") != "write"
            or any(
                name not in {"contents", "metadata"}
                or (name == "metadata" and value != "read")
                for name, value in permissions.items()
            )
        ):
            raise GitHubPublishError(
                "GitHub App token has unexpected repository permissions"
            )
        return token

    def _api_request(self, method: str, url: str, **kwargs) -> httpx.Response:
        try:
            return self._client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise GitHubPublishError("GitHub API request failed") from exc

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


__all__ = ["GitHubAppPublisher", "GitHubPublishError"]
