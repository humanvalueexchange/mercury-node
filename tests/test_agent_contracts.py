import builtins
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


AGENT_PATH = Path(__file__).parents[1] / "src" / "agent" / "main.py"


def load_agent():
    fastapi = types.ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code, detail):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    class FastAPI:
        def __init__(self, *args, **kwargs):
            pass

        def add_middleware(self, *args, **kwargs):
            return None

        def get(self, *args, **kwargs):
            return lambda function: function

        def post(self, *args, **kwargs):
            return lambda function: function

    fastapi.FastAPI = FastAPI
    fastapi.Header = lambda default=None: default
    fastapi.HTTPException = HTTPException
    cors = types.ModuleType("fastapi.middleware.cors")
    cors.CORSMiddleware = object
    middleware = types.ModuleType("fastapi.middleware")
    uvicorn = types.ModuleType("uvicorn")
    uvicorn.run = lambda *args, **kwargs: None

    saved = {
        name: sys.modules.get(name)
        for name in ("fastapi", "fastapi.middleware", "fastapi.middleware.cors", "uvicorn")
    }
    sys.modules.update(
        {
            "fastapi": fastapi,
            "fastapi.middleware": middleware,
            "fastapi.middleware.cors": cors,
            "uvicorn": uvicorn,
        }
    )
    try:
        spec = importlib.util.spec_from_file_location(
            "mercury_agent_test_module", AGENT_PATH
        )
        if spec is None:
            raise RuntimeError("Unable to load agent module")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


agent = load_agent()


class AgentShapingTests(unittest.TestCase):
    def test_tool_catalog_exposes_write_permissions(self):
        result = agent.get_tools()
        tools = {tool["name"]: tool for tool in result["tools"]}
        self.assertEqual(
            tools["payment.pay"]["permission"],
            "explicit_confirmation",
        )
        self.assertIn("channel.rebalance", tools)

    def test_prepare_payment_creates_expiring_plan_without_payment(self):
        decoded = {
            "num_satoshis": "2500",
            "destination": "02" + "a" * 64,
            "description": "agent test",
        }
        with patch.object(agent, "lncli", return_value=decoded) as lncli:
            result = agent.prepare_tool(
                "payment.pay",
                {"bolt11": "lnbc-test"},
            )

        self.assertEqual(result["plan"]["amount_sat"], 2500)
        self.assertTrue(result["requires_confirmation"])
        lncli.assert_called_once_with("decodepayreq", "lnbc-test")

    def test_execute_requires_confirmation_and_does_not_broadcast(self):
        prepared = agent.prepare_tool(
            "channel.rebalance",
            {"amount_sat": 5000},
        )
        with self.assertRaises(agent.HTTPException) as raised:
            agent.execute_tool(
                "channel.rebalance",
                {"plan_token": prepared["plan_token"], "confirmed": False},
            )
        self.assertEqual(raised.exception.status_code, 400)

    def test_all_write_tools_prepare_and_require_cli_confirmation(self):
        payloads = {
            "channel.open": {"peer": "peer@127.0.0.1:9735", "amount_sat": 20_000},
            "channel.close": {"channel_point": "abc:0"},
            "channel.rebalance": {"amount_sat": 5_000},
            "routing.fees.set": {"ppm": 100, "base_msat": 1000},
            "magma.buy": {"offer_id": "offer-1", "size_sat": 20_000},
        }
        for name, payload in payloads.items():
            result = agent.prepare_tool(name, payload)
            self.assertEqual(result["tool"], name)
            self.assertTrue(result["requires_confirmation"])
            with self.assertRaises(agent.HTTPException) as raised:
                agent.execute_tool(
                    name,
                    {"plan_token": result["plan_token"], "confirmed": True},
                )
            self.assertEqual(raised.exception.status_code, 409)

    def test_plan_token_cannot_be_reused_or_crossed(self):
        prepared = agent.prepare_tool(
            "routing.fees.set",
            {"ppm": 100, "base_msat": 1000},
        )
        with self.assertRaises(agent.HTTPException) as mismatch:
            agent.execute_tool(
                "magma.buy",
                {"plan_token": prepared["plan_token"], "confirmed": True},
            )
        self.assertEqual(mismatch.exception.status_code, 409)
        with self.assertRaises(agent.HTTPException) as reused:
            agent.execute_tool(
                "routing.fees.set",
                {"plan_token": prepared["plan_token"], "confirmed": True},
            )
        self.assertEqual(reused.exception.status_code, 409)

    def test_magma_endpoint_rejects_missing_cli_approval(self):
        request = agent.MagmaBuyRequest(
            offer_id="offer-1",
            size_sat=20_000,
            api_key="test-key",
        )
        with self.assertRaises(agent.HTTPException) as raised:
            import asyncio
            asyncio.run(agent.buy_magma_channel(request, None))
        self.assertEqual(raised.exception.status_code, 403)

    def test_channels_shapes_active_pending_and_summary_balances(self):
        active = {
            "channels": [
                {
                    "chan_id": "1",
                    "remote_pubkey": "peer-a",
                    "local_balance": "125",
                    "remote_balance": "375",
                    "capacity": "500",
                    "active": True,
                    "total_satoshis_sent": "10",
                    "total_satoshis_received": "20",
                },
                {
                    "chan_id": "2",
                    "remote_pubkey": "peer-b",
                    "local_balance": "0",
                    "remote_balance": "0",
                    "capacity": "0",
                    "active": False,
                },
            ]
        }
        pending = {
            "pending_open_channels": [
                {
                    "channel": {
                        "remote_node_pub": "peer-c",
                        "local_balance": "90",
                        "capacity": "100",
                    },
                    "confirmation_height": 42,
                    "commit_fee": "7",
                }
            ],
            "waiting_close_channels": [
                {"remote_node_pubkey": "peer-d", "local_balance": "8", "capacity": "10"}
            ],
        }

        with patch.object(agent, "lncli", side_effect=[active, pending]):
            result = agent.get_channels()

        self.assertEqual(result["active"][0]["local_pct"], 25.0)
        self.assertEqual(result["active"][1]["local_pct"], 0)
        self.assertEqual(result["summary"], {
            "active_count": 1,
            "open_count": 2,
            "pending_count": 2,
            "total_local_sat": 125,
            "total_remote_sat": 375,
        })
        self.assertEqual(result["pending"][0]["state"], "opening")
        self.assertEqual(result["pending"][1]["state"], "waiting_close")
        self.assertEqual(result["pending"][0]["commit_fee_sat"], 7)

    def test_status_shapes_wallet_balances_and_channel_counts(self):
        info = {
            "alias": "Mercury",
            "identity_pubkey": "pubkey",
            "block_height": "100",
            "synced_to_chain": True,
            "synced_to_graph": True,
            "num_active_channels": "2",
            "num_pending_channels": "1",
            "version": "0.20",
        }
        wallet = {
            "confirmed_balance": "1200",
            "unconfirmed_balance": "30",
            "locked_balance": "40",
        }
        channels = {"channels": [{}, {}]}
        pending = {"pending_open_channels": [{}]}

        with patch.object(
            agent,
            "lncli",
            side_effect=[info, wallet, channels, pending],
        ), patch.object(agent, "systemctl_active", return_value=True), patch.object(
            agent, "get_uptime", return_value="1m"
        ):
            result = agent.get_status()

        self.assertEqual(result["wallet"], {
            "confirmed_sat": 1200,
            "unconfirmed_sat": 30,
            "locked_sat": 40,
        })
        self.assertEqual(result["channels"], {"active": 2, "open": 2, "pending": 1})
        self.assertEqual(result["node"]["block_height"], "100")


