"""The helpers of the bench without Docker, tested against stand-ins on the loopback address: the two HTTP readers, the waiting loop, the list of checks, the report the command
writes and the camera checks seen from a server that answers what a good one would not. The run against a real server is the job 'Simulation bench' of the CI.
Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later."""
import http.server
import io
import json
import socket
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from armor_simulator import bench_ci  # noqa: E402


class Stub(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    routes: dict = {}
    seen: list = []

    def log_message(self, *_args):
        pass

    def answer(self, method):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self.seen.append((method, self.path, self.headers.get("Authorization"), body))
        status, payload = self.routes.get((method, self.path), self.routes.get((method, "*"), (404, b"{}")))
        if callable(payload):
            payload = payload(body)
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        self.answer("GET")

    def do_POST(self):  # noqa: N802
        self.answer("POST")


class QuietServer(http.server.ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass


class WithStub(unittest.TestCase):
    def setUp(self):
        Stub.routes, Stub.seen = {}, []
        self.httpd = QuietServer(("127.0.0.1", 0), Stub)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"


class Readers(WithStub):
    def test_get_gives_the_status_and_the_body_and_sends_the_token_only_when_there_is_one(self):
        Stub.routes[("GET", "/a")] = (200, b"hello")
        Stub.routes[("GET", "/missing")] = (404, b"gone")
        self.assertEqual(bench_ci.get(f"{self.base}/a"), (200, b"hello"))
        self.assertEqual(bench_ci.get(f"{self.base}/a", "tok"), (200, b"hello"))
        self.assertEqual(bench_ci.get(f"{self.base}/missing"), (404, b"gone"))
        self.assertEqual([seen[2] for seen in Stub.seen], [None, "Bearer tok", None])

    def test_post_sends_json_with_the_token_and_gives_an_error_status_back_as_a_result(self):
        Stub.routes[("POST", "/ok")] = (201, {"path": "/x"})
        Stub.routes[("POST", "/no")] = (502, b"bad")
        self.assertEqual(bench_ci.post(f"{self.base}/ok", "tok", {"a": 1}), (201, b'{"path": "/x"}'))
        self.assertEqual(bench_ci.post(f"{self.base}/no", "tok", {}), (502, b"bad"))
        self.assertEqual(json.loads(Stub.seen[0][3]), {"a": 1})
        self.assertEqual(Stub.seen[0][2], "Bearer tok")

    def test_a_port_that_is_listening_is_reachable_and_one_that_is_not_raises(self):
        self.assertTrue(bench_ci._reachable(self.httpd.server_address[1]))
        free = bench_ci.free_port()
        with self.assertRaises(OSError):
            bench_ci._reachable(free)

    def test_a_free_port_is_not_taken(self):
        port = bench_ci.free_port()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))


class Waiting(unittest.TestCase):
    def test_the_first_truthy_answer_is_returned(self):
        answers = iter([None, 0, "ready"])
        with mock.patch.object(bench_ci.time, "sleep"):
            self.assertEqual(bench_ci.wait_until(lambda: next(answers), 5, "x"), "ready")

    def test_network_errors_are_waited_through_and_a_timeout_names_what_did_not_happen(self):
        def refuse():
            raise OSError("not yet")
        with mock.patch.object(bench_ci.time, "sleep"), mock.patch.object(bench_ci.time, "monotonic", side_effect=[0, 0, 1, 2, 99]):
            with self.assertRaises(bench_ci.BenchError) as caught:
                bench_ci.wait_until(refuse, 3, "the server answering")
        self.assertIn("the server answering did not happen within 3 s", str(caught.exception))

    def test_a_value_error_of_the_check_is_also_waited_through(self):
        calls = []

        def check():
            calls.append(1)
            if len(calls) < 3:
                raise ValueError("half a document")
            return True
        with mock.patch.object(bench_ci.time, "sleep"):
            self.assertTrue(bench_ci.wait_until(check, 5, "x"))


class TheChecks(unittest.TestCase):
    def test_a_check_is_kept_and_printed_with_its_detail_only_when_it_failed(self):
        checks = bench_ci.Check()
        out = io.StringIO()
        with redirect_stdout(out):
            checks.add("good", True, "ignored")
            checks.add("bad", False, "why")
            checks.add("truthy", 1)
        self.assertEqual([row["passed"] for row in checks.rows], [True, False, True])
        self.assertIn("PASS good\n", out.getvalue())
        self.assertIn("FAIL bad - why", out.getvalue())
        self.assertNotIn("ignored", out.getvalue())


