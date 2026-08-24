import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
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
