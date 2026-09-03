"""Thin client for the llama-server OpenAI-compatible HTTP dialect."""

from __future__ import annotations

import httpx


class LlamaClient:
    def __init__(self, base: str, model: str, timeout: float = 8.0) -> None:
        self.base = base.rstrip("/")
        self.model = model
        self.timeout = timeout

    def healthy(self) -> bool:
        try:
            response = httpx.get(f"{self.base}/v1/models", timeout=0.4)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    async def chat(
        self, messages: list[dict[str, str]], max_tokens: int = 256
    ) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base}/v1/chat/completions", json=payload
            )
            response.raise_for_status()
            data = response.json()
        return data["choices"][0]["message"]["content"]