class Command(unittest.TestCase):
    ROWS = [{"check": "a", "passed": True, "detail": ""}, {"check": "b", "passed": False, "detail": "x"}]

    def test_the_report_is_written_and_the_exit_status_says_whether_a_check_failed(self):
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "report.json"
            out = io.StringIO()
            with mock.patch.object(bench_ci, "run", return_value=self.ROWS), redirect_stdout(out):
                code = bench_ci.main(["--server-dir", folder, "--json", str(report)])
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(report.read_text(encoding="utf-8")), self.ROWS)
        self.assertIn("BENCH_CI=FAIL checks=2 failed=1", out.getvalue())

    def test_every_check_passing_is_exit_zero(self):
        out = io.StringIO()
        with mock.patch.object(bench_ci, "run", return_value=self.ROWS[:1]), redirect_stdout(out):
            self.assertEqual(bench_ci.main(["--server-dir", "."]), 0)
        self.assertIn("BENCH_CI=PASS checks=1 failed=0", out.getvalue())

    def test_a_bench_that_could_not_run_is_exit_two_with_the_reason(self):
        err = io.StringIO()
        with mock.patch.object(bench_ci, "run", side_effect=bench_ci.BenchError("no broker")), redirect_stderr(err):
            self.assertEqual(bench_ci.main(["--server-dir", "."]), 2)
        self.assertIn("bench: no broker", err.getvalue())

    def test_the_options_reach_the_run(self):
        with mock.patch.object(bench_ci, "run", return_value=[]) as run, redirect_stdout(io.StringIO()):
            bench_ci.main(["--server-dir", ".", "--mosquitto", "auto", "--shim-driver", "r", "--shim-electrical-driver", "e", "--shim-solar-driver", "s", "--shim-alarm-driver", "a",
                           "--shim-hmi-driver", "h", "--battery-loop"])
        arguments = run.call_args[0]
        self.assertEqual(arguments[1:], ("auto", "r", "e", "s", "a", "h", True))

    def test_the_simulator_and_the_shim_are_run_in_this_process_and_their_errors_come_back(self):
        code, said = bench_ci.simulate(["--no-such-option"])
        self.assertNotEqual(code, 0)
        self.assertTrue(said)
        def shim(argv):
            print("on the error output", file=sys.stderr)
            print("on the output")
            return 7
        with mock.patch.object(bench_ci.node_shim, "main", side_effect=shim):
            self.assertEqual(bench_ci.shim_main(["x"]), (7, "on the error output\n"))
        with mock.patch.object(bench_ci.cli, "main", side_effect=SystemExit("text exit")):
            self.assertEqual(bench_ci.simulate([])[0], 2)
        with mock.patch.object(bench_ci.cli, "main", side_effect=SystemExit(3)):
            self.assertEqual(bench_ci.simulate([])[0], 3)


class CameraChecks(WithStub):
    def test_a_server_that_refuses_everything_fails_the_checks_it_should_and_nothing_raises(self):
        Stub.routes[("POST", "*")] = (503, b"{}")
        Stub.routes[("GET", "*")] = (503, b"")
        checks = bench_ci.Check()
        with redirect_stdout(io.StringIO()), mock.patch.object(bench_ci, "wait_until", side_effect=bench_ci.BenchError("no stop")):
            bench_ci.camera_checks(checks, self.base, "operator-token")
        by_name = {row["check"]: row["passed"] for row in checks.rows}
        self.assertFalse(by_name["cameras: bench-walker is configured"])
        self.assertFalse(by_name["cameras: a preview ticket is given for a camera with a snapshot address"])
        self.assertFalse(by_name["cameras: the preview is the PNG the fake camera made"])
        self.assertFalse(by_name["ptz: a move reaches the head of a camera with a login"])
        self.assertFalse(by_name["ptz: the server stops the head by itself, so a lost stop never leaves it turning"])
        self.assertTrue(by_name["ptz: a camera with no credentials cannot be moved"] is False, "a 503 is neither a 409 nor a 502")

    def test_a_server_that_answers_as_a_good_one_does_for_the_pictures_passes_those_checks(self):
        Stub.routes[("POST", "/api/v1/cameras/configure")] = (200, {})
        Stub.routes[("POST", "/api/v1/cameras/bench-walker/preview-ticket")] = (201, {"path": "/api/v1/cameras/bench-walker/preview?t=1"})
        Stub.routes[("POST", "/api/v1/cameras/bench-broken/preview-ticket")] = (201, {"path": "/api/v1/cameras/bench-broken/preview?t=2"})
        Stub.routes[("GET", "/api/v1/cameras/bench-walker/preview?t=1")] = (200, bench_ci.PNG_MAGIC + b"\x00" * 8)
        Stub.routes[("GET", "/api/v1/cameras/bench-broken/preview?t=2")] = (502, b"")
        Stub.routes[("POST", "/api/v1/cameras/bench-fixed/ptz")] = (409, {})
        Stub.routes[("POST", "/api/v1/cameras/bench-mover/ptz")] = (502, {})
        Stub.routes[("POST", "/api/v1/cameras/bench-locked/ptz")] = (502, b'{"error":"login refused"}')
        checks = bench_ci.Check()
        with redirect_stdout(io.StringIO()), mock.patch.object(bench_ci, "wait_until", side_effect=bench_ci.BenchError("no stop")):
            bench_ci.camera_checks(checks, self.base, "operator-token")
        by_name = {row["check"]: row["passed"] for row in checks.rows}
        for name in ("cameras: bench-walker is configured", "cameras: bench-broken is configured",
                     "cameras: a preview ticket is given for a camera with a snapshot address", "cameras: the preview is the PNG the fake camera made",
                     "cameras: a camera that answers an error is a clean refusal (502)", "ptz: a command that is not one of the table is refused and the head is not told",
                     "ptz: a stored login the camera refuses is told as such and nothing moves", "ptz: a camera with no credentials cannot be moved"):
            self.assertTrue(by_name[name], name)
        self.assertFalse(by_name["ptz: a move reaches the head of a camera with a login"], "the stand-in server moved nothing")


if __name__ == "__main__":
    unittest.main()
