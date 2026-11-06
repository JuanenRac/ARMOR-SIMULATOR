"""Record and replay of a run, and the faults of the delivery to a server."""
import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from armor_simulator.cli import main
from armor_simulator.http_faults import plan
from armor_simulator.recording import RecordingError, load_recording


def run(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch.dict(os.environ, {}):
        os.environ.pop("ARMOR_INGEST_TOKEN", None)
        try:
            code = main(list(args))
        except SystemExit as exit_:
            code = exit_.code
    return code, out.getvalue(), err.getvalue()


class Counter(BaseHTTPRequestHandler):
    posts = 0

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers["Content-Length"]))
        Counter.posts += 1
        self.send_response(202)
        self.end_headers()

    def log_message(self, *args):
        pass


class RecordingTests(unittest.TestCase):
    def test_a_recording_plays_back_the_same_messages(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "run.jsonl"
            code, first, err = run("--count", "4", "--seed", "7", "--record", str(path))
            self.assertEqual(code, 0, err)
            self.assertEqual(len(load_recording(path)), len(first.splitlines()))
            code, second, err = run("--replay", str(path))
            self.assertEqual(code, 0, err)
            self.assertEqual(first, second)

    def test_a_recording_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "run.jsonl"
            path.write_text("keep\n", encoding="utf-8")
            code, _out, err = run("--count", "1", "--record", str(path))
            self.assertEqual(code, 2)
            self.assertIn("already exists", err)
            self.assertEqual(path.read_text(encoding="utf-8"), "keep\n")

    def test_a_bad_recording_is_refused_whole(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.jsonl"
            good = json.dumps({"topic": "armor/node/a/health", "payload": {"x": 1}})
            for text in (good + "\nnot json\n", good + '\n{"topic":"armor/x","payload":NaN}\n', '{"topic":"other/x","payload":{}}\n',
                         '{"topic":"armor/x","payload":{},"extra":1}\n', "\n"):
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(RecordingError):
                    load_recording(path)
                code, out, _err = run("--replay", str(path))
                self.assertEqual((code, out), (2, ""))
            path.write_text(good, encoding="utf-8")
            with self.assertRaises(RecordingError):
                load_recording(path, max_bytes=5)

    def test_a_recording_made_by_a_server_keeps_its_time_and_its_refusals_and_plays_them(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "server.jsonl"
            lines = [
                {"topic": "armor/node/a/telemetry", "payload": {"x": 1}, "at": "2000-01-01T00:00:00Z", "accepted": True},
                {"topic": "armor/node/a/telemetry", "payload": {"x": "bad"}, "at": "2000-01-01T00:00:01Z", "accepted": False, "reason": "x must be a number"},
                {"topic": "armor/node/a/health", "payload": {}},
            ]
            path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
            self.assertEqual(len(load_recording(path)), 3)   # the refused message is played too: the same refusal happens again
            self.assertEqual([topic for topic, _ in load_recording(path, accepted_only=True)], ["armor/node/a/telemetry", "armor/node/a/health"])
            code, out, err = run("--replay", str(path))
            self.assertEqual((code, len(out.splitlines())), (0, 3), err)
            code, out, err = run("--replay", str(path), "--replay-accepted-only")
            self.assertEqual((code, len(out.splitlines())), (0, 2), err)
            self.assertEqual(run("--replay-accepted-only")[0], 2)   # it only means something with --replay

    def test_the_extra_fields_of_a_server_recording_are_checked(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "server.jsonl"
            base = {"topic": "armor/x", "payload": {}}
            for extra in ({"at": 5}, {"accepted": "yes"}, {"reason": 7}, {"reason": "r" * 201}, {"other": 1}):
                path.write_text(json.dumps({**base, **extra}) + "\n", encoding="utf-8")
                with self.assertRaises(RecordingError):
                    load_recording(path)

    def test_replay_does_not_mix_with_generators(self):
        self.assertEqual(run("--replay", "x.jsonl", "--count", "3")[0], 2)
        self.assertEqual(run("--replay", "x.jsonl", "--energy")[0], 2)
        self.assertEqual(run("--replay", "same", "--record", "same")[0], 2)

    def test_a_replay_can_still_carry_a_fault(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "run.jsonl"
            run("--count", "6", "--health-every", "0", "--record", str(path))
            code, out, err = run("--replay", str(path), "--fault", "node-silent", "--fault-every", "2")
            self.assertEqual(code, 0, err)
            self.assertEqual(len(out.splitlines()), 2)


class DeliveryFaultTests(unittest.TestCase):
    def test_the_plan_is_every_nth_message(self):
        self.assertEqual([plan("drop", n, 3, 0).sends for n in range(1, 7)], [1, 1, 0, 1, 1, 0])
        self.assertEqual([plan("duplicate", n, 2, 0).sends for n in range(1, 5)], [1, 2, 1, 2])
        self.assertEqual(plan("latency", 3, 3, 40).delay_ms, 40)
        self.assertEqual(plan("none", 3, 3, 40).sends, 1)
        with self.assertRaises(ValueError):
            plan("explode", 3, 3, 0)

    def test_the_server_sees_the_fault(self):
        Counter.posts = 0
        server = HTTPServer(("127.0.0.1", 0), Counter)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_address[1]}"
        base = ("--count", "6", "--health-every", "0", "--server-url", url, "--ingest-token", "t")
        code, _out, err = run(*base, "--http-fault", "drop", "--http-fault-every", "3")
        self.assertEqual(code, 0, err)
        self.assertEqual(Counter.posts, 4)
        self.assertIn("2 message(s) not sent", err)
        Counter.posts = 0
        code, _out, err = run(*base, "--http-fault", "duplicate", "--http-fault-every", "2")
        self.assertEqual((code, Counter.posts), (0, 9))
        code, _out, err = run(*base, "--http-fault", "latency", "--http-fault-every", "3", "--http-latency-ms", "1")
        self.assertIn("2 delayed", err)

    def test_a_delivery_fault_needs_a_server_and_sane_numbers(self):
        self.assertEqual(run("--http-fault", "drop")[0], 2)
        self.assertEqual(run("--http-fault", "drop", "--server-url", "http://127.0.0.1:1", "--ingest-token", "t", "--http-fault-every", "0")[0], 2)
        self.assertEqual(run("--http-fault", "latency", "--server-url", "http://127.0.0.1:1", "--ingest-token", "t", "--http-latency-ms", "999999")[0], 2)


if __name__ == "__main__":
    unittest.main()
