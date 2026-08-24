import unittest

from mercury_cli.registry import Permission, ToolPermissionError, ToolRegistry, ToolSpec


class ToolRegistryTests(unittest.TestCase):
    def test_executes_read_only_tool(self):
        registry = ToolRegistry()
        registry.register(ToolSpec("node.status", "Status", Permission.READ_ONLY, lambda args: args))

        args = object()
        self.assertIs(registry.execute("node.status", args), args)

    def test_requires_confirmation_for_write_tools(self):
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                "wallet.pay",
                "Pay invoice",
                Permission.EXPLICIT_CONFIRMATION,
                lambda args: "sent",
            )
        )

        with self.assertRaises(ToolPermissionError):
            registry.execute("wallet.pay", None)
        self.assertEqual(registry.execute("wallet.pay", None, confirmed=True), "sent")

    def test_rejects_duplicate_tools(self):
        registry = ToolRegistry()
        tool = ToolSpec("node.status", "Status", Permission.READ_ONLY, lambda args: None)
        registry.register(tool)

        with self.assertRaises(ValueError):
            registry.register(tool)

    def test_list_returns_immutable_registration_snapshot(self):
        registry = ToolRegistry()
        tool = ToolSpec("node.status", "Status", Permission.READ_ONLY, lambda args: None)
        registry.register(tool)

        listed = registry.list()
        self.assertIsInstance(listed, tuple)
        self.assertEqual(listed, (tool,))

        registry.register(
            ToolSpec("node.peers", "Peers", Permission.READ_ONLY, lambda args: None)
        )
        self.assertEqual(listed, (tool,))

    def test_unknown_tool_error_identifies_requested_name(self):
        with self.assertRaisesRegex(KeyError, "missing.tool"):
            ToolRegistry().get("missing.tool")

    def test_prepare_only_tools_are_also_confirmation_gated(self):
        called = False

        def handler(args):
            nonlocal called
            called = True

        registry = ToolRegistry()
        registry.register(
            ToolSpec("channel.prepare", "Prepare", Permission.PREPARE_ONLY, handler)
        )

        with self.assertRaises(ToolPermissionError):
            registry.execute("channel.prepare", None)
        self.assertFalse(called)
        registry.execute("channel.prepare", None, confirmed=True)
        self.assertTrue(called)

    def test_prepare_builds_plan_without_executing_handler(self):
        executed = []
        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                "bitcoin.send",
                "Send",
                Permission.EXPLICIT_CONFIRMATION,
                lambda plan: executed.append(plan),
                prepare_handler=lambda args: {"amount": args["amount"]},
            )
        )

        plan = registry.prepare("bitcoin.send", {"amount": 1000, "address": "bc1q"})
        self.assertEqual(plan, {"amount": 1000})
        self.assertEqual(executed, [])
        registry.execute("bitcoin.send", plan, confirmed=True)
        self.assertEqual(executed, [plan])


if __name__ == "__main__":
    unittest.main()
