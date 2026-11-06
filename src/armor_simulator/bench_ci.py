"""The virtual bench without Docker: a real ARMOR-SERVER, built, on this machine, fed by the simulator over HTTP and (when a broker is at hand) over MQTT.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

    python -m armor_simulator.bench_ci --server-dir ../ARMOR-SERVER                    # the server must have been built (npm ci && npm run build)
    python -m armor_simulator.bench_ci --server-dir ../ARMOR-SERVER --mosquitto auto   # also the road through a broker, when mosquitto is installed

It is what `docker/bench.sh` does with the compose file of ARMOR-DEVOPS, without Docker, so that it can run in the continuous integration of a repository and on a laptop. It starts
the server it is given with secrets made up for the run (never printed, never written outside a temporary folder that is removed at the end) on a free loopback port, and checks:

    http        patrol, solar and electrical messages are accepted and the nodes show in the status of the server
    refusals    messages spoiled on purpose (an impossible light value) are refused, and the server goes on
    delivery    a message sent twice and a slow link do not break it
    replay      a recording made by a server from its own traffic (examples/recordings/incident.jsonl) is played again: the accepted messages arrive, and the refused one is
                refused again for the same reason (with --replay-accepted-only the refusal is left out)
    replay      the same with a recording of the HTTP reports of an alarm panel, a meter, a solar device and a network node (examples/recordings/http_routes.jsonl)
    mqtt        (with a broker) a node that only exists on the broker shows in the status of the server

The only process it starts besides the server is the broker, and the only ones it stops are the two it started. Nothing is sent outside this machine. The server and the broker are
real; the nodes and what they sense are simulated, so a green run says the software side works against a simulated installation and nothing about a board.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import cli

ROOT = Path(__file__).resolve().parent.parent.parent
RECORDING = ROOT / "examples" / "recordings" / "incident.jsonl"
RECORDING_HTTP = ROOT / "examples" / "recordings" / "http_routes.jsonl"
START_TIMEOUT_S = 40


class BenchError(RuntimeError):
    """The bench could not be run (not a failed check)."""


def free_port() -> int:
    with contextlib.closing(socket.socket()) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def get(url: str, bearer: str | None = None, timeout: float = 5.0) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {bearer}"} if bearer else {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:  # noqa: S310 - a loopback address chosen here
            return reply.status, reply.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def wait_until(check, seconds: float, what: str):
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        try:
            last = check()
            if last:
                return last
        except (OSError, urllib.error.URLError, ValueError) as error:
            last = None
            _ = error
        time.sleep(0.25)
    raise BenchError(f"{what} did not happen within {seconds:.0f} s")


def _reachable(port: int) -> bool:
    with socket.create_connection(("127.0.0.1", port), 1):
        return True


def simulate(argv: list[str]) -> tuple[int, str]:
    """Runs the command line of the simulator in this process; gives its exit status and what it said on its error output."""
    err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        try:
            code = cli.main(argv)
        except SystemExit as stop:
            code = int(stop.code or 0) if isinstance(stop.code, int) else 2
    return code, err.getvalue()


class Check:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.rows.append({"check": name, "passed": bool(passed), "detail": detail})
        print(f"{'PASS' if passed else 'FAIL'} {name}{' - ' + detail if detail and not passed else ''}", flush=True)


def run(server_dir: Path, mosquitto: str | None) -> list[dict]:
    entry = server_dir / "dist" / "server.mjs"
    node = shutil.which("node")
    if not entry.is_file() or not node:
        raise BenchError(f"{entry} is not there or node is not installed: build the server first (npm ci && npm run build)")
    checks = Check()
    work = Path(tempfile.mkdtemp(prefix="armor-bench-"))
    port = free_port()
    secrets_ = {name: secrets.token_hex(16) for name in ("ARMOR_INGEST_TOKEN", "ARMOR_CONTROL_TOKEN", "ARMOR_OPERATOR_TOKEN", "ARMOR_CAMERA_CONFIG_KEY")}
    env = {key: os.environ[key] for key in ("PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "TMP", "TEMP", "TMPDIR") if key in os.environ}
    env.update(secrets_, ARMOR_DATA_DIR=str(work / "data"), ARMOR_HOST="127.0.0.1", ARMOR_PORT=str(port), ARMOR_TZ="UTC", ARMOR_STUDIO_USERNAME="admin", ARMOR_STUDIO_PASSWORD=secrets.token_hex(12))
    children: list[subprocess.Popen] = []
    broker_port = None
    try:
        if mosquitto:
            program = shutil.which("mosquitto") if mosquitto == "auto" else mosquitto
            if program:
                broker_port = free_port()
                conf = work / "mosquitto.conf"
                conf.write_text(f"listener {broker_port} 127.0.0.1\nallow_anonymous true\npersistence false\n", encoding="utf-8")
                children.append(subprocess.Popen([program, "-c", str(conf)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))  # noqa: S603
                wait_until(lambda: _reachable(broker_port), 15, "the broker")
                env["ARMOR_MQTT_URL"] = f"mqtt://127.0.0.1:{broker_port}"
            elif mosquitto != "auto":
                raise BenchError(f"{mosquitto} is not a program")
        log = (work / "server.log").open("w", encoding="utf-8")
        children.append(subprocess.Popen([node, str(entry)], cwd=server_dir, env=env, stdout=log, stderr=subprocess.STDOUT))  # noqa: S603
        base = f"http://127.0.0.1:{port}"
        try:
            wait_until(lambda: get(f"{base}/healthz")[0] == 200, START_TIMEOUT_S, "the server")
        except BenchError:
            raise BenchError("the server did not start; its log:\n" + (work / "server.log").read_text(encoding="utf-8", errors="replace")[-1500:]) from None
        checks.add("server starts", True)
        operator = secrets_["ARMOR_OPERATOR_TOKEN"]
        os.environ["ARMOR_INGEST_TOKEN"] = secrets_["ARMOR_INGEST_TOKEN"]

        def nodes() -> dict:
            status, body = get(f"{base}/api/v1/status", operator)
            return json.loads(body).get("nodes", {}) if status == 200 else {}

        # http
        code, said = simulate(["--node-id", "bench-1", "--count", "12", "--scenario", "patrol", "--solar", "--electrical", "--server-url", base])
        checks.add("http: patrol, solar and electrical are accepted", code == 0, said[-300:])
        seen = nodes()
        checks.add("http: the node shows in the status of the server", "bench-1" in seen, f"nodes: {sorted(seen)}")
        # refusals
        code, said = simulate(["--node-id", "bench-2", "--count", "9", "--fault", "corrupt-lux", "--fault-every", "3", "--allow-invalid", "--server-url", base])
        refused = "were refused" in said and ", 0 were refused" not in said
        checks.add("refusals: impossible readings are refused", code == 0 and refused, said[-300:])
        checks.add("refusals: the server goes on", get(f"{base}/healthz")[0] == 200)
        # delivery
        code, said = simulate(["--node-id", "bench-3", "--count", "9", "--http-fault", "duplicate", "--http-fault-every", "2", "--server-url", base])
        checks.add("delivery: a message sent twice does not break it", code == 0 and "bench-3" in nodes(), said[-300:])
        code, said = simulate(["--node-id", "bench-4", "--count", "6", "--http-fault", "latency", "--http-latency-ms", "200", "--http-fault-every", "2", "--server-url", base])
        checks.add("delivery: a slow link does not break it", code == 0 and "bench-4" in nodes(), said[-300:])
        # replay
        code, said = simulate(["--replay", str(RECORDING), "--replay-accepted-only", "--server-url", base])
        checks.add("replay: the accepted messages of a recording arrive", code == 0 and "incident-1" in nodes(), said[-300:])
        code, said = simulate(["--replay", str(RECORDING), "--server-url", base])
        checks.add("replay: the message the server refused is refused again", code == 1 and "armor-simulator:" in said, f"status {code}: {said[-300:]}")
        # replay of what a server copied from its HTTP routes (alarm, electrical, solar and network reports)
        def listed(route: str, key: str) -> list:
            status, body = get(f"{base}{route}", operator)
            return json.loads(body).get(key, []) if status == 200 else []

        code, said = simulate(["--replay", str(RECORDING_HTTP), "--replay-accepted-only", "--server-url", base])
        panels = [item.get("node_id") for item in listed("/api/v1/alarm/nodes", "nodes")]
        meters = [item.get("node_id") for item in listed("/api/v1/electrical/readings", "nodes")]
        checks.add("replay: the HTTP routes of a recording (alarm, electrical, solar, network) arrive", code == 0 and "alarm-http" in panels and "http-1" in meters, f"status {code}, alarm {panels}, electrical {meters}: {said[-200:]}")
        code, said = simulate(["--replay", str(RECORDING_HTTP), "--server-url", base])
        checks.add("replay: the alarm report the server refused over HTTP is refused again", code == 1 and "armor-simulator:" in said, f"status {code}: {said[-300:]}")
        # mqtt
        if broker_port:
            os.environ.pop("ARMOR_INGEST_TOKEN", None)       # the broker road takes no ingest token, and the simulator refuses one without a server address
            code, said = simulate(["--node-id", "mqtt-1", "--count", "6", "--mqtt-url", f"mqtt://127.0.0.1:{broker_port}"])
            if code != 0 and "paho" in said.lower():
                raise BenchError("paho-mqtt is not installed (pip install paho-mqtt)")
            appeared = False
            try:
                appeared = bool(wait_until(lambda: "mqtt-1" in nodes(), 15, "the node on the broker"))
            except BenchError:
                pass
            checks.add("mqtt: a node that only exists on the broker shows in the status", code == 0 and appeared, said[-300:])
        else:
            print("SKIP mqtt: no broker (install mosquitto and pass --mosquitto auto)")
        checks.add("server still answers at the end", get(f"{base}/healthz")[0] == 200)
        return checks.rows
    finally:
        for child in reversed(children):
            child.terminate()
            try:
                child.wait(10)
            except subprocess.TimeoutExpired:
                child.kill()
        shutil.rmtree(work, ignore_errors=True)
        os.environ.pop("ARMOR_INGEST_TOKEN", None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="armor_simulator.bench_ci", description=__doc__.split("\n\n")[0])
    parser.add_argument("--server-dir", type=Path, required=True, help="the ARMOR-SERVER folder, built (dist/server.mjs)")
    parser.add_argument("--mosquitto", help="a mosquitto program, or 'auto' to look for it; with one, the road through the broker is checked too")
    parser.add_argument("--json", type=Path, metavar="FILE", help="also write the report there")
    args = parser.parse_args(argv)
    try:
        rows = run(args.server_dir.resolve(), args.mosquitto)
    except (BenchError, OSError) as error:
        print(f"bench: {error}", file=sys.stderr)
        return 2
    if args.json:
        args.json.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    failed = [row for row in rows if not row["passed"]]
    print(f"BENCH_CI={'FAIL' if failed else 'PASS'} checks={len(rows)} failed={len(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
