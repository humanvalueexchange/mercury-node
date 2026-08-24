"""Small, read-only adapter around the LND ``lncli`` executable."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeAlias, TypeVar, cast

from .config import MercuryConfig


JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]
T = TypeVar("T")


class LncliError(RuntimeError):
    """Base exception for failures talking to LND through ``lncli``."""


class LncliNotFoundError(LncliError):
    """Raised when ``lncli`` is not available on PATH."""


class LncliTimeoutError(LncliError):
    """Raised when an ``lncli`` command exceeds its timeout."""


class LncliCommandError(LncliError):
    """Raised when ``lncli`` exits unsuccessfully."""

    def __init__(
        self,
        command: tuple[str, ...],
        returncode: int,
        stderr: str,
        stdout: str,
    ) -> None:
        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        self.stdout = stdout
        detail = stderr or stdout or f"exit status {returncode}"
        super().__init__(f"{' '.join(command)}: {detail}")


class LncliJSONError(LncliError):
    """Raised when successful ``lncli`` output is not valid JSON."""

    def __init__(self, command: tuple[str, ...], stdout: str, cause: json.JSONDecodeError):
        self.command = command
        self.stdout = stdout
        self.cause = cause
        super().__init__(f"{' '.join(command)}: invalid JSON: {cause}")


class LncliResponseError(LncliError):
    """Raised when a helper receives a JSON value of the wrong shape."""


@dataclass(frozen=True)
class LncliResult(Generic[T]):
    """Parsed command output together with process diagnostics."""

    data: T
    command: tuple[str, ...]
    stdout: str
    stderr: str = ""
    returncode: int = 0

    @property
    def value(self) -> T:
        """Alias for callers that prefer value-oriented result naming."""
        return self.data

    @property
    def json(self) -> T:
        """Alias exposing the parsed JSON payload."""
        return self.data

    def __getitem__(self, key: str) -> JsonValue:
        """Allow convenient access to object payloads without hiding metadata."""
        return cast(JsonObject, self.data)[key]


class LndClient:
    """Invoke read-only LND RPC commands without invoking a shell."""

    def __init__(
        self,
        config: MercuryConfig | None = None,
        *,
        executable: str | os.PathLike[str] = "lncli",
        command_prefix: tuple[str, ...] = (),
        timeout: float = 15.0,
        lnd_dir: str | os.PathLike[str] | None = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.config = config or MercuryConfig.from_env()
        self.executable = os.fspath(executable)
        self.command_prefix = tuple(command_prefix)
        self.lnd_dir = Path(lnd_dir) if lnd_dir is not None else self.config.lnd_dir
        self.timeout = timeout

    def run(self, *args: str, timeout: float | None = None) -> LncliResult[JsonValue]:
        """Run ``lncli --lnddir=...`` and parse its JSON response."""
        command = (
            *self.command_prefix,
            self.executable,
            f"--lnddir={self.lnd_dir}",
            *args,
        )
        try:
            completed = subprocess.run(
                list(command),
                capture_output=True,
                text=True,
                timeout=self.timeout if timeout is None else timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise LncliNotFoundError(f"{self.executable} is not available") from exc
        except subprocess.TimeoutExpired as exc:
            raise LncliTimeoutError(
                f"{' '.join(command)} exceeded {self.timeout if timeout is None else timeout}s"
            ) from exc

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        if completed.returncode:
            raise LncliCommandError(command, completed.returncode, stderr, stdout)
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise LncliJSONError(command, stdout, exc) from exc
        return LncliResult(payload, command, stdout, stderr, completed.returncode)

    def _object(self, *args: str, timeout: float | None = None) -> LncliResult[JsonObject]:
        result = self.run(*args, timeout=timeout)
        if not isinstance(result.data, dict):
            raise LncliResponseError(
                f"{' '.join(result.command)} returned {type(result.data).__name__}, expected object"
            )
        return cast(LncliResult[JsonObject], result)

    def getinfo(self) -> LncliResult[JsonObject]:
        """Return node identity, version, and synchronization information."""
        return self._object("getinfo")

    def walletbalance(self) -> LncliResult[JsonObject]:
        """Return on-chain wallet balances."""
        return self._object("walletbalance")

    def listchannels(self) -> LncliResult[JsonObject]:
        """Return the node's public channel list."""
        return self._object("listchannels")

    def pendingchannels(self) -> LncliResult[JsonObject]:
        """Return channels that are opening or closing."""
        return self._object("pendingchannels")

    def invoices(
        self,
        last: int | None = None,
        *,
        pending_only: bool | None = None,
    ) -> LncliResult[JsonObject]:
        """Return invoices, optionally limited or restricted to pending ones."""
        args: list[str] = ["listinvoices"]
        if last is not None:
            if last < 0:
                raise ValueError("last must not be negative")
            args.append(f"--max_invoices={last}")
        if pending_only is not None:
            args.append(f"--pending_only={'true' if pending_only else 'false'}")
        return self._object(*args)

    def peers(self) -> LncliResult[JsonObject]:
        """Return currently connected Lightning peers."""
        return self._object("listpeers")

    def forwarding_history(
        self,
        *,
        days: int | None = None,
        limit: int | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> LncliResult[JsonObject]:
        """Return forwarding events with optional time and count filters."""
        if days is not None and start_time is not None:
            raise ValueError("specify either days or start_time, not both")
        if days is not None and days < 0:
            raise ValueError("days must not be negative")
        if limit is not None and limit < 0:
            raise ValueError("limit must not be negative")
        args: list[str] = ["fwdinghistory"]
        if days is not None:
            start_time = f"-{days}d"
        if start_time is not None:
            args.append(f"--start_time={start_time}")
        if end_time is not None:
            args.append(f"--end_time={end_time}")
        if limit is not None:
            args.append(f"--max_events={limit}")
        return self._object(*args)

    # Verbose aliases mirror the command names while remaining pleasant to call.
    get_info = getinfo
    wallet_balance = walletbalance
    list_channels = listchannels
    pending_channels = pendingchannels
    list_invoices = invoices
    list_peers = peers
    listinvoices = invoices
    listpeers = peers
    forwardinghistory = forwarding_history
    fwdinghistory = forwarding_history
    execute = run
    command = run


LndAdapter = LndClient
LNDClient = LndClient
LNDAdapter = LndClient

__all__ = [
    "JsonObject",
    "JsonValue",
    "LndAdapter",
    "LndClient",
    "LNDClient",
    "LNDAdapter",
    "LncliCommandError",
    "LncliError",
    "LncliJSONError",
    "LncliNotFoundError",
    "LncliResponseError",
    "LncliResult",
    "LncliTimeoutError",
]
