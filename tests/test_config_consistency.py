import ast
import importlib.util
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path


ROOT = Path(__file__).parents[1]
CLI_PATH = ROOT / "src" / "cli" / "mercury"
AGENT_PATH = ROOT / "src" / "agent" / "main.py"


def constants_from(path):
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    constants = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                try:
                    constants[target.id] = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    continue
    return constants


def load_cli():
    loader = SourceFileLoader("mercury_cli_config_test", str(CLI_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ConfigConsistencyTests(unittest.TestCase):
    def test_cli_and_agent_use_the_same_lnd_directory(self):
        cli = constants_from(CLI_PATH)
        agent = constants_from(AGENT_PATH)
        self.assertEqual(cli["LND_DIR"], agent["LND_DIR"])

    def test_cli_backup_export_directory_matches_agent_backup_directory(self):
        agent = constants_from(AGENT_PATH)
        self.assertEqual(str(load_cli().backup_export_dirs()[0]), agent["BACKUP_DIR"])

    def test_cli_agent_url_targets_agent_listener_port(self):
        cli = constants_from(CLI_PATH)
        source = AGENT_PATH.read_text(encoding="utf-8-sig")
        self.assertEqual(cli["AGENT_URL"].rsplit(":", 1)[1], "8088")
        self.assertIn("port=8088", source)


if __name__ == "__main__":
    unittest.main()
