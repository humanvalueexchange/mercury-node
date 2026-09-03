import asyncio
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path

from mercury_cli.ai.engine import DualEngine
from mercury_cli.ai.fast_path import deterministic_reply
from mercury_cli.ai.hailo_client import HailoClient
from mercury_cli.ai.snapshot import SnapshotBuilder, prompt_snapshot


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


class SlowLlama(FakeLlama):
    async def chat(self, *_args, **_kwargs):
        self.calls += 1
        await asyncio.sleep(20)
        return self.value


class FailingMergeLlama(FakeLlama):
    async def chat(self, *_args, **_kwargs):
        self.calls += 1
        if self.calls > 1:
            raise RuntimeError("merge failed")
        return self.value


class DualEngineTests(unittest.TestCase):
    def test_hailo_ready_requires_marker_and_service(self):
        with tempfile.TemporaryDirectory() as directory:
            client = HailoClient("http://127.0.0.1:8000", "model", ready_file=Path(directory) / "ready")
            client.healthy = lambda: True
            self.assertFalse(client.ready())
            Path(directory, "ready").touch()
            self.assertTrue(client.ready())

    def test_zero_channel_fast_path_uses_snapshot_only(self):
        snapshot = {
            "fresh": True,
            "totals": {"active": 0},
        }
        self.assertIn("No active channels", deterministic_reply("What channels do I have?", snapshot))

    def test_sync_fast_path_requires_complete_fresh_snapshot(self):
        snapshot = {
            "fresh": True,
            "chain": {"height": 100, "synced": True},
            "wallet": {"confirmed_sat": 10, "unconfirmed_sat": 2},
        }
        reply = deterministic_reply("Is the node ready?", snapshot)
        self.assertIn("height 100", reply)
        self.assertIsNone(
            deterministic_reply("Is the node ready?", {**snapshot, "fresh": False})
        )

    def test_liquidity_fast_path_requires_active_channel(self):
        snapshot = {
            "fresh": True,
            "totals": {
                "active": 1,
                "local_sat": 100,
                "remote_sat": 300,
                "inbound_pct": 75.0,
                "outbound_pct": 25.0,
            },
        }
        self.assertIn("75.0% inbound", deterministic_reply(
            "What is my inbound and outbound liquidity?", snapshot
        ))
        self.assertIsNone(
            deterministic_reply("What is my inbound and outbound liquidity?",
                                 {**snapshot, "totals": {**snapshot["totals"], "active": 0}})
        )

    def test_fast_path_is_closed_set(self):
        snapshot = {"fresh": True, "totals": {"active": 0}}
        self.assertIsNone(deterministic_reply("Should I open a channel?", snapshot))

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

    def test_partial_plan_survives_slow_cpu(self):
        result = asyncio.run(
            DualEngine(FakeHailo(), SlowLlama()).ask("q", {})
        )
        self.assertEqual(result.source, "plan")
        self.assertEqual(result.timings_ms["merge_status"], "skipped_partial")

    def test_merge_failure_returns_draft(self):
        result = asyncio.run(
            DualEngine(FakeHailo(), FailingMergeLlama(value="Draft")).ask("q", {})
        )
        self.assertEqual(result.source, "draft")
        self.assertEqual(result.timings_ms["merge_status"], "failed")

    def test_debug_timing_status_has_no_ms_suffix(self):
        from contextlib import redirect_stderr
        from io import StringIO
        from mercury_cli.ai.render import debug_timings

        output = StringIO()
        with redirect_stderr(output):
            debug_timings({"merge_status": "skipped_budget"})
        self.assertIn("merge_status=skipped_budget", output.getvalue())

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

    def test_prompt_snapshot_keeps_facts_and_removes_unused_channel_fields(self):
        snapshot = {
            "chain": {"height": 1, "synced": True},
            "wallet": {"confirmed_sat": 2, "unconfirmed_sat": 3},
            "channels": [{"alias": "peer", "chan_id": "1", "active": True, "initiator": True}],
            "totals": {"active": 1},
            "notes": [],
            "fresh": True,
        }
        projected = prompt_snapshot(snapshot)
        self.assertEqual(projected["channels"][0]["alias"], "peer")
        self.assertNotIn("initiator", projected["channels"][0])
        self.assertEqual(projected["wallet"]["confirmed_sat"], 2)


if __name__ == "__main__":
    unittest.main()
