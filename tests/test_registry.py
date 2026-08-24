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


if __name__ == "__main__":
    unittest.main()
