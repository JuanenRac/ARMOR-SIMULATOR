"""The scenarios with modes played against a server: the orders the simulator sends, what it reads back and what it refuses to do.

The server here is a small stand-in on the loopback that answers the routes the driver uses; the real ARMOR-SERVER is what the same driver is pointed at in a manual run.
"""

from __future__ import annotations

import contextlib
import io
import json
import threading
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from armor_simulator.alarm_scenarios import ScenarioError, load_scenario, parse_scenario
from armor_simulator.cli import main
from armor_simulator.server_driver import DriverError, Session, drive, mode_changes, modes_document, zone_expectations_at_node

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "alarm" / "arming-modes-server.json"
T0 = 1_000_000.0


class FakeServer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.enabled = True
        self.modes: dict[str, Any] = {"away": {}, "home": {}, "night": {}}
        self.mode_refusal: tuple[int, str] | None = None
        self.login_status = 201
        self.alarms: list[dict[str, Any]] = []
        self.counter = 0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _answer(self, status: int, body: Any = None) -> None:
                raw = json.dumps(body if body is not None else {}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _body(self) -> Any:
                length = int(self.headers.get("Content-Length") or 0)
                return json.loads(self.rfile.read(length)) if length else None

            def do_GET(self) -> None:
                owner.calls.append(("GET", self.path, None))
                if self.path == "/api/v1/alarm/modes":
                    self._answer(200, {"enabled": owner.enabled, "revision": 3, "modes": owner.modes, "schedule": []})
                elif self.path == "/api/v1/alarms":
                    self._answer(200, {"active": owner.alarms, "recent": []})
                else:
                    self._answer(404)

            def do_PUT(self) -> None:
                body = self._body()
                owner.calls.append(("PUT", self.path, body))
                owner.modes = body["modes"]
                self._answer(200, {"enabled": owner.enabled, "revision": 4, "modes": owner.modes})

            def do_POST(self) -> None:
                body = self._body()
                owner.calls.append(("POST", self.path, body))
                if self.path == "/api/v1/studio/session":
                    self._answer(owner.login_status, {"totp_required": False})
                elif self.path == "/api/v1/mode":
                    if owner.mode_refusal:
                        self._answer(owner.mode_refusal[0], {"error": "refused", "code": owner.mode_refusal[1]})
                    else:
                        self._answer(200, {})
                elif self.path in ("/api/v1/telemetry", "/api/v1/health"):
                    self._answer(202, {"accepted": True})
                else:
                    self._answer(404)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.origin = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def alarm(self, code: str, node: str, second: float, severity: str = "high") -> dict[str, Any]:
        stamp = datetime.fromtimestamp(T0 + second, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        self.counter += 1
        return {"id": f"alm-{self.counter}", "source": {"type": "node", "id": node}, "code": code, "severity": severity, "raised_at": stamp}


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def short(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema": "armor-alarm-scenario/1", "name": "t", "duration_s": 30, "nodes": ["n1", "n2"], "seed": 1,
        "zones": [{"id": "a", "node": "n1", "sensor_id": 2, "armed_in": ["home", "away", "night"]}, {"id": "b", "node": "n2", "sensor_id": 2, "armed_in": ["away", "night"]}],
        "events": [{"type": "mode", "at_s": 1, "mode": "home"}, {"type": "mode", "at_s": 20, "mode": "night"}],
        "expect": {"alarms": [{"code": "intrusion", "node": "n1", "at_s": [2, 10]}], "forbidden": [{"code": "intrusion", "node": "n2", "from_s": 0, "to_s": 19}]},
    }
    data.update(extra or {})
    return data


class ScenarioKeyTests(unittest.TestCase):
    def test_the_example_for_a_real_server_is_valid_and_defines_what_each_mode_defends(self):
        scenario = load_scenario(EXAMPLE)
        self.assertEqual(modes_document(scenario)["modes"]["home"], {"defends": ["node:radar-garden"]})
        self.assertEqual(modes_document(scenario)["modes"]["night"], {"defends": ["node:radar-garden", "node:radar-hall"]})
        self.assertEqual(mode_changes(scenario), [(2, "home"), (58, "night")])

    def test_without_server_modes_the_nodes_with_a_zone_armed_in_the_mode_are_defended(self):
        scenario = parse_scenario(short())
        document = modes_document(scenario)
        self.assertEqual(document["modes"], {"away": {}, "home": {"defends": ["node:n1"]}, "night": {"defends": ["node:n1", "node:n2"]}})

    def test_server_modes_are_checked_as_strictly_as_the_rest_of_the_file(self):
        for bad, text in (
            ({"home": {"defends": ["node:ghost"]}}, "not in nodes"),
            ({"home": {"defends": ["thing:x"]}}, "must be zone:"),
            ({"home": {"defends": ["zone:Hall", "zone:hall"]}}, "twice"),
            ({"away": {"defends": ["node:n1"]}}, "not part of the schema"),
            ({"home": {"exit_delay_s": 301}}, "exit_delay_s"),
            ({"sleep": {}}, "not part of the schema"),
        ):
            with self.subTest(bad=bad), self.assertRaisesRegex(ScenarioError, text):
                parse_scenario(short({"server_modes": bad}))

    def test_a_forbidden_alarm_can_name_a_node_that_exists_only(self):
        with self.assertRaises(ScenarioError):
            parse_scenario(short({"expect": {"forbidden": [{"code": "intrusion", "node": "ghost"}]}}))


class ZoneExpectationTests(unittest.TestCase):
    def zoned(self, alarms: list[dict[str, Any]], forbidden: list[dict[str, Any]]) -> Any:
        return parse_scenario(short({"expect": {"alarms": alarms, "forbidden": forbidden}}))

    def test_an_expectation_that_names_a_zone_is_checked_at_the_node_that_sees_it(self):
        scenario = self.zoned([{"code": "intrusion", "zone": "a", "at_s": [2, 10]}], [{"code": "intrusion", "zone": "b", "from_s": 0, "to_s": 19}])
        checked, notes = zone_expectations_at_node(scenario)
        self.assertEqual(checked.expect_alarms[0]["node"], "n1")
        self.assertNotIn("zone", checked.expect_alarms[0])
        self.assertEqual(checked.expect_forbidden[0]["node"], "n2")
        self.assertEqual(len(notes), 2)
        self.assertIn("zone a", notes[0])
        self.assertEqual(scenario.expect_alarms[0]["zone"], "a")   # the scenario itself is not changed

    def test_an_expectation_without_a_zone_is_left_as_it_is(self):
        scenario = parse_scenario(short())
        checked, notes = zone_expectations_at_node(scenario)
        self.assertEqual(checked.expect_alarms, scenario.expect_alarms)
        self.assertEqual(notes, [])

    def test_two_zones_of_one_node_that_one_expects_and_the_other_forbids_cannot_be_checked(self):
        data = short({"zones": [{"id": "a", "node": "n1", "sensor_id": 1, "armed_in": ["home", "away", "night"]}, {"id": "b", "node": "n1", "sensor_id": 2, "armed_in": ["home", "away", "night"]}, {"id": "c", "node": "n2", "sensor_id": 2}]})
        data["expect"] = {"alarms": [{"code": "intrusion", "zone": "a", "at_s": [2, 10]}], "forbidden": [{"code": "intrusion", "zone": "b", "from_s": 0, "to_s": 19}]}
        with self.assertRaisesRegex(DriverError, "cannot tell the two zones apart"):
            zone_expectations_at_node(parse_scenario(data))
        data["expect"]["forbidden"][0].update(from_s=25, to_s=29)   # not at the same time: they can be told apart
        checked, _ = zone_expectations_at_node(parse_scenario(data))
        self.assertEqual(checked.expect_forbidden[0]["node"], "n1")

    def test_a_zone_and_a_node_that_disagree_are_refused(self):
        with self.assertRaisesRegex(DriverError, "cannot both hold"):
            zone_expectations_at_node(self.zoned([{"code": "intrusion", "zone": "a", "node": "n2", "at_s": [2, 10]}], []))


class DriveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = FakeServer()
        self.addCleanup(self.server.close)
        self.clock = Clock()
        self.sent: list[tuple[str, dict[str, Any]]] = []

    def send(self, url: str, token: str, kind: str, payload: dict[str, Any], per_node: bool = False) -> int:
        self.sent.append((kind, payload))
        return 202

    def run_scenario(self, scenario: Any, **options: Any) -> Any:
        session = Session(self.server.origin, track_clock=False)
        session.login("tester", "pw")
        return drive(scenario, session, ingest_url=self.server.origin, ingest_token="tok", clock=self.clock, sleep=self.clock.sleep, send=self.send, settle_s=0, **options)

    def test_the_mode_events_become_orders_at_their_second_and_the_alarms_are_checked(self):
        scenario = parse_scenario(short())
        self.server.alarms = [self.server.alarm("intrusion", "n1", 5)]
        result = self.run_scenario(scenario, apply_modes=True)
        self.assertEqual(result.problems, [])
        orders = [(call[2]["mode"]) for call in self.server.calls if call[1] == "/api/v1/mode"]
        self.assertEqual(orders, ["home", "night"])
        put = next(call for call in self.server.calls if call[0] == "PUT")
        self.assertEqual(put[2]["revision"], 3)
        self.assertEqual(put[2]["modes"]["home"], {"defends": ["node:n1"]})
        kinds = {kind for kind, _ in self.sent}
        self.assertEqual(kinds, {"telemetry", "health"})
        self.assertEqual(self.clock.now - T0, 30)   # one second of the clock per second of scenario
        self.assertEqual(result.observed, [{"t_s": 5.0, "code": "intrusion", "node": "n1", "severity": "high"}])

    def test_an_expectation_with_a_zone_is_checked_against_the_alarm_of_its_node(self):
        scenario = parse_scenario(short({"expect": {"alarms": [{"code": "intrusion", "zone": "a", "at_s": [2, 10]}], "forbidden": [{"code": "intrusion", "zone": "b", "from_s": 0, "to_s": 19}]}}))
        self.server.alarms = [self.server.alarm("intrusion", "n1", 5)]
        result = self.run_scenario(scenario, apply_modes=True)
        self.assertEqual(result.problems, [])
        self.assertTrue(any("names the node, not the zone" in line for line in result.log))

    def test_an_alarm_of_the_node_of_a_forbidden_zone_is_a_false_alarm(self):
        scenario = parse_scenario(short({"expect": {"alarms": [{"code": "intrusion", "zone": "a", "at_s": [2, 10]}], "forbidden": [{"code": "intrusion", "zone": "b", "from_s": 0, "to_s": 19}]}}))
        self.server.alarms = [self.server.alarm("intrusion", "n1", 5), self.server.alarm("intrusion", "n2", 8)]
        self.assertIn("must not happen", self.run_scenario(scenario, apply_modes=True).problems[0])

    def test_an_intrusion_where_the_mode_does_not_defend_is_a_difference(self):
        scenario = parse_scenario(short())
        self.server.alarms = [self.server.alarm("intrusion", "n1", 5), self.server.alarm("intrusion", "n2", 8)]
        result = self.run_scenario(scenario, apply_modes=True)
        self.assertEqual(len(result.problems), 1)
        self.assertIn("must not happen", result.problems[0])

    def test_a_missing_alarm_is_a_difference_and_alarms_before_the_run_are_left_out(self):
        scenario = parse_scenario(short())
        self.server.alarms = [self.server.alarm("intrusion", "n1", -500)]
        result = self.run_scenario(scenario, apply_modes=True)
        self.assertEqual(result.observed, [])
        self.assertIn("did not happen", result.problems[0])

    def test_a_server_with_the_modes_off_is_not_played_and_nothing_is_sent(self):
        self.server.enabled = False
        with self.assertRaisesRegex(DriverError, "arming modes are off"):
            self.run_scenario(parse_scenario(short()), apply_modes=True)
        self.assertEqual(self.sent, [])

    def test_the_definitions_in_the_server_must_be_the_ones_of_the_scenario_unless_they_are_applied(self):
        with self.assertRaisesRegex(DriverError, "--apply-modes"):
            self.run_scenario(parse_scenario(short()))
        self.assertEqual(self.sent, [])
        self.server.modes = {"away": {}, "home": {"defends": ["node:n1"]}, "night": {"defends": ["node:n2", "node:n1"]}}
        self.server.alarms = [self.server.alarm("intrusion", "n1", 5)]
        self.assertEqual(self.run_scenario(parse_scenario(short())).problems, [])
        self.assertFalse(any(call[0] == "PUT" for call in self.server.calls))

    def test_a_refusal_of_the_server_stops_the_run_and_a_pin_is_asked_for(self):
        self.server.mode_refusal = (403, "wrong_pin")
        with self.assertRaisesRegex(DriverError, "PIN") as raised:
            self.run_scenario(parse_scenario(short()), apply_modes=True)
        self.assertIn("second 1", str(raised.exception))
        self.server.mode_refusal = (409, "no_zones_assigned")
        with self.assertRaisesRegex(DriverError, "no_zones_assigned"):
            self.run_scenario(parse_scenario(short()), apply_modes=True)

    def test_the_pin_is_sent_only_when_given(self):
        self.run_scenario(parse_scenario(short()), apply_modes=True)
        self.assertTrue(all("pin" not in call[2] for call in self.server.calls if call[1] == "/api/v1/mode"))
        self.server.calls.clear()
        self.run_scenario(parse_scenario(short()), apply_modes=True, pin="4321")
        self.assertTrue(all(call[2]["pin"] == "4321" for call in self.server.calls if call[1] == "/api/v1/mode"))

    def test_the_login_failures_are_told_without_the_password(self):
        self.server.login_status = 401
        with self.assertRaises(DriverError) as raised:
            Session(self.server.origin, track_clock=False).login("tester", "secret-pw")
        self.assertNotIn("secret-pw", str(raised.exception))


class CommandLineTests(unittest.TestCase):
    def run_cli(self, *args: str) -> tuple[int, str]:
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            try:
                code = main(list(args))
            except SystemExit as exit_:
                code = int(exit_.code or 0)
        return code, err.getvalue()

    def test_driving_a_server_needs_the_server_the_token_and_the_account(self):
        code, err = self.run_cli("--alarm-scenario", str(EXAMPLE), "--drive-server")
        self.assertEqual(code, 2)
        self.assertIn("--studio-user", err)

    def test_driving_a_server_needs_a_scenario_and_no_faults(self):
        code, err = self.run_cli("--drive-server")
        self.assertEqual(code, 2)
        self.assertIn("--alarm-scenario", err)
        code, err = self.run_cli("--alarm-scenario", str(EXAMPLE), "--drive-server", "--server-url", "http://127.0.0.1:1", "--ingest-token", "t", "--studio-user", "u", "--fault", "duplicates")
        self.assertEqual(code, 2)
        self.assertIn("real time", err)

    def test_the_password_comes_from_a_file_or_the_environment_and_a_missing_file_is_told(self):
        code, err = self.run_cli("--alarm-scenario", str(EXAMPLE), "--drive-server", "--server-url", "http://127.0.0.1:1", "--ingest-token", "t", "--studio-user", "u", "--studio-password-file", "does-not-exist.txt")
        self.assertEqual(code, 2)
        self.assertIn("does-not-exist.txt", err)


if __name__ == "__main__":
    unittest.main()
