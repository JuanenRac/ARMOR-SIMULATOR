"""The corners of the command line that need a real server, broker or clock to reach, with stand-ins for them: an interrupted run, the driver of a server, the check of the sync of a panel, an
error of the broker and a message that only travels over the broker.
Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later."""
import contextlib
import io
import os
import socket
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from armor_simulator import cli  # noqa: E402
from armor_simulator.mqtt_out import MqttOutError  # noqa: E402
from armor_simulator.panel_sim import PanelLinkError  # noqa: E402
from armor_simulator.server_driver import DriverError  # noqa: E402

EXAMPLE = str(ROOT / "examples" / "alarm" / "sequential-intrusion.json")


def run(*args, env=None):
    out, err = io.StringIO(), io.StringIO()
    clean = {key: value for key, value in os.environ.items() if not key.startswith("ARMOR_")}
    clean.update(env or {})
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch.dict(os.environ, clean, clear=True):
        try:
            code = cli.main(list(args))
        except SystemExit as stop:
            code = stop.code
    return code, out.getvalue(), err.getvalue()


class Interrupted(unittest.TestCase):
    def test_a_meter_bus_and_the_cameras_that_run_until_interrupted_stop_cleanly_on_ctrl_c(self):
        for option in ("--meter-bus-port", "--camera-port"):
            with mock.patch.object(cli.time, "sleep", side_effect=KeyboardInterrupt):
                code, _, err = run(option, "0")
            self.assertEqual(code, 0, option)
            self.assertIn("listening" if "meter" in option else "camera ", err)

    def test_the_time_of_the_cameras_must_be_within_a_week(self):
        for seconds in ("-1", "700000"):
            code, _, err = run("--camera-port", "0", "--camera-seconds", seconds)
            self.assertEqual(code, 2)
            self.assertIn("--camera-seconds", err)

    def test_a_port_that_is_taken_is_told_for_the_cameras(self):
        with socket.socket() as taken:
            taken.bind(("127.0.0.1", 0))
            taken.listen()
            code, _, err = run("--camera-port", str(taken.getsockname()[1]), "--camera-seconds", "0.1")
        self.assertEqual(code, 2)
        self.assertIn("cannot listen", err)


