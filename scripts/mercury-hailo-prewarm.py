#!/opt/mercury/venv/bin/python
"""Prewarm hailo-ollama and publish readiness only after complete inference."""

from __future__ import annotations

import json
import grp
import os
import tempfile
import urllib.request
from pathlib import Path


URL = os.environ.get("MERCURY_HAILO_URL", "http://127.0.0.1:8000")
MODEL = os.environ.get("MERCURY_HAILO_MODEL", "qwen2.5-instruct:1.5b")
READY_FILE = Path(os.environ.get("MERCURY_HAILO_READY_FILE", "/run/hailo-ollama/ready"))


def main() -> int:
    READY_FILE.unlink(missing_ok=True)
    payload = json.dumps(
        {
            "model": MODEL,
            "messages": [{"role": "user", "content": "Return exactly {}."}],
            "stream": False,
            "keep_alive": -1,
            "options": {"num_predict": 1, "temperature": 0},
        }
    ).encode()
    request = urllib.request.Request(
        f"{URL.rstrip('/')}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        if response.status != 200:
            raise RuntimeError(f"Hailo prewarm returned HTTP {response.status}")
        json.loads(response.read())
    READY_FILE.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=READY_FILE.parent, prefix=".ready.", delete=False
    ) as marker:
        marker.write(b"ready\n")
        temporary = Path(marker.name)
    os.chown(temporary, -1, grp.getgrnam("mercury-ready").gr_gid)
    temporary.chmod(0o640)
    temporary.replace(READY_FILE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
