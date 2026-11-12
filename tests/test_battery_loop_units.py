"""The parts of the battery-writing loop that need neither the real server nor a broker: the fake console, the node that answers arm, execute and cancel, the administrator that
signs in and proves themselves again against a server on the loopback, and the wait for a condition."""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from armor_simulator.battery_loop import BATTERY, SERIAL, Admin, FakeConsole, SimBatteryNode, wait_for


class FakeConsoleTests(unittest.TestCase):
    def test_the_snapshot_lists_the_outputs_and_the_clock(self):
        console = FakeConsole()
        text = console.snapshot()
        self.assertIn("## output", text)
        self.assertIn("cfet : ON", text)
        self.assertIn("## clock", text)
        self.assertIn(console.clock, text)

    def test_an_output_is_set_and_the_clock_is_set_and_both_are_written_down(self):
        console = FakeConsole()
        console.apply("output_set", {"output": "buzz", "state": "on"})
        console.apply("set_clock", {})
        self.assertEqual(console.outputs["buzz"], "ON")
        self.assertEqual(console.clock, "2026-11-07 12:00:00")
        self.assertEqual(console.writes, ["output buzz on", "time set"])

    def test_an_operation_it_does_not_know_is_an_error(self):
        with self.assertRaises(ValueError):
            FakeConsole().apply("format_everything", {})


class SimBatteryNodeTests(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.node = SimBatteryNode("shim-solar", lambda topic, body: self.sent.append((topic, body)))

    def order(self, action, **fields):
        return {"command_id": "c1", "port": 1, "action": action, **fields}

    def last(self):
        return self.sent[-1][1]

    def test_its_own_switch_is_off_so_an_arm_is_refused_as_disabled(self):
        self.node.handle(self.order("arm", op="output_set", params={"output": "buzz", "state": "on"}, serial=SERIAL))
        self.assertEqual((self.last()["accepted"], self.last()["refusal"], self.last()["stage"]), (False, "disabled", "rejected"))
        self.assertEqual(self.sent[-1][0], "armor/solar/shim-solar/maintenance/result")

    def test_an_unknown_operation_and_a_wrong_serial_are_refused_once_writing_is_on(self):
        self.node.allow_write = True
        self.node.handle(self.order("arm", op="erase", params={}, serial=SERIAL))
        self.assertEqual(self.last()["refusal"], "unknown_op")
        self.node.handle(self.order("arm", op="set_clock", params={}, serial="OTHER"))
        self.assertEqual(self.last()["refusal"], "serial_mismatch")

    def test_arm_then_execute_changes_the_console_once_and_ends_with_a_final_answer(self):
        self.node.allow_write = True
        params = {"output": "heat", "state": "on"}
        self.node.handle(self.order("arm", op="output_set", params=params, serial=SERIAL))
        armed = self.last()
        self.assertEqual((armed["stage"], armed["accepted"], armed["battery"]), ("armed", True, BATTERY))
        self.assertIn("output=heat", armed["canonical"])
        self.node.handle(self.order("execute", op="output_set", params=params, serial=SERIAL, token=armed["token"]))
        stages = [body["stage"] for _topic, body in self.sent[1:]]
        self.assertEqual(stages, ["started", "progress", "progress", "final"])
        self.assertEqual(self.last()["outcome"], "ok")
        self.assertEqual(self.node.console.outputs["heat"], "ON")
        self.assertIn("output heat on", self.last()["transcript"])
        # one arm, one execute: the same token again finds nothing
        self.node.handle(self.order("execute", op="output_set", params=params, serial=SERIAL, token=armed["token"]))
        self.assertEqual(self.last()["refusal"], "bad_token")

    def test_an_execute_with_another_order_than_the_armed_one_is_refused_and_changes_nothing(self):
        self.node.allow_write = True
        self.node.handle(self.order("arm", op="output_set", params={"output": "buzz", "state": "on"}, serial=SERIAL))
        token = self.last()["token"]
        self.node.handle(self.order("execute", op="output_set", params={"output": "buzz", "state": "off"}, serial=SERIAL, token=token))
        self.assertEqual(self.last()["refusal"], "bad_token")
        self.assertEqual(self.node.console.writes, [])
        self.node.handle(self.order("execute", op="output_set", params={"output": "buzz", "state": "on"}, serial=SERIAL, token="never-given"))
        self.assertEqual(self.last()["refusal"], "bad_token")

    def test_cancel_and_an_unknown_action_are_answered_and_every_order_is_noted(self):
        self.node.handle(self.order("cancel"))
        self.assertEqual(self.last()["refusal"], "not_cancellable")
        self.node.handle(self.order("dance"))
        self.assertEqual(self.last()["refusal"], "unknown_op")
        self.assertEqual([action for action, _op in self.node.seen], ["cancel", "dance"])


class Handler(BaseHTTPRequestHandler):
    """A server that remembers the cookie it was shown and answers by path."""

    seen: list[tuple[str, str, str, str]] = []

    def log_message(self, *args):
        pass

    def _answer(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode("utf-8")
        Handler.seen.append((self.command, self.path, self.headers.get("Cookie") or "", body))
        if self.path == "/api/v1/studio/session":
            self.send_response(200)
            self.send_header("Set-Cookie", "armor_session=abc; Path=/; HttpOnly")
            self.send_header("Set-Cookie", "armor_csrf=def; Path=/")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
        elif self.path == "/api/v1/studio/elevate":
            self.send_response(204)
            self.end_headers()
        elif self.path == "/missing":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error":"not found"}')
        elif self.path == "/broken":
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"<html>not json</html>")
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"")

    do_GET = do_POST = _answer  # noqa: N815


class AdminTests(unittest.TestCase):
    def setUp(self):
        Handler.seen = []
        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.admin = Admin(f"http://127.0.0.1:{self.server.server_address[1]}", "admin", "a-password")

    def test_signing_in_keeps_the_cookies_and_sends_them_with_the_next_call(self):
        self.assertEqual(self.admin.sign_in(), 200)
        self.assertEqual(self.admin.cookie, "armor_session=abc; armor_csrf=def")
        self.assertEqual(self.admin.elevate(), 204)
        self.assertEqual(Handler.seen[0][3], json.dumps({"username": "admin", "password": "a-password"}))
        self.assertEqual(Handler.seen[1][2], "armor_session=abc; armor_csrf=def")      # the cookie goes with the next call
        self.assertEqual(Handler.seen[1][3], json.dumps({"password": "a-password"}))

    def test_an_error_answer_gives_its_code_and_its_body_when_it_is_json(self):
        self.assertEqual(self.admin.call("GET", "/missing"), (404, {"error": "not found"}))

    def test_an_error_answer_that_is_not_json_gives_its_code_and_an_empty_body(self):
        self.assertEqual(self.admin.call("GET", "/broken"), (500, {}))

    def test_an_empty_answer_is_an_empty_body(self):
        self.assertEqual(self.admin.call("GET", "/nothing"), (200, {}))


class WaitForTests(unittest.TestCase):
    def test_a_condition_that_holds_gives_its_value_at_once(self):
        self.assertEqual(wait_for(lambda: "yes", 1.0), "yes")

    def test_a_condition_that_comes_true_later_is_waited_for(self):
        calls = []

        def later():
            calls.append(1)
            return "now" if len(calls) >= 3 else None

        self.assertEqual(wait_for(later, 5.0), "now")
        self.assertGreaterEqual(len(calls), 3)

    def test_a_condition_that_never_holds_gives_nothing_after_the_time(self):
        self.assertIsNone(wait_for(lambda: None, 0.3))


if __name__ == "__main__":
    unittest.main()
