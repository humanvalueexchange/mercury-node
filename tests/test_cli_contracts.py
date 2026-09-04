import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from unittest.mock import AsyncMock
from importlib.machinery import SourceFileLoader


CLI_PATH = Path(__file__).parents[1] / "src" / "cli" / "mercury"


def load_cli():
    loader = SourceFileLoader("mercury_cli_entrypoint", str(CLI_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cli = load_cli()


class CliParserDispatchTests(unittest.TestCase):
    def test_ask_skips_hailo_when_readiness_is_unavailable(self):
        config = type(
            "Config",
            (),
            {
                "split_ai": True,
                "hailo_url": "http://127.0.0.1:8000",
                "hailo_model": "model",
                "hailo_ready_file": "/run/hailo-ollama/ready",
                "local_llm_url": "http://127.0.0.1:8089",
                "local_llm_model": "model",
                "allow_dgx": False,
                "ai_debug": False,
            },
        )()
        with patch.object(cli, "load_config", return_value=config), patch.object(
            cli.SnapshotBuilder, "build", return_value={"fresh": True}
        ), patch.object(cli, "deterministic_reply", return_value=None), patch.object(
            cli.HailoClient, "ready", return_value=False
        ), patch.object(cli.LlamaClient, "healthy", return_value=True), patch.object(
            cli.LlamaClient, "chat", new_callable=AsyncMock, return_value="Draft"
        ), patch.object(cli.HailoClient, "chat", new_callable=AsyncMock) as hailo_chat, patch.object(
            cli, "print_answer"
        ) as answer:
            result = cli.cmd_ask(type("Args", (), {"question": ["status", "summary"]})())

        self.assertEqual(result, 0)
        hailo_chat.assert_not_called()
        self.assertEqual(answer.call_args.args[1], "Draft")

    def test_write_tools_are_confirmation_gated(self):
        for name in (
            "payment.pay",
            "bitcoin.send",
            "channel.open",
            "channel.close",
            "channel.rebalance",
            "routing.fees.set",
            "magma.buy",
        ):
            self.assertEqual(
                cli.TOOL_REGISTRY.get(name).permission,
                cli.Permission.EXPLICIT_CONFIRMATION,
            )

    def test_operation_amount_limits_are_enforced(self):
        self.assertEqual(cli.validate_amount(5000, "test", minimum=100), 5000)
        with self.assertRaises(ValueError):
            cli.validate_amount(99, "test", minimum=100)
        with self.assertRaises(ValueError):
            cli.validate_amount(cli.MAX_OPERATION_SAT + 1, "test")

    def test_send_prepare_builds_plan_without_broadcast(self):
        with patch.object(
            cli, "lncli", return_value=({"confirmed_balance": "5000"}, None)
        ) as lncli:
            plan = cli.TOOL_REGISTRY.prepare(
                "bitcoin.send",
                type("Args", (), {"address": "bc1qexample", "amount": 1000})(),
            )

        self.assertIsInstance(plan, cli.SendPlan)
        self.assertEqual(plan.amount_sat, 1000)
        lncli.assert_called_once_with("walletbalance")

    def test_payment_prepare_decodes_without_broadcast(self):
        with patch.object(
            cli,
            "lncli",
            return_value=(
                {
                    "num_satoshis": "2500",
                    "destination": "02" + "a" * 64,
                    "description": "test",
                },
                None,
            ),
        ) as lncli:
            plan = cli.TOOL_REGISTRY.prepare(
                "payment.pay", type("Args", (), {"bolt11": "lnbc-test"})()
            )

        self.assertIsInstance(plan, cli.PayPlan)
        self.assertEqual((plan.amount_sat, plan.memo), (2500, "test"))
        lncli.assert_called_once_with("decodepayreq", "lnbc-test")

    def test_channel_write_tools_execute_only_approved_plans(self):
        self.assertIs(
            cli.TOOL_REGISTRY.get("channel.open").handler,
            cli.execute_channel_open,
        )
        self.assertIs(
            cli.TOOL_REGISTRY.get("channel.close").handler,
            cli.execute_channel_close,
        )

    def test_execution_plan_tools_have_prepare_handlers(self):
        self.assertIs(
            cli.TOOL_REGISTRY.get("channel.rebalance").prepare_handler,
            cli.prepare_rebalance,
        )
        self.assertIs(
            cli.TOOL_REGISTRY.get("routing.fees.set").prepare_handler,
            cli.prepare_fees,
        )
        self.assertIs(
            cli.TOOL_REGISTRY.get("magma.buy").prepare_handler,
            cli.prepare_magma_buy,
        )

    def test_rebalance_prepare_validates_requested_amount(self):
        args = type("Args", (), {"amount": 5000, "dry_run": True})()
        plan = cli.TOOL_REGISTRY.prepare("channel.rebalance", args)
        self.assertIsInstance(plan, cli.RebalancePlan)
        with self.assertRaises(ValueError):
            cli.TOOL_REGISTRY.prepare(
                "channel.rebalance",
                type("Args", (), {"amount": 4999})(),
            )

    def test_fee_prepare_validates_limits_without_lnd_call(self):
        args = type(
            "Args",
            (),
            {"fees_action": "set", "ppm": 100, "base_msat": 1000},
        )()
        plan = cli.TOOL_REGISTRY.prepare("routing.fees.set", args)
        self.assertIsInstance(plan, cli.FeeUpdatePlan)

    def test_ask_does_not_execute_invoice_writes(self):
        with patch.object(cli, "lncli") as lncli, patch.object(
            cli, "_print_ai_answer"
        ) as answer:
            cli.cmd_ask(type("Args", (), {"question": ["create", "invoice", "for", "1000", "sats"]})())

        lncli.assert_not_called()
        self.assertIn("cannot execute writes", answer.call_args.args[1])

    def test_ask_payment_prepares_but_does_not_pay(self):
        plan = cli.PayPlan("lnbc-test", 2500, "peer", "test")
        with patch.object(cli.TOOL_REGISTRY, "prepare", return_value=plan), patch.object(
            cli, "_print_ai_answer"
        ) as answer, patch.object(cli, "execute_pay") as execute:
            cli.cmd_ask(
                type(
                    "Args",
                    (),
                    {"question": ["pay", "lnbc-test"]},
                )()
            )

        execute.assert_not_called()
        self.assertIn("No payment was sent", answer.call_args.args[1])

    def test_status_parser_dispatches_with_ai_flag(self):
        with patch.object(cli, "cmd_status_tool") as handler, patch.object(
            sys, "argv", ["mercury", "status", "--ai"]
        ):
            cli.main()

        args = handler.call_args.args[0]
        self.assertEqual(args.command, "status")
        self.assertTrue(args.ai)

    def test_invoice_parser_preserves_defaults_and_filters(self):
        with patch.object(cli, "cmd_invoices") as handler, patch.object(
            sys, "argv", ["mercury", "invoices", "--last", "7", "--recent"]
        ):
            cli.main()

        args = handler.call_args.args[0]
        self.assertEqual((args.last, args.recent, args.pending), (7, True, False))

    def test_nested_channel_parser_dispatches_peer_and_amount(self):
        with patch.object(cli, "cmd_channel") as handler, patch.object(
            sys, "argv", ["mercury", "channel", "open", "acinq", "400000"]
        ):
            cli.main()

        args = handler.call_args.args[0]
        self.assertEqual(args.command, "channel")
        self.assertEqual(args.channel_action, "open")
        self.assertEqual((args.peer, args.amount), ("acinq", "400000"))

    def test_send_parser_dispatches_address_and_amount(self):
        with patch.object(cli, "cmd_send") as handler, patch.object(
            sys, "argv", ["mercury", "send", "bc1qexample", "1000"]
        ):
            cli.main()

        args = handler.call_args.args[0]
        self.assertEqual((args.address, args.amount), ("bc1qexample", 1000))

    def test_magma_parser_dispatches_bounds_and_subcommand(self):
        with patch.object(cli, "cmd_magma") as handler, patch.object(
            sys,
            "argv",
            ["mercury", "magma", "recommend", "--min", "123", "--max", "456", "--ai"],
        ):
            cli.main()

        args = handler.call_args.args[0]
        self.assertEqual(
            (args.subcmd, args.min_sat, args.max_sat, args.ai),
            ("recommend", 123, 456, True),
        )

if __name__ == "__main__":
    unittest.main()
