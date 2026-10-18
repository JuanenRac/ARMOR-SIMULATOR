"""The options of the command line that decide what leaves the simulator: where the token comes from, the dates, the combinations that are refused and what is said about a server that accepts what it should refuse."""
import contextlib
import hashlib
import hmac
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

from armor_simulator import cli
from armor_simulator.cli import _is_invalid, _stamp, _token, build_parser, main, messages


def run(*args, env=None):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err), mock.patch.dict(os.environ, env or {}):
        os.environ.pop("ARMOR_INGEST_TOKEN", None) if env is None else None
        try:
            code = main(list(args))
        except SystemExit as exit_:
            code = exit_.code
    return code, out.getvalue(), err.getvalue()


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


class TokenTests(unittest.TestCase):
    def parse(self, *arguments):
        return build_parser().parse_args(arguments)

    def test_the_option_wins_then_the_file_then_the_environment(self):
        with tempfile.TemporaryDirectory() as folder, mock.patch.dict(os.environ, {"ARMOR_INGEST_TOKEN": " from-env "}):
            path = Path(folder) / "token"
            path.write_text("OTHER=1\nARMOR_INGEST_TOKEN=from-file\n", encoding="utf-8")
            self.assertEqual(_token(self.parse("--ingest-token", "from-option", "--ingest-token-file", str(path))), "from-option")
            self.assertEqual(_token(self.parse("--ingest-token-file", str(path))), "from-file")
            self.assertEqual(_token(self.parse()), "from-env")

    def test_a_file_may_hold_only_the_token_or_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "token"
            path.write_text("  just-the-token  \nsecond line\n", encoding="utf-8")
            self.assertEqual(_token(self.parse("--ingest-token-file", str(path))), "just-the-token")
            path.write_text("", encoding="utf-8")
            self.assertEqual(_token(self.parse("--ingest-token-file", str(path))), "")

    def test_no_token_anywhere_is_an_empty_token(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ARMOR_INGEST_TOKEN", None)
            self.assertEqual(_token(self.parse()), "")

    def test_a_server_and_a_token_go_together(self):
        self.assertEqual(run("--server-url", "http://127.0.0.1:1")[0], 2)
        self.assertEqual(run("--ingest-token", "x")[0], 2)
        code, _out, _err = run("--count", "1", env={"ARMOR_INGEST_TOKEN": "from-env"})
        self.assertEqual(code, 2)                                                       # a token with nowhere to go is a mistake, not something to ignore

    def test_the_token_from_the_environment_reaches_the_server_and_the_file_never_prints_it(self):
        Capture.statuses, Capture.seen = [], []
        server = HTTPServer(("127.0.0.1", 0), Capture)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_address[1]}"
        code, out, err = run("--count", "1", "--health-every", "0", "--server-url", url, env={"ARMOR_INGEST_TOKEN": "secret-env-token"})
        self.assertEqual(code, 0, err)
        self.assertEqual(Capture.seen[0][1], "Bearer secret-env-token")
        self.assertNotIn("secret-env-token", out + err)

    def test_the_per_node_token_is_the_derived_one(self):
        Capture.statuses, Capture.seen = [], []
        server = HTTPServer(("127.0.0.1", 0), Capture)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_address[1]}"
        code, _out, err = run("--count", "1", "--health-every", "0", "--node-id", "north-1", "--server-url", url, "--ingest-token", "ingest", "--per-node-token")
        self.assertEqual(code, 0, err)
        expected = hmac.new(b"ingest", b"armor-node:north-1", hashlib.sha256).hexdigest()
        self.assertEqual(Capture.seen[0][1], f"Bearer {expected}")


