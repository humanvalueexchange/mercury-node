"""Configuration and protected credential loading for x402 Watch."""

from __future__ import annotations

import ipaddress
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


class ConfigurationError(ValueError):
    """Raised when required local configuration is missing or unsafe."""


def _loopback_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise ConfigurationError("The llama.cpp endpoint is invalid") from exc
    if parsed.scheme.lower() != "http" or not parsed.hostname:
        raise ConfigurationError("The llama.cpp endpoint must be an HTTP loopback URL")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ConfigurationError("The llama.cpp endpoint has an invalid port") from exc
    if (
        parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or port is None
        or port < 1024
    ):
        raise ConfigurationError(
            "The llama.cpp endpoint must use a non-privileged port without a path"
        )
    hostname = parsed.hostname.lower()
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if parsed.username is not None or parsed.password is not None or (
        address is None and hostname != "localhost"
    ):
        raise ConfigurationError("The llama.cpp endpoint must be loopback-only")
    if address is not None and not address.is_loopback:
        raise ConfigurationError("The llama.cpp endpoint must be loopback-only")
    if address is not None and getattr(address, "scope_id", None) is not None:
        raise ConfigurationError("Scoped IPv6 loopback endpoints are not supported")
    host = "127.0.0.1" if address is None else address.compressed
    authority = f"[{host}]" if ":" in host else host
    return f"http://{authority}:{port or 80}"


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("/var/lib/x402-watch")
    llama_server: Path = Path("/opt/x402-watch/llama.cpp/build/bin/llama-server")
    llama_model: Path = Path("/opt/x402-watch/models/Qwen3-4B-Q4_K_M.gguf")
    llama_url: str = "http://127.0.0.1:8090"
    hailo_python: Path = Path("/usr/bin/python3")
    hailo_model: Path = Path(
        "/opt/x402-watch/models/Qwen2.5-1.5B-Instruct-v5.1.1.hef"
    )
    credentials_dir: Path | None = None
    brave_endpoint: str = "https://api.search.brave.com/res/v1/web/search"
    github_api: str = "https://api.github.com"
    github_owner: str = "HansHWestphal"
    github_repo: str = "x402-watch"
    github_branch: str = "main"
    github_app_id: str = ""
    github_installation_id: str = ""
    publish_enabled: bool = False
    max_search_results: int = 5
    max_source_bytes: int = 2_000_000
    max_redirects: int = 4
    fetch_timeout_seconds: float = 20.0
    model_timeout_seconds: float = 2400.0

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> Settings:
        env = os.environ if environ is None else environ
        credential_dir = env.get(
            "CREDENTIALS_DIRECTORY",
            env.get("X402_WATCH_CREDENTIALS_DIR", ""),
        )
        return cls(
            data_dir=Path(env.get("X402_WATCH_DATA_DIR", "/var/lib/x402-watch")),
            llama_server=Path(
                env.get(
                    "X402_WATCH_LLAMA_SERVER",
                    "/opt/x402-watch/llama.cpp/build/bin/llama-server",
                )
            ),
            llama_model=Path(
                env.get(
                    "X402_WATCH_LLAMA_MODEL",
                    "/opt/x402-watch/models/Qwen3-4B-Q4_K_M.gguf",
                )
            ),
            llama_url=_loopback_url(
                env.get("X402_WATCH_LLAMA_URL", "http://127.0.0.1:8090")
            ),
            hailo_python=Path(
                env.get("X402_WATCH_HAILO_PYTHON", "/usr/bin/python3")
            ),
            hailo_model=Path(
                env.get(
                    "X402_WATCH_HAILO_MODEL",
                    "/opt/x402-watch/models/Qwen2.5-1.5B-Instruct-v5.1.1.hef",
                )
            ),
            credentials_dir=Path(credential_dir) if credential_dir else None,
            brave_endpoint=env.get(
                "X402_WATCH_BRAVE_ENDPOINT",
                "https://api.search.brave.com/res/v1/web/search",
            ),
            github_api=env.get("X402_WATCH_GITHUB_API", "https://api.github.com").rstrip(
                "/"
            ),
            github_owner=env.get("X402_WATCH_GITHUB_OWNER", "HansHWestphal"),
            github_repo=env.get("X402_WATCH_GITHUB_REPO", "x402-watch"),
            github_branch=env.get("X402_WATCH_GITHUB_BRANCH", "main"),
            github_app_id=env.get("X402_WATCH_GITHUB_APP_ID", ""),
            github_installation_id=env.get(
                "X402_WATCH_GITHUB_INSTALLATION_ID", ""
            ),
            publish_enabled=env.get(
                "X402_WATCH_PUBLISH_ENABLED", ""
            ).lower()
            in {"1", "true", "yes"},
        )

    @property
    def database_path(self) -> Path:
        return self.data_dir / "x402-watch.sqlite3"

    @property
    def outbox_dir(self) -> Path:
        return self.data_dir / "outbox"

    def credential(self, name: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name):
            raise ConfigurationError("Invalid credential name")
        if self.credentials_dir is None:
            raise ConfigurationError("Systemd credentials are not configured")
        path = self.credentials_dir / name
        try:
            value = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            raise ConfigurationError(
                f"Required systemd credential is unavailable: {name}"
            ) from exc
        if not value:
            raise ConfigurationError(f"Required systemd credential is empty: {name}")
        return value

    def validate_publisher(self) -> None:
        if not self.publish_enabled:
            raise ConfigurationError("Publishing is disabled by default")
        if not self.github_app_id or not self.github_installation_id:
            raise ConfigurationError("GitHub App identifiers are not configured")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", self.github_owner):
            raise ConfigurationError("Invalid GitHub owner")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", self.github_repo):
            raise ConfigurationError("Invalid GitHub repository")
        if not re.fullmatch(r"[1-9][0-9]*", self.github_app_id):
            raise ConfigurationError("Invalid GitHub App ID")
        if not re.fullmatch(r"[1-9][0-9]*", self.github_installation_id):
            raise ConfigurationError("Invalid GitHub installation ID")
        branch_parts = self.github_branch.split("/")
        if (
            not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", self.github_branch)
            or ".." in self.github_branch
            or self.github_branch.endswith(("/", "."))
            or "//" in self.github_branch
            or "@{" in self.github_branch
            or any(
                part.startswith(".") or part.endswith(".lock")
                for part in branch_parts
            )
        ):
            raise ConfigurationError("Invalid GitHub branch name")


__all__ = ["ConfigurationError", "Settings"]
