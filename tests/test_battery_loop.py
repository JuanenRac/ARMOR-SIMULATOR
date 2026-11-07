"""The simulated battery node: its switch is off by default, one arm is one execute, and a serial that is not the battery's is refused. Nothing here needs a broker or a server."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from armor_simulator import battery_loop as loop


def command(action, **fields):
    return {"kind": "solar_battery_command", "node_id": "n1", "timestamp_ms": 1, "command_id": "0123456789abcdef", "port": 1, "action": action, **fields}


ORDER = {"op": "output_set", "params": {"output": "cfet", "state": "off"}, "serial": loop.SERIAL}


class SimBatteryNodeTests(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.node = loop.SimBatteryNode("n1", lambda topic, body: self.sent.append((topic, body)))

    def test_the_switch_is_off_by_default_and_nothing_is_written(self):
        self.node.handle(command("arm", **ORDER))
        self.assertEqual((self.sent[-1][1]["stage"], self.sent[-1][1]["refusal"]), ("rejected", "disabled"))
        self.assertEqual(self.node.console.writes, [])

    def test_arm_then_execute_changes_the_fake_console_once(self):
        self.node.allow_write = True
        self.node.handle(command("arm", **ORDER))
        armed = self.sent[-1][1]
        self.assertEqual((armed["stage"], len(armed["token"])), ("armed", 32))
        self.node.handle(command("execute", **ORDER, token=armed["token"]))
        self.assertEqual([item[1]["stage"] for item in self.sent[1:]], ["started", "progress", "progress", "final"])
        self.assertEqual(self.node.console.outputs["cfet"], "OFF")
        self.node.handle(command("execute", **ORDER, token=armed["token"]))
        self.assertEqual(self.sent[-1][1]["refusal"], "bad_token")     # the token was used up

    def test_a_serial_that_is_not_the_batterys_is_refused(self):
        self.node.allow_write = True
        self.node.handle(command("arm", **{**ORDER, "serial": "PYLWRONG0000001"}))
        self.assertEqual(self.sent[-1][1]["refusal"], "serial_mismatch")

    def test_an_execute_with_other_values_than_the_arm_is_refused(self):
        self.node.allow_write = True
        self.node.handle(command("arm", **ORDER))
        token = self.sent[-1][1]["token"]
        self.node.handle(command("execute", **{**ORDER, "params": {"output": "dfet", "state": "off"}}, token=token))
        self.assertEqual(self.sent[-1][1]["refusal"], "bad_token")
        self.assertEqual(self.node.console.writes, [])

    def test_the_snapshot_reads_like_the_sections_the_server_parses(self):
        text = loop.FakeConsole().snapshot()
        self.assertIn("## output\ncfet ", text)
        self.assertIn("cfet : ON", text.replace("  ", " "))

    def test_an_unsupported_operation_and_a_cancel_are_refused(self):
        self.node.allow_write = True
        self.node.handle(command("arm", op="restart", params={}, serial=loop.SERIAL))
        self.assertEqual(self.sent[-1][1]["refusal"], "unknown_op")
        self.node.handle(command("cancel"))
        self.assertEqual(self.sent[-1][1]["refusal"], "not_cancellable")


if __name__ == "__main__":
    unittest.main()