class DateTests(unittest.TestCase):
    def test_start_ms_is_added_to_every_dated_message_and_zero_changes_nothing(self):
        stream = [("t", {"timestamp_ms": 1000}), ("t", {"timestamp_ms": 2000}), ("t", {"no": "date"}), ("t", {"timestamp_ms": "text"})]
        self.assertEqual(list(_stamp(iter(stream), 0)), stream)
        shifted = list(_stamp(iter(stream), 5))
        self.assertEqual([payload.get("timestamp_ms") for _t, payload in shifted], [1005, 2005, None, "text"])
        self.assertEqual(stream[0][1]["timestamp_ms"], 1000)                              # the original message is not modified

    def test_now_uses_the_clock_and_a_number_is_taken_as_it_is(self):
        with mock.patch.object(cli.time, "time", return_value=1_700_000_000.5):
            code, out, _ = run("--count", "1", "--health-every", "0", "--start-ms", "now")
        self.assertEqual(code, 0)
        self.assertGreaterEqual(json.loads(out.splitlines()[0])["payload"]["timestamp_ms"], 1_700_000_000_500)
        code, out, _ = run("--count", "1", "--health-every", "0", "--start-ms", "42")
        self.assertGreaterEqual(json.loads(out.splitlines()[0])["payload"]["timestamp_ms"], 42)

    def test_a_date_that_is_not_a_number_or_is_negative_is_refused(self):
        for value in ("tomorrow", "-5", "1.5", ""):
            self.assertEqual(run("--start-ms", value)[0], 2, value)


class RefusedCombinationTests(unittest.TestCase):
    def test_each_combination_that_cannot_work_is_refused_with_its_reason(self):
        cases = [
            (["--fault", "flapping", "--health-every", "0"], "flapping needs health"),
            (["--fault", "duplicates", "--fault-every", "0"], "needs --fault-every of at least 1"),
            (["--fault", "corrupt-lux", "--fault-every", "0", "--allow-invalid"], "needs --fault-every of at least 1"),
            (["--fault", "corrupt-lux", "--fault-every", "1"], "--allow-invalid"),
            (["--fault", "corrupt-lux", "--fault-every", "1", "--allow-invalid", "--validate"], "contradict"),
            (["--health-every", "-1"], "must not be negative"),
            (["--fault-every", "-1"], "must not be negative"),
            (["--node-id", "UPPER"], "--node-id"),
            (["--node-id", "-leading"], "--node-id"),
            (["--node-id", "a" * 65], "--node-id"),
            (["--count", "abc"], "invalid int"),
            (["--scenario", "nonsense"], "invalid choice"),
        ]
        for arguments, fragment in cases:
            code, _out, err = run(*arguments)
            self.assertEqual(code, 2, arguments)
            self.assertIn(fragment, err, arguments)

    def test_the_server_address_with_a_path_or_secret_is_refused(self):
        for url in ("http://u:p@127.0.0.1:1", "http://127.0.0.1:1/api", "ftp://127.0.0.1"):
            with self.assertRaises(ValueError):
                cli.check_server_url(url)

    def test_the_longest_name_and_the_largest_count_are_accepted(self):
        self.assertEqual(run("--node-id", "a" * 64, "--count", "1", "--health-every", "0")[0], 0)
        self.assertEqual(run("--node-id", "0", "--count", "1", "--health-every", "0")[0], 0)


class StreamTests(unittest.TestCase):
    def test_a_health_beat_is_sent_every_n_samples_starting_with_the_first(self):
        topics = [topic for topic, _payload in messages("n", 6, "patrol", "cycle", 0, 3)]
        self.assertEqual(topics.count("armor/node/n/telemetry"), 6)
        self.assertEqual(topics.count("armor/node/n/health"), 2)
        self.assertEqual(topics[0:2], ["armor/node/n/telemetry", "armor/node/n/health"])

    def test_no_health_when_it_is_off_and_extra_streams_only_when_asked(self):
        plain = [topic for topic, _payload in messages("n", 3, "patrol", "cycle", 0, 0)]
        self.assertTrue(all(topic.endswith("/telemetry") for topic in plain))
        both = [topic for topic, _payload in messages("n", 2, "patrol", "cycle", 0, 0, solar=True, electrical=True)]
        self.assertTrue(any(topic.startswith("armor/solar/") for topic in both))
        self.assertTrue(any(topic.startswith("armor/electrical/") for topic in both))

    def test_the_same_seed_is_the_same_bytes_and_another_seed_is_not(self):
        first = run("--count", "5", "--seed", "7", "--scenario", "crossing")[1]
        self.assertEqual(first, run("--count", "5", "--seed", "7", "--scenario", "crossing")[1])
        self.assertNotEqual(first, run("--count", "5", "--seed", "8", "--scenario", "crossing")[1])

    def test_every_line_is_compact_sorted_json(self):
        _code, out, _err = run("--count", "2")
        for line in out.splitlines():
            envelope = json.loads(line)
            self.assertEqual(line, json.dumps(envelope, separators=(",", ":"), sort_keys=True))

    def test_the_interval_is_a_real_pause_between_messages(self):
        with mock.patch.object(cli.time, "sleep") as sleep:
            run("--count", "3", "--health-every", "0", "--interval-ms", "250")
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.25, 0.25, 0.25])
        with mock.patch.object(cli.time, "sleep") as sleep:
            run("--count", "3", "--health-every", "0")
        sleep.assert_not_called()


