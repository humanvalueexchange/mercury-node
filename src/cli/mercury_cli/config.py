"""Configuration primitives for the Mercury command-line tools."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


LND_DIR = "/var/lib/lnd"
LND_USER = "lnd"
AGENT_URL = "http://localhost:8088"
LOCAL_LLM_URL = "http://127.0.0.1:8089"
LOCAL_LLM_MODEL = "/opt/mercury/models/Qwen3.8-2B-Distill-Q4_K_M.gguf"
BACKUP_DIR = "/var/lib/mercury/backups"
OLLAMA_URL = "http://10.0.0.79:11434"
OLLAMA_MODEL = "qwen2.5:14b"


@dataclass(frozen=True)
class MercuryConfig:
    """Immutable paths and service endpoints used by Mercury."""

    lnd_dir: Path = Path(LND_DIR)
    agent_url: str = AGENT_URL
    local_llm_url: str = LOCAL_LLM_URL
    model_path: Path = Path(LOCAL_LLM_MODEL)
    backup_path: Path = Path(BACKUP_DIR)
    ollama_url: str = OLLAMA_URL
    ollama_model: str = OLLAMA_MODEL
    lnd_user: str = LND_USER

    def __post_init__(self) -> None:
        """Normalize path-like values without requiring a path library."""
        object.__setattr__(self, "lnd_dir", Path(self.lnd_dir))
        object.__setattr__(self, "model_path", Path(self.model_path))
        object.__setattr__(self, "backup_path", Path(self.backup_path))

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "MercuryConfig":
        """Load supported overrides, retaining Mercury's existing defaults."""
        env = os.environ if environ is None else environ
        return cls(
            local_llm_url=env.get("MERCURY_LOCAL_LLM_URL", LOCAL_LLM_URL),
            model_path=env.get("MERCURY_LOCAL_LLM_MODEL", LOCAL_LLM_MODEL),
            ollama_url=env.get("MERCURY_OLLAMA_URL", OLLAMA_URL),
            ollama_model=env.get("MERCURY_OLLAMA_MODEL", OLLAMA_MODEL),
        )

    from_environment = from_env

    @property
    def local_llm_model(self) -> Path:
        """Compatibility name for the configured local model path."""
        return self.model_path

    @property
    def backup_dir(self) -> Path:
        """Compatibility name for the configured backup directory."""
        return self.backup_path


def load_config(environ: Mapping[str, str] | None = None) -> MercuryConfig:
    """Return a fresh configuration snapshot from the process environment."""
    return MercuryConfig.from_env(environ)


Config = MercuryConfig

__all__ = [
    "AGENT_URL",
    "BACKUP_DIR",
    "Config",
    "LOCAL_LLM_MODEL",
    "LOCAL_LLM_URL",
    "LND_DIR",
    "LND_USER",
    "MercuryConfig",
    "OLLAMA_MODEL",
    "OLLAMA_URL",
    "load_config",
]
