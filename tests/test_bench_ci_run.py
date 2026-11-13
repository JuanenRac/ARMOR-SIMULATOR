"""The run of the bench seen without a server, a broker or a node: every process, HTTP read and simulator call is a stand-in, so what is checked is the order of the steps, the
environment given to the server, the checks that are added for each road and the clean-up at the end. The run against a real server is the job 'Simulation bench' of the CI.
Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from armor_simulator import bench_ci  # noqa: E402

NODES = {"nodes": {name: {} for name in ("bench-1", "bench-3", "bench-4", "incident-1", "mqtt-1", "shim-radar")}}
ROUTES = {
    "/healthz": {},
    "/api/v1/status": NODES,
    "/api/v1/alarm/nodes": {"nodes": [{"node_id": "alarm-http"}, {"node_id": "shim-alarm", "state": {"phase": "armed", "mode": "away"}}]},
    "/api/v1/electrical/readings": {"nodes": [{"node_id": "http-1"}, {"node_id": "shim-electrical"}]},
    "/api/v1/solar": {"devices": [{"node_id": "shim-solar", "kind": "inverter"}, {"node_id": "shim-solar", "kind": "battery"}]},
    "/api/v1/node-health": {"nodes": [{"node_id": "shim-hmi", "family": "hmi", "report": {"reset_reason": "brownout", "last_error": ""}}]},
}


class FakeProcess:
    started: list = []

    def __init__(self, command, **kwargs):
        self.command = command
        self.kwargs = kwargs
        self.ended = []
        FakeProcess.started.append(self)

    def terminate(self):
        self.ended.append("terminate")

    def wait(self, _seconds=None):
        self.ended.append("wait")

    def kill(self):
        self.ended.append("kill")


def fake_get(url, bearer=None, timeout=5.0):
    path = url.split("127.0.0.1:", 1)[1].split("/", 1)[1]
    body = ROUTES.get("/" + path)
    return (200, json.dumps(body).encode()) if body is not None else (404, b"{}")


def fake_simulate(argv):
    if "--replay" in argv and "--replay-accepted-only" not in argv:
        return 1, "armor-simulator: the server refused a message"
    if "--allow-invalid" in argv:
        return 0, "9 sent, 3 were refused"
    return 0, "ok"


def fake_shim(_argv):
    return 0, ""


class Run(unittest.TestCase):
    def setUp(self):
        FakeProcess.started = []
        self.server = Path(tempfile.mkdtemp(prefix="armor-run-test-"))
        (self.server / "dist").mkdir()
        (self.server / "dist" / "server.mjs").write_text("//", encoding="utf-8")
        self.loop = mock.Mock()
        self.patches = [
            mock.patch.object(bench_ci.subprocess, "Popen", FakeProcess),
            mock.patch.object(bench_ci.shutil, "which", side_effect=lambda name: name),
            mock.patch.object(bench_ci, "get", fake_get),
            mock.patch.object(bench_ci, "simulate", fake_simulate),
            mock.patch.object(bench_ci, "shim_main", fake_shim),
            mock.patch.object(bench_ci, "camera_checks", lambda *_a: None),
            mock.patch.object(bench_ci, "_reachable", lambda _port: True),
            mock.patch.dict(sys.modules, {}),
        ]
        for patch in self.patches:
            patch.start()
        self.addCleanup(lambda: [patch.stop() for patch in reversed(self.patches)])

    def names(self, rows):
        return [row["check"] for row in rows]

    def test_over_http_only_every_road_is_checked_and_the_mqtt_one_is_skipped(self):
        rows = bench_ci.run(self.server, None)
        self.assertTrue(all(row["passed"] for row in rows), [row for row in rows if not row["passed"]])
        names = self.names(rows)
        self.assertIn("server starts", names)
        self.assertIn("refusals: impossible readings are refused", names)
        self.assertIn("replay: the message the server refused is refused again", names)
        self.assertIn("replay: the HTTP routes of a recording (alarm, electrical, solar, network) arrive", names)
        self.assertFalse([name for name in names if name.startswith("mqtt")])
        self.assertEqual(names[-1], "server still answers at the end")
        self.assertEqual(len(FakeProcess.started), 1)
        self.assertEqual(FakeProcess.started[0].ended[0], "terminate")
        self.assertNotIn("ARMOR_INGEST_TOKEN", os.environ)

    def test_the_server_gets_secrets_of_its_own_and_a_loopback_port_and_nothing_of_the_environment_secrets(self):
        with mock.patch.dict(os.environ, {"SOME_OTHER_SECRET": "x", "ARMOR_OPERATOR_TOKEN": "from-the-environment"}):
            bench_ci.run(self.server, None)
        env = FakeProcess.started[0].kwargs["env"]
        self.assertNotIn("SOME_OTHER_SECRET", env)
        self.assertNotEqual(env["ARMOR_OPERATOR_TOKEN"], "from-the-environment")
        self.assertEqual(env["ARMOR_HOST"], "127.0.0.1")
        self.assertEqual(len(env["ARMOR_INGEST_TOKEN"]), 32)
        self.assertNotIn("ARMOR_BATTERY_WRITE", env)

    def test_with_a_broker_and_every_shim_each_road_adds_its_check(self):
        with mock.patch("armor_simulator.battery_loop.run_checks") as loop:
            rows = bench_ci.run(self.server, "auto", "radar", "electrical", "solar", "alarm", "hmi", True)
        self.assertTrue(all(row["passed"] for row in rows), [row for row in rows if not row["passed"]])
        names = " | ".join(self.names(rows))
        for word in ("mqtt: a node that only exists", "radar node", "electrical node", "solar node", "alarm node", "HMI node", "shim: the server still answers"):
            self.assertIn(word, names)
        loop.assert_called_once()
        self.assertEqual(len(FakeProcess.started), 2)
        self.assertEqual(FakeProcess.started[1].kwargs["env"]["ARMOR_BATTERY_WRITE"], "1")
        self.assertTrue(FakeProcess.started[1].kwargs["env"]["ARMOR_MQTT_URL"].startswith("mqtt://127.0.0.1:"))

    def test_nothing_showing_on_the_server_fails_the_checks_and_does_not_raise(self):
        def waiting(check, seconds, what):
            if what in ("the server", "the broker"):
                return True
            raise bench_ci.BenchError(f"{what} did not happen")

        with mock.patch.object(bench_ci, "wait_until", waiting):
            rows = bench_ci.run(self.server, "auto", "radar", "electrical", "solar", "alarm", "hmi")
        failed = [row["check"] for row in rows if not row["passed"]]
        for word in ("mqtt: a node", "radar node", "electrical node", "solar node", "alarm node"):
            self.assertTrue([name for name in failed if word in name], word)
        self.assertEqual(rows[-1]["check"], "server still answers at the end")
        self.assertTrue(rows[-1]["passed"])

    def test_a_server_that_does_not_start_gives_its_log(self):
        def never(check, seconds, what):
            raise bench_ci.BenchError(f"{what} did not happen")

        with mock.patch.object(bench_ci, "wait_until", never):
            with self.assertRaises(bench_ci.BenchError) as raised:
                bench_ci.run(self.server, None)
        self.assertIn("the server did not start", str(raised.exception))
        self.assertEqual(FakeProcess.started[0].ended[0], "terminate")

    def test_a_missing_broker_program_is_a_skip_when_automatic(self):
        with mock.patch.object(bench_ci.shutil, "which", side_effect=lambda name: "node" if name == "node" else None):
            rows = bench_ci.run(self.server, "auto")
        self.assertFalse([row for row in rows if row["check"].startswith("mqtt")])

    def test_a_missing_mqtt_client_library_is_told(self):
        def simulate(argv):
            return (1, "No module named 'paho'") if "--mqtt-url" in argv else fake_simulate(argv)

        with mock.patch.object(bench_ci, "simulate", simulate):
            with self.assertRaises(bench_ci.BenchError) as raised:
                bench_ci.run(self.server, "auto")
        self.assertIn("paho-mqtt", str(raised.exception))

    def test_a_child_that_does_not_stop_is_killed(self):
        class Stubborn(FakeProcess):
            def wait(self, _seconds=None):
                raise subprocess.TimeoutExpired("x", 10)

        with mock.patch.object(bench_ci.subprocess, "Popen", Stubborn):
            bench_ci.run(self.server, None)
        self.assertEqual(Stubborn.started[0].ended, ["terminate", "kill"])

    def test_the_module_can_be_run_as_a_program(self):
        import runpy
        with mock.patch.object(sys, "argv", ["bench_ci", "--server-dir", str(self.server / "missing")]):
            with self.assertRaises(SystemExit) as stop:
                runpy.run_module("armor_simulator.bench_ci", run_name="__main__")
        self.assertEqual(stop.exception.code, 2)


if __name__ == "__main__":
    unittest.main()


class PrivateBroker(unittest.TestCase):
    def test_on_linux_a_broker_that_is_a_file_is_copied_into_the_working_folder_and_anything_else_is_used_as_it_is(self) -> None:
        import tempfile
        from pathlib import Path
        from unittest import mock

        with tempfile.TemporaryDirectory() as folder:
            work = Path(folder)
            original = work / "installed-broker"
            original.write_bytes(b"#!/bin/sh\n")
            with mock.patch.object(bench_ci.sys, "platform", "linux"):
                copy = bench_ci.private_broker(str(original), work)
                self.assertEqual(copy, str(work / "mosquitto-broker"))
                self.assertEqual(Path(copy).read_bytes(), b"#!/bin/sh\n")
                self.assertEqual(bench_ci.private_broker("mosquitto", work), "mosquitto", "a name that is not a file is left to the system")
            with mock.patch.object(bench_ci.sys, "platform", "win32"):
                self.assertEqual(bench_ci.private_broker(str(original), work), str(original))
