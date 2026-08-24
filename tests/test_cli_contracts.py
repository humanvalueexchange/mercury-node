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
