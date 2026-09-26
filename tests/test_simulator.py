import contextlib
import io
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
COMMON = ROOT.parent / "ARMOR-COMMON" / "src"
if COMMON.is_dir():
    sys.path.insert(0, str(COMMON))

from armor_simulator import health, telemetry
from armor_simulator.cli import main, messages
from armor_simulator.faults import FAULTS, INVALID_FAULTS
from armor_simulator.publisher import DeliveryError, check_server_url, post
from armor_simulator.scenarios import SCENARIOS, tracks_for
import random


def run(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(list(args))
        except SystemExit as exit_:
            code = exit_.code
    return code, out.getvalue(), err.getvalue()


class ScenarioTests(unittest.TestCase):
    def test_the_same_arguments_always_give_the_same_payload(self):
        for scenario in SCENARIOS:
            self.assertEqual(telemetry("sim-1", 4, scenario, seed=7), telemetry("sim-1", 4, scenario, seed=7))

    def test_a_different_seed_changes_the_noisy_scenarios_only(self):
        self.assertNotEqual(telemetry("n", 3, "crossing", seed=1), telemetry("n", 3, "crossing", seed=2))
        self.assertEqual(telemetry("n", 3, "patrol", seed=1), telemetry("n", 3, "patrol", seed=2))

    def test_patrol_is_visible_only_in_front_of_the_node(self):
        self.assertEqual(telemetry("n", 0, "patrol")["targets"], [])          # at 3 m to the right, level with the node
        self.assertEqual(len(telemetry("n", 6, "patrol")["targets"]), 1)      # straight ahead

    def test_every_target_is_seen_by_the_sensor_facing_it(self):
        rng = random.Random(0)
        first = tracks_for("crossing", 0, rng)[0]
        last = tracks_for("crossing", 11, rng)[0]
        self.assertEqual((first["sensor_id"], last["sensor_id"]), (1, 3))

    def test_two_intruders_gives_two_tracks_and_empty_gives_none(self):
        self.assertEqual(len(telemetry("n", 9, "two-intruders")["targets"]), 2)
        self.assertEqual(telemetry("n", 5, "empty")["targets"], [])

    def test_track_ids_are_positive_and_sensor_ids_are_one_to_three(self):
        for scenario in SCENARIOS:
            for sample in range(24):
                for track in telemetry("n", sample, scenario)["targets"]:
                    self.assertIn(track["sensor_id"], (1, 2, 3))
                    self.assertGreaterEqual(track["track_id"], 1)

    def test_the_night_light_profile_is_fixed_and_dark(self):
        self.assertEqual({telemetry("n", s, light="night")["lux"] for s in range(5)}, {0.3})
        self.assertGreater(telemetry("n", 6, light="cycle")["lux"], 4000)

    def test_health_payload(self):
        self.assertEqual(health("n", 3), {"node_id": "n", "timestamp_ms": 3000, "online": True})


class FaultTests(unittest.TestCase):
    def stream(self, count=12, health_every=2):
        return list(messages("n", count, "crossing", "cycle", 0, health_every))

    def test_no_fault_leaves_the_stream_alone(self):
        self.assertEqual(list(FAULTS["none"](self.stream(), 3)), self.stream())

    def test_a_silent_node_stops_after_the_given_number_of_messages(self):
        self.assertEqual(len(list(FAULTS["node-silent"](self.stream(), 5))), 5)

    def test_out_of_order_messages_carry_an_older_timestamp(self):
        original = self.stream()
        changed = list(FAULTS["out-of-order"](original, 4))
        self.assertEqual(len(changed), len(original))
        self.assertLess(changed[4][1]["timestamp_ms"], original[4][1]["timestamp_ms"])
        self.assertEqual(changed[1], original[1])

    def test_duplicates_repeat_every_nth_message(self):
        self.assertGreater(len(list(FAULTS["duplicates"](self.stream(), 3))), len(self.stream()))

    def test_flapping_marks_some_health_messages_offline(self):
        flags = [payload["online"] for topic, payload in FAULTS["flapping"](self.stream(20), 2) if topic.endswith("/health")]
        self.assertIn(False, flags)
        self.assertIn(True, flags)

    def test_invalid_faults_are_flagged_and_really_are_invalid(self):
        from armor_common import ContractError, validate_topic_and_payload
        for name in INVALID_FAULTS:
            bad = 0
            for topic, payload in FAULTS[name](self.stream(), 1):
                try:
                    validate_topic_and_payload(topic, payload)
                except ContractError:
                    bad += 1
            self.assertGreater(bad, 0, name)

    def test_the_valid_faults_produce_only_valid_messages(self):
        from armor_common import validate_topic_and_payload
        for name in set(FAULTS) - INVALID_FAULTS:
            for topic, payload in FAULTS[name](self.stream(), 3):
                validate_topic_and_payload(topic, payload)


class CliTests(unittest.TestCase):
    def test_default_output_is_valid_json_lines(self):
        code, out, _ = run("--count", "4", "--validate")
        self.assertEqual(code, 0)
        for line in out.strip().splitlines():
            envelope = json.loads(line)
            self.assertEqual(set(envelope), {"topic", "payload"})

    def test_invalid_arguments_are_refused(self):
        for args in (["--count", "0"], ["--count", "10001"], ["--node-id", "Bad Node"], ["--interval-ms", "-1"], ["--server-url", "http://x"],
                     ["--ingest-token", "x"], ["--fault", "corrupt-lux"], ["--fault", "corrupt-lux", "--allow-invalid", "--validate"]):
            code, _, _ = run(*args)
            self.assertEqual(code, 2, args)

    def test_an_invalid_fault_is_emitted_only_when_asked_for(self):
        code, out, _ = run("--count", "3", "--fault", "corrupt-lux", "--fault-every", "1", "--allow-invalid")
        self.assertEqual(code, 0)
        self.assertIn("1000000000", out)

    def test_the_server_url_must_be_a_plain_origin(self):
        self.assertEqual(check_server_url("http://127.0.0.1:8080/"), "http://127.0.0.1:8080")
        for bad in ("ftp://x", "http://u:p@x", "http://x/api", "http://x?q=1", "nonsense"):
            with self.assertRaises(ValueError):
                check_server_url(bad)


class Capture(BaseHTTPRequestHandler):
    statuses: list[int] = []
    seen: list[tuple[str, str, dict]] = []

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Capture.seen.append((self.path, self.headers.get("Authorization", ""), body))
        self.send_response(Capture.statuses.pop(0) if Capture.statuses else 202)
        self.end_headers()

    def log_message(self, *args):
        pass


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        Capture.statuses, Capture.seen = [], []
        self.server = HTTPServer(("127.0.0.1", 0), Capture)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def test_a_message_is_posted_with_the_ingest_token(self):
        post(self.url, "tok", "telemetry", {"a": 1})
        self.assertEqual(Capture.seen[0], ("/api/v1/telemetry", "Bearer tok", {"a": 1}))

    def test_a_client_error_is_final_and_a_server_error_is_retried(self):
        Capture.statuses = [400]
        with self.assertRaises(DeliveryError):
            post(self.url, "tok", "health", {}, pause_s=0)
        self.assertEqual(len(Capture.seen), 1)
        Capture.seen.clear()
        Capture.statuses = [503, 503, 202]
        self.assertEqual(post(self.url, "tok", "health", {}, pause_s=0), 202)
        self.assertEqual(len(Capture.seen), 3)

    def test_an_unreachable_server_gives_a_clear_error(self):
        with self.assertRaises(DeliveryError):
            post("http://127.0.0.1:1", "tok", "telemetry", {}, timeout=0.5, attempts=1)

    def test_the_cli_delivers_every_message_it_emits(self):
        code, out, _ = run("--count", "3", "--health-every", "1", "--server-url", self.url, "--ingest-token", "tok")
        self.assertEqual(code, 0)
        self.assertEqual(len(Capture.seen), len(out.strip().splitlines()))
        self.assertEqual({path for path, _, _ in Capture.seen}, {"/api/v1/telemetry", "/api/v1/health"})

    def test_a_refused_message_stops_the_run_unless_the_fault_was_intentional(self):
        Capture.statuses = [401]
        code, _, err = run("--count", "2", "--server-url", self.url, "--ingest-token", "bad")
        self.assertEqual(code, 1)
        self.assertIn("rejected", err)
        Capture.statuses = [400, 400, 400, 400]
        code, _, _ = run("--count", "2", "--fault", "unknown-field", "--fault-every", "1", "--allow-invalid", "--server-url", self.url, "--ingest-token", "tok")
        self.assertEqual(code, 0)


class SolarTests(unittest.TestCase):
    def test_solar_adds_an_inverter_and_a_battery_that_the_contract_accepts(self):
        code, out, _ = run("--count", "300", "--solar", "--validate", "--health-every", "0")
        self.assertEqual(code, 0)
        lines = [json.loads(line) for line in out.strip().splitlines()]
        solar = [line for line in lines if line["topic"].startswith("armor/solar/")]
        self.assertEqual(len(solar), 600)
        inverters = [line["payload"] for line in solar if line["payload"]["kind"] == "inverter"]
        self.assertEqual({item["mode"] for item in inverters}, {"line", "battery"})          # the mains outage of the fast day
        self.assertTrue(any(item["pv_w"] > 2000 for item in inverters))
        battery = next(line["payload"] for line in solar if line["payload"]["kind"] == "battery")
        self.assertEqual([len(module["cells_v"]) for module in battery["stack"]], [15, 15])
        self.assertEqual(battery["full_capacity_ah"], 148.0)

    def test_the_solar_stream_is_repeatable_and_off_by_default(self):
        self.assertEqual(run("--count", "5", "--solar", "--seed", "3"), run("--count", "5", "--solar", "--seed", "3"))
        self.assertNotIn("armor/solar/", run("--count", "5")[1])


if __name__ == "__main__":
    unittest.main()
