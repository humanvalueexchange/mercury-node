"""Thin client for the hailo-ollama HTTP dialect."""

from __future__ import annotations

import json
from typing import Any

import httpx


class HailoClient:
    def __init__(self, base: str, model: str, timeout: float = 2.5) -> None:
        self.base = base.rstrip("/")
        self.model = model
        self.timeout = timeout

    def healthy(self) -> bool:
        try:
            response = httpx.get(f"{self.base}/api/tags", timeout=0.4)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def chat(
        self, messages: list[dict[str, str]], num_predict: int = 200
    ) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"num_predict": num_predict, "temperature": 0.2},
        }
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
        required = {"intent", "need_tools", "risks", "bullets", "answer_sketch", "recommended_action"}
        if not required.issubset(value):
            return None
        if value["intent"] not in {"rebalance", "liquidity", "status", "pay", "invoice", "other"}:
            return None
        if value["recommended_action"] not in {"observe", "recommend", "requires_human_confirm"}:
            return None
        if not all(isinstance(value[key], list) for key in ("need_tools", "risks", "bullets")):
            return None
        return value
