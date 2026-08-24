import ast
import importlib.util
import sys
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path


ROOT = Path(__file__).parents[1]
CLI_PATH = ROOT / "src" / "cli" / "mercury"
AGENT_PATH = ROOT / "src" / "agent" / "main.py"
PACKAGE_PATH = ROOT / "src" / "cli"


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
    sys.modules[loader.name] = module
    spec.loader.exec_module(module)
    return module


def load_config():
    loader = SourceFileLoader(
        "mercury_cli_config_module",
        str(PACKAGE_PATH / "mercury_cli" / "config.py"),
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    spec.loader.exec_module(module)
    return module.load_config({})


class ConfigConsistencyTests(unittest.TestCase):
    def test_cli_and_agent_use_the_same_lnd_directory(self):
        config = load_config()
        agent = constants_from(AGENT_PATH)
        self.assertEqual(str(config.lnd_dir), agent["LND_DIR"])

    def test_cli_backup_export_directory_matches_agent_backup_directory(self):
        agent = constants_from(AGENT_PATH)
        self.assertEqual(str(load_config().backup_dir), agent["BACKUP_DIR"])

    def test_cli_agent_url_targets_agent_listener_port(self):
        config = load_config()
        source = AGENT_PATH.read_text(encoding="utf-8-sig")
        self.assertEqual(config.agent_url.rsplit(":", 1)[1], "8088")
        self.assertIn("port=8088", source)


if __name__ == "__main__":
    unittest.main()
