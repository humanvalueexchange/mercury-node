"""Bounded line-protocol client for the credential-free Hailo worker process."""

from __future__ import annotations

import json
import selectors
import subprocess
from pathlib import Path
from typing import Self

from .config import Settings
from .models import HailoTag, SearchHit


class HailoWorkerError(RuntimeError):
    """Raised when the optional local Hailo triage worker is unavailable."""


class HailoWorker:
    def __init__(self, settings: Settings, timeout: float = 45.0):
        self._settings = settings
        self._timeout = timeout
        self._process: subprocess.Popen[str] | None = None
        self._selector: selectors.BaseSelector | None = None

    def start(self) -> None:
        if not self._settings.hailo_python.is_file():
            raise HailoWorkerError("Configured system Python for Hailo is missing")
        if not self._settings.hailo_model.is_file():
            raise HailoWorkerError("Configured Hailo HEF model is missing")
        home = self._settings.data_dir / "hailo-home"
        try:
            home.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HailoWorkerError(
                "Could not prepare the isolated Hailo worker home"
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
            raise HailoWorkerError("Could not start the Hailo worker") from exc
        try:
            if self._process.stdout is None:
                raise HailoWorkerError(
                    "Hailo worker protocol pipe could not be created"
                )
            self._selector = selectors.DefaultSelector()
            self._selector.register(self._process.stdout, selectors.EVENT_READ)
            ready = self._read_response()
            if ready != {"ready": True}:
                raise HailoWorkerError("Hailo worker did not report readiness")
        except (HailoWorkerError, OSError):
            self.stop()
            raise

    def classify(self, hit: SearchHit) -> HailoTag:
        process = self._process
        if process is None or process.stdin is None:
            raise HailoWorkerError("Hailo worker has not been started")
        request = json.dumps(
            {"title": hit.title[:500], "snippet": hit.snippet[:1200]},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            process.stdin.write(request + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise HailoWorkerError("Hailo worker input pipe failed") from exc
        response = self._read_response()
        if response.get("ok") is not True:
            raise HailoWorkerError("Hailo worker returned an inference error")
        try:
            return HailoTag.model_validate(response.get("tag"))
        except ValueError as exc:
            raise HailoWorkerError("Hailo worker returned an invalid tag") from exc

    def _read_response(self) -> dict:
        process = self._process
        if process is None or process.stdout is None or self._selector is None:
            raise HailoWorkerError("Hailo worker is not running")
        if process.poll() is not None:
            raise HailoWorkerError(
                f"Hailo worker exited ({process.returncode})"
            )
        events = self._selector.select(self._timeout)
        if not events:
            raise HailoWorkerError("Hailo worker timed out")
        line = process.stdout.readline()
        try:
            response = json.loads(line)
        except json.JSONDecodeError as exc:
            raise HailoWorkerError("Hailo worker returned malformed protocol data") from exc
        if not isinstance(response, dict):
            raise HailoWorkerError("Hailo worker returned an invalid protocol response")
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
