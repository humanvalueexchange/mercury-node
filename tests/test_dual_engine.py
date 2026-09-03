import asyncio
import unittest
from types import SimpleNamespace

from mercury_cli.ai.engine import DualEngine
from mercury_cli.ai.hailo_client import HailoClient
from mercury_cli.ai.snapshot import SnapshotBuilder


PLAN = {
    "intent": "liquidity",
    "need_tools": ["channels"],
    "risks": [],
    "bullets": ["No active channels"],
    "answer_sketch": "There is no channel to rebalance.",
    "recommended_action": "observe",
}


class FakeHailo:
    def __init__(self, value=PLAN, error=None):
        self.value, self.error = value, error

    async def chat(self, *_args, **_kwargs):
        if self.error:
            raise self.error
        return "ignored"

    @staticmethod
    def parse_plan(_text):
        return PLAN


class FakeLlama:
    def __init__(self, value="Draft", error=None):
        self.value, self.error = value, error
        self.calls = 0

    async def chat(self, *_args, **_kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self.value


class DualEngineTests(unittest.TestCase):
    def test_parse_plan_rejects_incomplete_json(self):
        self.assertEqual(HailoClient.parse_plan("```json\n" + str(PLAN) + "\n```"), None)
        self.assertEqual(HailoClient.parse_plan('{"intent":"liquidity"}'), None)

    def test_hailo_failure_returns_draft(self):
        result = asyncio.run(DualEngine(FakeHailo(error=RuntimeError()), FakeLlama()).ask("q", {}))
        self.assertEqual(result.source, "draft")

    def test_cpu_failure_returns_plan_sketch(self):
        result = asyncio.run(DualEngine(FakeHailo(), FakeLlama(error=RuntimeError())).ask("q", {}))
        self.assertEqual(result.source, "plan")
        self.assertIn("no channel", result.text.lower())

    def test_both_failures_are_unavailable(self):
        result = asyncio.run(
            DualEngine(FakeHailo(error=RuntimeError()), FakeLlama(error=RuntimeError())).ask("q", {})
        )
        self.assertEqual(result.source, "unavailable")

    def test_snapshot_is_bounded_and_marks_zero_channels(self):
        config = SimpleNamespace(agent_url="http://127.0.0.1:8088")
        builder = SnapshotBuilder(
            config,
            agent_get=lambda path: {"node": {"block_height": 1, "synced_to_chain": True}}
            if path.endswith("status")
            else {"active": []},
        )
        snapshot = builder.build()
        self.assertLessEqual(len(__import__("json").dumps(snapshot, separators=(",", ":"))), 4096)
        self.assertIn("zero_channels", snapshot["notes"])


if __name__ == "__main__":
    unittest.main()
