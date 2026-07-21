import importlib
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


class ImportRegressionTests(unittest.TestCase):
    def test_mcp_servers_import_without_chat_circular_dependency(self):
        for module_name in ("mcp_servers.wms_server", "mcp_servers.datameet_server"):
            with self.subTest(module=module_name):
                importlib.import_module(module_name)


if __name__ == "__main__":
    unittest.main()