class ValidationTests(unittest.TestCase):
    def test_a_message_the_contract_refuses_stops_the_run_and_says_where(self):
        calls = []

        def validate(topic, payload):
            calls.append(topic)
            if len(calls) == 2:
                raise ValueError("lux out of range")

        def never(topic, payload):
            raise AssertionError("the solar validator was not expected")

        with mock.patch.object(cli, "_common_validators", return_value=(validate, never, never)):
            code, out, err = run("--count", "3", "--health-every", "1", "--validate")
        self.assertEqual(code, 1)
        self.assertIn("message 2", err)
        self.assertIn("lux out of range", err)
        self.assertEqual(len(out.splitlines()), 1)                                        # nothing after the first bad message is emitted

    def test_each_kind_of_message_goes_to_its_own_validator(self):
        seen = {"node": [], "solar": [], "electrical": []}
        validators = (lambda t, p: seen["node"].append(t), lambda t, p: seen["solar"].append(t), lambda t, p: seen["electrical"].append(t))
        with mock.patch.object(cli, "_common_validators", return_value=validators):
            code, _out, _err = run("--count", "1", "--health-every", "1", "--solar", "--electrical", "--validate")
        self.assertEqual(code, 0)
        self.assertTrue(all(topic.startswith("armor/node/") for topic in seen["node"]) and seen["node"])
        self.assertTrue(all(topic.startswith("armor/solar/") for topic in seen["solar"]) and seen["solar"])
        self.assertTrue(all(topic.startswith("armor/electrical/") for topic in seen["electrical"]) and seen["electrical"])


class InvalidFaultReportTests(unittest.TestCase):
    def test_what_marks_a_message_as_spoiled(self):
        self.assertTrue(_is_invalid("corrupt-lux", "armor/node/n/telemetry", {"lux": 1_000_000_000}))
        self.assertFalse(_is_invalid("corrupt-lux", "armor/node/n/telemetry", {"lux": 100}))
        self.assertFalse(_is_invalid("corrupt-lux", "armor/node/n/health", {"lux": 1_000_000_000}))
        self.assertTrue(_is_invalid("unknown-field", "armor/node/n/health", {"firmware_debug": 1}))
        self.assertFalse(_is_invalid("unknown-field", "armor/node/n/health", {}))
        self.assertTrue(_is_invalid("oversized-targets", "armor/node/n/telemetry", {"targets": list(range(16))}))
        self.assertFalse(_is_invalid("oversized-targets", "armor/node/n/telemetry", {"targets": list(range(15))}))

    def test_a_server_that_accepts_what_it_should_refuse_is_counted_and_said(self):
        Capture.statuses, Capture.seen = [], []
        server = HTTPServer(("127.0.0.1", 0), Capture)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f"http://127.0.0.1:{server.server_address[1]}"
        code, _out, err = run("--count", "3", "--health-every", "0", "--fault", "corrupt-lux", "--fault-every", "1", "--allow-invalid", "--server-url", url, "--ingest-token", "tok")
        self.assertEqual(code, 0)
        self.assertIn("0 were refused and 3 were accepted", err)
        Capture.statuses = [400, 400, 400]
        code, _out, err = run("--count", "3", "--health-every", "0", "--fault", "corrupt-lux", "--fault-every", "1", "--allow-invalid", "--server-url", url, "--ingest-token", "tok")
        self.assertEqual(code, 0)
        self.assertIn("refused as expected", err)
        self.assertIn("3 were refused and 0 were accepted", err)


if __name__ == "__main__":
    unittest.main()
