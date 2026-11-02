"""The virtual bench (docker/bench.sh): the commands it builds are accepted by the real command line, what it refuses, and a round delivered to a local server."""
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from armor_simulator.cli import build_parser

SCRIPT = ROOT / "docker" / "bench.sh"
SH = shutil.which("sh")


def bench(env: dict[str, str], extra_path: str | None = None) -> subprocess.CompletedProcess:
    base = {key: value for key, value in os.environ.items() if not key.startswith("ARMOR_")}
    base.update(env)
    if extra_path:
        base["PATH"] = extra_path + os.pathsep + base.get("PATH", "")
    assert SH is not None
    return subprocess.run([SH, str(SCRIPT).replace("\\", "/")], env=base, capture_output=True, text=True, timeout=60, check=False)


@unittest.skipUnless(SH, "no POSIX shell on this machine")
class BenchScriptTests(unittest.TestCase):
    def test_every_command_it_builds_is_accepted_by_the_real_parser(self):
        done = bench({"ARMOR_SIM_DRY_RUN": "1", "ARMOR_INGEST_TOKEN": "t" * 30, "ARMOR_SIM_NODES": "3", "ARMOR_SIM_SOLAR": "1", "ARMOR_SIM_ELECTRICAL": "1", "ARMOR_INGEST_STRICT": "1"})
        self.assertEqual(done.returncode, 0, done.stderr)
        lines = [line for line in done.stdout.splitlines() if line.startswith("armor-simulator ")]
        self.assertEqual(len(lines), 3)
        ids = set()
        for line in lines:
            args = build_parser().parse_args(shlex.split(line)[1:])
            ids.add(args.node_id)
            self.assertEqual(args.server_url, "http://server:8080")
            self.assertTrue(args.per_node_token and args.solar and args.electrical)
            self.assertEqual(args.start_ms, "now")
        self.assertEqual(ids, {"bench-1", "bench-2", "bench-3"})

    def test_the_token_never_reaches_a_command_line(self):
        done = bench({"ARMOR_SIM_DRY_RUN": "1", "ARMOR_INGEST_TOKEN": "secret-token-value-0123456789"})
        self.assertNotIn("secret-token-value", done.stdout + done.stderr)

    def test_a_token_file_is_handed_on_by_path(self):
        done = bench({"ARMOR_SIM_DRY_RUN": "1", "ARMOR_SIM_TOKEN_FILE": "/run/secrets/ingest"})
        self.assertIn("--ingest-token-file /run/secrets/ingest", done.stdout)

    def test_it_refuses_what_it_should(self):
        token = {"ARMOR_INGEST_TOKEN": "t" * 30, "ARMOR_SIM_DRY_RUN": "1"}
        for bad in ({"ARMOR_SIM_NODES": "0"}, {"ARMOR_SIM_NODES": "9"}, {"ARMOR_SIM_NODES": "x"}, {"ARMOR_SIM_NODE_PREFIX": "Bad Name"},
                    {"ARMOR_SIM_SERVER_URL": "ftp://server"}, {"ARMOR_SIM_ROUND_SAMPLES": "0"}, {"ARMOR_SIM_INTERVAL_MS": "-1"}):
            with self.subTest(bad=bad):
                self.assertEqual(bench({**token, **bad}).returncode, 2)
        self.assertEqual(bench({"ARMOR_SIM_DRY_RUN": "1"}).returncode, 2)

    def test_a_round_reaches_a_server(self):
        received: list[tuple[str, str]] = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - the name the standard library calls
                length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(length)
                received.append((self.path, self.headers.get("Authorization", "") + self.headers.get("X-Armor-Token", "")))
                self.send_response(202)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True}).encode())

            def log_message(self, *args):  # noqa: D401 - silence
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                shim = Path(folder) / "armor-simulator"
                shim.write_text(f'#!/bin/sh\nexec "{sys.executable.replace(chr(92), "/")}" -I -c "import sys; sys.path.insert(0, \'{(ROOT / "src").as_posix()}\'); from armor_simulator.cli import main; sys.exit(main(sys.argv[1:]))" "$@"\n', encoding="utf-8", newline="\n")
                shim.chmod(0o755)
                done = bench({"ARMOR_SIM_NODES": "2", "ARMOR_SIM_ROUNDS": "1", "ARMOR_SIM_ROUND_SAMPLES": "3", "ARMOR_SIM_INTERVAL_MS": "0", "ARMOR_INGEST_TOKEN": "t" * 30,
                              "ARMOR_SIM_SERVER_URL": f"http://127.0.0.1:{server.server_address[1]}"}, extra_path=folder.replace("\\", "/"))
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("done after 1 round", done.stdout)
        self.assertGreaterEqual(len(received), 6)


if __name__ == "__main__":
    unittest.main()
