"""The script that checks the panel sync against a real server and a real broker (tools/ci_panel_sync.py): what it does without them, and its small parts."""
import importlib.util
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

PATH = Path(__file__).resolve().parents[1] / "tools" / "ci_panel_sync.py"
spec = importlib.util.spec_from_file_location("ci_panel_sync", PATH)
assert spec is not None and spec.loader is not None
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)


class CiPanelSync(unittest.TestCase):
    def test_without_the_broker_or_node_it_says_so_and_exits_with_2(self):
        with mock.patch.dict(os.environ, {"MOSQUITTO_BIN": "", "NODE_BIN": ""}), mock.patch.object(script.shutil, "which", return_value=None), mock.patch.object(sys, "argv", ["ci_panel_sync.py"]):
            self.assertEqual(script.main(), 2)

    def test_without_the_server_built_it_says_so_and_exits_with_2(self):
        with mock.patch.dict(os.environ, {"MOSQUITTO_BIN": "mosquitto", "NODE_BIN": "node"}), mock.patch.object(script, "SERVER", PATH.parent / "no-such-server"), mock.patch.object(sys, "argv", ["ci_panel_sync.py"]):
            self.assertEqual(script.main(), 2)

    def test_a_free_port_is_a_port_nobody_listens_on(self):
        port = script.free_port()
        self.assertTrue(1024 < port < 65536)
        with script.socket.socket() as probe:
            self.assertNotEqual(probe.connect_ex(("127.0.0.1", port)), 0)

    def test_a_program_that_stops_at_once_is_reported_with_its_name(self):
        process = subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"])
        process.wait()
        with self.assertRaises(RuntimeError) as caught:
            script.wait_port(script.free_port(), process, "the broker", seconds=2)
        self.assertIn("the broker stopped at once", str(caught.exception))

    def test_a_port_that_never_opens_is_reported_after_the_time_given(self):
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            with self.assertRaises(RuntimeError) as caught:
                script.wait_port(script.free_port(), process, "the server", seconds=0.6)
            self.assertIn("did not listen", str(caught.exception))
        finally:
            process.kill()
            process.wait()


if __name__ == "__main__":
    unittest.main()
