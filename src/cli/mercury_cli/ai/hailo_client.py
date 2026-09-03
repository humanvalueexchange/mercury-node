"""Thin client for the hailo-ollama HTTP dialect."""

from __future__ import annotations

import json
import asyncio
from pathlib import Path
from typing import Any

import httpx

_hailo_request_lock: asyncio.Lock | None = None
_hailo_request_loop: asyncio.AbstractEventLoop | None = None


def _request_lock() -> asyncio.Lock:
    global _hailo_request_lock, _hailo_request_loop
    loop = asyncio.get_running_loop()
    if _hailo_request_lock is None or _hailo_request_loop is not loop:
        _hailo_request_lock = asyncio.Lock()
        _hailo_request_loop = loop
    return _hailo_request_lock


class HailoClient:
    def __init__(
        self,
        base: str,
        model: str,
        timeout: float = 2.5,
        ready_file: str | Path = "/run/hailo-ollama/ready",
    ) -> None:
        self.base = base.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.ready_file = Path(ready_file)

    def healthy(self) -> bool:
        try:
            response = httpx.get(f"{self.base}/api/tags", timeout=0.4)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    def ready(self) -> bool:
        """Require both an HTTP service and a completed model prewarm."""
        return self.ready_file.is_file() and self.healthy()

    async def chat(
        self, messages: list[dict[str, str]], num_predict: int = 200
    ) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"num_predict": num_predict, "temperature": 0.2},
        }
        async with _request_lock():
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base}/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
        return (data.get("message") or {}).get("content") or data.get("response") or ""

    @staticmethod
    def parse_plan(text: str) -> dict[str, Any] | None:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
        if not isinstance(value, dict):
            return None
        if "recommendation" in value and isinstance(value["recommendation"], dict):
            value["recommendation"] = value["recommendation"].get("action")
        for source, target in {
            "tooling_needed": "need_tools",
            "blist": "bullets",
            "recommendation": "recommended_action",
        }.items():
            if target not in value and source in value:
                value[target] = value[source]
        required = {
            "intent",
            "need_tools",
            "risks",
            "bullets",
            "answer_sketch",
            "recommended_action",
        }
        if not required.issubset(value):
            return None
        if not isinstance(value["intent"], str) or value["intent"] not in {
            "rebalance",
            "liquidity",
            "status",
            "pay",
            "invoice",
            "other",
        }:
            return None
        if (
            not isinstance(value["recommended_action"], str)
            or value["recommended_action"]
            not in {"observe", "recommend", "requires_human_confirm"}
        ):
            return None
        if not isinstance(value["answer_sketch"], str) or len(value["answer_sketch"]) > 400:
            return None
        limits = {"need_tools": 3, "risks": 5, "bullets": 5}
        allowed_tools = {"channels", "payments", "routing"}
        for key, limit in limits.items():
            items = value[key]
            if (
                not isinstance(items, list)
                or len(items) > limit
                or not all(isinstance(item, str) and len(item) <= 160 for item in items)
            ):
                return None
            if key == "need_tools" and not set(items).issubset(allowed_tools):
                return None
        return {
            "intent": value["intent"],
            "need_tools": value["need_tools"],
            "risks": value["risks"],
            "bullets": value["bullets"],
            "answer_sketch": value["answer_sketch"],
            "recommended_action": value["recommended_action"],
        }