class Verifying(unittest.TestCase):
    def test_an_observed_file_that_is_not_one_is_exit_2(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "observed.jsonl"
            path.write_text("this is not json\n", encoding="utf-8")
            code, _, err = run("--alarm-scenario", EXAMPLE, "--verify-alarms", str(path))
        self.assertEqual(code, 2)
        self.assertIn("armor-simulator:", err)


class FakeSession:
    logins: list = []

    def __init__(self, server):
        self.server = server

    def login(self, user, password):
        FakeSession.logins.append((user, password))


class Driving(unittest.TestCase):
    ARGS = ("--alarm-scenario", EXAMPLE, "--drive-server", "--server-url", "http://127.0.0.1:9", "--studio-user", "admin")
    ENV = {"ARMOR_INGEST_TOKEN": "token-of-the-test", "ARMOR_STUDIO_PASSWORD": "password-of-the-test"}

    def setUp(self):
        FakeSession.logins = []

    def drive_with(self, problems, *extra):
        result = types.SimpleNamespace(log=["armed"], observed=[{"code": "intrusion"}], problems=problems)
        with mock.patch.object(cli, "Session", FakeSession), mock.patch.object(cli, "drive", return_value=result) as drive:
            return run(*self.ARGS, *extra, env=self.ENV), drive

    def test_a_server_that_answered_as_expected_is_exit_0_and_its_log_is_printed(self):
        (code, out, err), drive = self.drive_with([])
        self.assertEqual(code, 0)
        self.assertIn("armed", err)
        self.assertIn("it answered as expected", out)
        self.assertEqual(FakeSession.logins, [("admin", "password-of-the-test")])
        self.assertEqual(drive.call_args.kwargs["ingest_token"], "token-of-the-test")

    def test_differences_are_listed_and_are_exit_1_and_the_observed_alarms_can_be_saved(self):
        with tempfile.TemporaryDirectory() as folder:
            saved = Path(folder) / "observed.json"
            (code, out, err), _ = self.drive_with(["intrusion did not happen"], "--save-observed", str(saved))
            self.assertTrue(saved.is_file())
        self.assertEqual(code, 1)
        self.assertIn("intrusion did not happen", err)
        self.assertIn("1 difference(s)", out)

    def test_a_driver_error_is_exit_2(self):
        with mock.patch.object(cli, "Session", FakeSession), mock.patch.object(cli, "drive", side_effect=DriverError("the login was refused")):
            code, _, err = run(*self.ARGS, env=self.ENV)
        self.assertEqual(code, 2)
        self.assertIn("the login was refused", err)

    def test_no_password_or_a_combination_with_faults_is_refused(self):
        code, _, err = run(*self.ARGS, env={"ARMOR_INGEST_TOKEN": "token-of-the-test"})
        self.assertEqual(code, 2)
        self.assertIn("ARMOR_STUDIO_PASSWORD", err)
        code, _, err = run(*self.ARGS, "--fault", "duplicates", env=self.ENV)
        self.assertEqual(code, 2)
        self.assertIn("real time with no faults", err)
        code, _, err = run(*self.ARGS, "--settle-s", "301", env=self.ENV)
        self.assertEqual(code, 2)
        self.assertIn("--settle-s", err)


class FakeLink:
    def __init__(self, *_a, **_k):
        self.stopped = False

    def start(self):
        pass

    def stop(self):
        self.stopped = True


class PanelSync(unittest.TestCase):
    ARGS = ("--verify-panel-sync", "--server-url", "http://127.0.0.1:9", "--studio-user", "admin", "--mqtt-url", "mqtt://127.0.0.1:9")
    ENV = {"ARMOR_STUDIO_PASSWORD": "password-of-the-test"}

    def sync_with(self, problems, *extra, map_problems=None):
        patches = [mock.patch.object(cli, "Session", FakeSession), mock.patch.object(cli, "PanelLink", FakeLink), mock.patch.object(cli.time, "sleep"),
                   mock.patch.object(cli, "verify_panel_sync", return_value=(problems, ["profile asked"])),
                   mock.patch.object(cli, "verify_panel_map", return_value=(map_problems or [], ["map checked"]))]
        with contextlib.ExitStack() as stack:
            for patch in patches:
                stack.enter_context(patch)
            return run(*self.ARGS, *extra, env=self.ENV)

    def test_a_panel_that_reported_what_it_must_is_exit_0(self):
        code, out, err = self.sync_with([])
        self.assertEqual(code, 0)
        self.assertIn("profile asked", err)
        self.assertIn("reported what the panel answered", out)

    def test_differences_are_exit_1_and_the_map_check_adds_its_own(self):
        code, out, err = self.sync_with(["mode away differs"], "--verify-panel-map", map_problems=["map differs"])
        self.assertEqual(code, 1)
        self.assertIn("map checked", err)
        self.assertIn("map differs", err)
        self.assertIn("2 difference(s)", out)

    def test_a_link_that_fails_is_exit_2(self):
        with mock.patch.object(cli, "Session", FakeSession), mock.patch.object(cli, "PanelLink", FakeLink), mock.patch.object(cli.time, "sleep"), \
                mock.patch.object(cli, "verify_panel_sync", side_effect=PanelLinkError("no broker")):
            code, _, err = run(*self.ARGS, env=self.ENV)
        self.assertEqual(code, 2)
        self.assertIn("no broker", err)

    def test_missing_pieces_are_refused(self):
        self.assertEqual(run("--verify-panel-sync")[0], 2)
        code, _, err = run(*self.ARGS, env={})
        self.assertEqual(code, 2)
        self.assertIn("ARMOR_STUDIO_PASSWORD", err)
        code, _, err = run(*self.ARGS, "--panel-id", "Not Valid", env=self.ENV)
        self.assertEqual(code, 2)
        self.assertIn("--panel-id", err)


class Broker(unittest.TestCase):
    def test_an_error_of_the_broker_while_emitting_is_exit_1_with_its_reason(self):
        with mock.patch.object(cli, "_emit", side_effect=MqttOutError("the broker refused the login")):
            code, _, err = run("--count", "1")
        self.assertEqual(code, 1)
        self.assertIn("the broker refused the login", err)

    def test_a_message_that_the_server_takes_only_from_the_broker_is_counted_and_told(self):
        with mock.patch.object(cli, "kind_of", return_value=None):
            code, out, err = run("--count", "1", "--server-url", "http://127.0.0.1:9", env={"ARMOR_INGEST_TOKEN": "token-of-the-test"})
        self.assertEqual(code, 0)
        self.assertIn("were not delivered over HTTP", err)
        self.assertTrue(out.strip())


if __name__ == "__main__":
    unittest.main()
