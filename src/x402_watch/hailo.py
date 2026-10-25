"""Bounded line-protocol client for the credential-free Hailo worker process."""

from __future__ import annotations

import json
import re
import selectors
import subprocess
from pathlib import Path
from typing import Self

from .config import Settings
from .models import HailoTag, SearchHit


class HailoWorkerError(RuntimeError):
    """Raised when the optional local Hailo triage worker is unavailable."""

    def __init__(self, message: str, *, diagnostic: str = "worker_error"):
        super().__init__(message)
        self.diagnostic = diagnostic


_DIAGNOSTIC_COMPONENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,79}\Z")
_SECRET_ASSIGNMENT = re.compile(
    r"""(?ix)["']?[\w.-]*(?:api[_-]?key|token|secret|password|credential)"""
    r"""[\w.-]*["']?\s*[:=]\s*["']?[^\s,;:"']+["']?"""
)
_URL = re.compile(r"https?://[^\s,;]+", re.IGNORECASE)
_PATH = re.compile(r"(?<![\w])/(?:[^\s/:]+/)*[^\s,;:)]+")


def _safe_component(value: object, fallback: str) -> str:
    if isinstance(value, str) and _DIAGNOSTIC_COMPONENT.fullmatch(value):
        return value
    return fallback


def _safe_diagnostic_message(
    value: object,
    sensitive_values: tuple[str, ...] = (),
) -> str:
    if not isinstance(value, str):
        return ""
    message = "".join(character for character in value if character.isprintable())
    message = " ".join(message.split())
    for sensitive_value in sensitive_values:
        if sensitive_value:
            message = message.replace(sensitive_value, "<evidence>")
    message = _URL.sub("<url>", message)
    message = _SECRET_ASSIGNMENT.sub("credential=<redacted>", message)
    message = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [redacted]", message)
    message = re.sub(
        r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{16,})\b",
        "<redacted>",
        message,
    )
    message = _PATH.sub("<path>", message)
    message = re.sub(r"\b0x[0-9a-fA-F]+\b", "<address>", message)
    return message[:240]


class HailoWorker:
    def __init__(self, settings: Settings, timeout: float = 45.0):
        self._settings = settings
        self._timeout = timeout
        self._process: subprocess.Popen[str] | None = None
        self._selector: selectors.BaseSelector | None = None

    def start(self) -> None:
        if not self._settings.hailo_python.is_file():
            raise HailoWorkerError(
                "Configured system Python for Hailo is missing",
                diagnostic="configuration:python_missing",
            )
        if not self._settings.hailo_model.is_file():
            raise HailoWorkerError(
                "Configured Hailo HEF model is missing",
                diagnostic="configuration:model_missing",
            )
        home = self._settings.data_dir / "hailo-home"
        try:
            home.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HailoWorkerError(
                "Could not prepare the isolated Hailo worker home",
                diagnostic="configuration:worker_home_failed",
            ) from exc
        source_root = str(Path(__file__).resolve().parents[1])
        environment = {
            "HOME": str(home),
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": source_root,
            "X402_WATCH_HEF_PATH": str(self._settings.hailo_model),
        }
        try:
            self._process = subprocess.Popen(
                [
                    str(self._settings.hailo_python),
                    "-m",
                    "x402_watch.hailo_worker",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=None,
                text=True,
                bufsize=1,
                close_fds=True,
                env=environment,
            )
        except OSError as exc:
            raise HailoWorkerError(
                "Could not start the Hailo worker",
                diagnostic="worker_start:spawn_failed",
            ) from exc
        try:
            if self._process.stdout is None:
                raise HailoWorkerError(
                    "Hailo worker protocol pipe could not be created",
                    diagnostic="protocol:stdout_missing",
                )
            self._selector = selectors.DefaultSelector()
            self._selector.register(self._process.stdout, selectors.EVENT_READ)
            ready = self._read_response()
            if ready != {"ready": True}:
                raise self._worker_error(
                    ready,
                    fallback="worker_start:readiness_failed",
                )
        except (HailoWorkerError, OSError):
            self.stop()
            raise

    def classify(self, hit: SearchHit) -> HailoTag:
        process = self._process
        if process is None or process.stdin is None:
            raise HailoWorkerError(
                "Hailo worker has not been started",
                diagnostic="worker:not_started",
            )
        request = json.dumps(
            {"title": hit.title[:500], "snippet": hit.snippet[:1200]},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            process.stdin.write(request + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise HailoWorkerError(
                "Hailo worker input pipe failed",
                diagnostic="protocol:stdin_failed",
            ) from exc
        response = self._read_response()
        if response.get("ok") is not True:
            raise self._worker_error(
                response,
                fallback="worker_inference:failed",
                sensitive_values=(hit.title, hit.snippet),
            )
        try:
            return HailoTag.model_validate(response.get("tag"))
        except ValueError as exc:
            raise HailoWorkerError(
                "Hailo worker returned an invalid tag",
                diagnostic="tag:invalid_model_output",
            ) from exc

    @staticmethod
    def _worker_error(
        response: dict[str, object],
        *,
        fallback: str,
        sensitive_values: tuple[str, ...] = (),
    ) -> HailoWorkerError:
        error = response.get("error")
        if not isinstance(error, dict):
            return HailoWorkerError(
                "Hailo worker returned an unspecified error",
                diagnostic=fallback,
            )
        stage = _safe_component(error.get("stage"), "worker")
        exception = _safe_component(error.get("exception"), "WorkerError")
        detail = _safe_diagnostic_message(
            error.get("message"),
            sensitive_values=sensitive_values,
        )
        diagnostic = f"{stage}:{exception}"
        if detail:
            diagnostic = f"{diagnostic}: {detail}"
        return HailoWorkerError(
            f"Hailo worker failed ({diagnostic})",
            diagnostic=diagnostic,
        )

    def _read_response(self) -> dict[str, object]:
        process = self._process
        if process is None or process.stdout is None or self._selector is None:
            raise HailoWorkerError(
                "Hailo worker is not running",
                diagnostic="worker:not_running",
            )
        events = self._selector.select(self._timeout)
        if not events:
            returncode = process.poll()
            if returncode is not None:
                raise HailoWorkerError(
                    f"Hailo worker exited ({returncode})",
                    diagnostic=f"worker:exit_{returncode}",
                )
            raise HailoWorkerError(
                "Hailo worker timed out",
                diagnostic="worker:timeout",
            )
        line = process.stdout.readline()
        if not line:
            returncode = process.poll()
            if returncode is not None:
                raise HailoWorkerError(
                    f"Hailo worker exited ({returncode})",
                    diagnostic=f"worker:exit_{returncode}",
                )
            raise HailoWorkerError(
                "Hailo worker closed its protocol pipe",
                diagnostic="protocol:closed",
            )
        try:
            response = json.loads(line)
        except json.JSONDecodeError as exc:
            raise HailoWorkerError(
                "Hailo worker returned malformed protocol data",
                diagnostic="protocol:malformed_json",
            ) from exc
        if not isinstance(response, dict):
            raise HailoWorkerError(
                "Hailo worker returned an invalid protocol response",
                diagnostic="protocol:invalid_response",
            )
        return response

    def stop(self) -> None:
        if self._selector is not None:
            self._selector.close()
            self._selector = None
        process = self._process
        self._process = None
        if process is None:
            return
        if process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.stop()


__all__ = ["HailoWorker", "HailoWorkerError"]