class BackupPermissionTests(unittest.TestCase):
    def test_backup_requires_configured_token_before_filesystem_access(self):
        agent.BACKUP_TOKEN = ""
        with patch.object(agent.os, "makedirs") as makedirs, patch.object(
            agent, "lncli"
        ) as lncli:
            with self.assertRaises(agent.HTTPException) as raised:
                agent.trigger_backup("wrong")

        self.assertEqual(raised.exception.status_code, 503)
        makedirs.assert_not_called()
        lncli.assert_not_called()

    def test_backup_rejects_invalid_token_before_export(self):
        agent.BACKUP_TOKEN = "correct"
        with patch.object(agent.os, "makedirs") as makedirs, patch.object(
            agent, "lncli"
        ) as lncli:
            with self.assertRaises(agent.HTTPException) as raised:
                agent.trigger_backup("wrong")

        self.assertEqual(raised.exception.status_code, 401)
        makedirs.assert_not_called()
        lncli.assert_not_called()

    def test_authorized_backup_secures_directory_and_file(self):
        agent.BACKUP_TOKEN = "correct"
        agent.BACKUP_DIR = "/var/lib/mercury/test-backups"
        opened = Mock()
        opened.__enter__ = Mock(return_value=opened)
        opened.__exit__ = Mock(return_value=False)
        with patch.object(agent.os, "makedirs") as makedirs, patch.object(
            agent.os, "chmod"
        ) as chmod, patch.object(agent, "lncli", return_value={"multi_chan_backup": {}}), patch.object(
            builtins, "open", return_value=opened
        ) as open_file:
            result = agent.trigger_backup("correct")

        path = result["path"]
        makedirs.assert_called_once_with(agent.BACKUP_DIR, exist_ok=True)
        self.assertEqual(chmod.call_args_list[0].args, (agent.BACKUP_DIR, 0o700))
        self.assertEqual(chmod.call_args_list[1].args, (path, 0o600))
        self.assertEqual(open_file.call_args.args[:2], (path, "w"))


if __name__ == "__main__":
    unittest.main()
