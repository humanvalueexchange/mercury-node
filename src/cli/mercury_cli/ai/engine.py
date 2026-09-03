"""Concurrent Hailo planning, CPU drafting, and local merge orchestration."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from mercury_cli.prompts import DRAFT_SYS, MERGE_SYS, PLAN_SYS


@dataclass(frozen=True)
class AskResult:
    text: str
    source: str
    plan: dict[str, Any] | None = None
    timings_ms: dict[str, int] = field(default_factory=dict)


class DualEngine:
    def __init__(self, hailo: Any, llama: Any, debug: bool = False) -> None:
        self.hailo = hailo
        self.llama = llama
        self.debug = debug

    async def ask(self, question: str, snapshot: dict[str, Any]) -> AskResult:
        user = self._user(question, snapshot)
        started = time.monotonic()
        plan_task = asyncio.create_task(self._plan(user))
        draft_task = asyncio.create_task(self._draft(user))
        plan, draft = await asyncio.gather(plan_task, draft_task, return_exceptions=True)
        plan_obj = plan if isinstance(plan, dict) else None
        draft_text = draft.strip() if isinstance(draft, str) and draft.strip() else None
        timings = {"parallel": round((time.monotonic() - started) * 1000)}

        if plan_obj and draft_text:
            merged = await self._merge(question, snapshot, plan_obj, draft_text)
            if merged:
                return AskResult(merged, "merge", plan_obj, timings)
        if draft_text:
            return AskResult(draft_text, "draft", plan_obj, timings)
        if plan_obj:
            sketch = plan_obj.get("answer_sketch")
            bullets = plan_obj.get("bullets") or []
            text = " ".join([str(sketch)] + [str(item) for item in bullets[:5]]).strip()
            return AskResult(text or "No current recommendation is available.", "plan", plan_obj, timings)
        return AskResult("Mercury AI unavailable (local engines down).", "unavailable", None, timings)

    async def _plan(self, user: str) -> dict[str, Any] | None:
        raw = await asyncio.wait_for(
            self.hailo.chat(
                [{"role": "system", "content": PLAN_SYS}, {"role": "user", "content": user}],
                num_predict=200,
            ),
            timeout=2.5,
        )
        return self.hailo.parse_plan(raw)

    async def _draft(self, user: str) -> str:
        return await asyncio.wait_for(
            self.llama.chat(
                [{"role": "system", "content": DRAFT_SYS}, {"role": "user", "content": user}],
                max_tokens=96,
            ),
            timeout=8,
        )

    async def _merge(
        self, question: str, snapshot: dict[str, Any], plan: dict[str, Any], draft: str
    ) -> str:
        user = (
            f"QUESTION:\n{question}\n\nSNAPSHOT:\n"
            f"{json.dumps(snapshot, separators=(',', ':'))}\n\nPLAN:\n"
            f"{json.dumps(plan, separators=(',', ':'))}\n\nDRAFT:\n{draft}"
        )
        try:
            result = await asyncio.wait_for(
                self.llama.chat(
                    [{"role": "system", "content": MERGE_SYS}, {"role": "user", "content": user}],
                    max_tokens=96,
                ),
                timeout=5,
            )
            return result.strip()
        except (asyncio.TimeoutError, httpx.HTTPError, KeyError, TypeError, ValueError):
            return ""

    @staticmethod
    def _user(question: str, snapshot: dict[str, Any]) -> str:
        return (
            f"QUESTION:\n{question}\n\nSNAPSHOT:\n"
            f"```json\n{json.dumps(snapshot, separators=(',', ':'))}\n```"
        )
