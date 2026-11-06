"""The bench without Docker: the recording it plays is a recording a server could have made, and it refuses to run without a built server. (The run against the real, built server
is the job 'Simulation bench' of the CI.)"""
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from armor_simulator import bench_ci
from armor_simulator.recording import load_recording


class RecordingTests(unittest.TestCase):
    def test_the_recording_has_accepted_messages_and_one_refusal_for_a_reason(self):
        lines = [json.loads(line) for line in bench_ci.RECORDING.read_text(encoding="utf-8").splitlines() if line.strip()]
        refused = [line for line in lines if line["accepted"] is False]
        self.assertEqual(len(refused), 1)
        self.assertLessEqual(len(refused[0]["reason"]), 200)
        self.assertTrue(all(line["topic"].startswith("armor/") and "at" in line for line in lines))
        self.assertEqual(len(load_recording(bench_ci.RECORDING)), len(lines))
        self.assertEqual(len(load_recording(bench_ci.RECORDING, accepted_only=True)), len(lines) - 1)

    def test_the_refused_message_is_the_one_the_server_would_refuse(self):
        refused = next(json.loads(line) for line in bench_ci.RECORDING.read_text(encoding="utf-8").splitlines() if '"accepted":false' in line)
        self.assertGreater(refused["payload"]["lux"], 200_000)

    def test_a_recording_has_no_secret(self):
        text = bench_ci.RECORDING.read_text(encoding="utf-8").lower()
        for word in ("token", "password", "secret", "key"):
            self.assertNotIn(word, text)

    def test_the_recording_of_the_http_routes_has_one_message_of_each_kind_and_one_refusal(self):
        lines = [json.loads(line) for line in bench_ci.RECORDING_HTTP.read_text(encoding="utf-8").splitlines() if line.strip()]
        kinds = {line["topic"].split("/")[1] for line in lines}
        self.assertEqual(kinds, {"alarm", "electrical", "solar", "network"})
        refused = [line for line in lines if line["accepted"] is False]
        self.assertEqual(len(refused), 1)
        self.assertEqual(refused[0]["reason"], "the siren sounds only in the alarm phase")
        self.assertTrue(refused[0]["payload"]["siren"] and refused[0]["payload"]["phase"] != "alarm")
        self.assertEqual(len(load_recording(bench_ci.RECORDING_HTTP)), len(lines))
        self.assertEqual(len(load_recording(bench_ci.RECORDING_HTTP, accepted_only=True)), len(lines) - 1)

    def test_the_recording_of_the_http_routes_has_no_secret(self):
        text = bench_ci.RECORDING_HTTP.read_text(encoding="utf-8").lower()
        for word in ("token", "password", "secret", "key"):
            self.assertNotIn(word, text)


class RunTests(unittest.TestCase):
    def test_without_a_built_server_it_does_not_run(self):
        with tempfile.TemporaryDirectory() as folder, redirect_stderr(io.StringIO()) as err:
            self.assertEqual(bench_ci.main(["--server-dir", folder]), 2)
        self.assertIn("build the server first", err.getvalue())

    def test_a_free_port_is_a_loopback_port_that_can_be_used(self):
        port = bench_ci.free_port()
        self.assertTrue(1024 <= port <= 65535)


if __name__ == "__main__":
    unittest.main()
