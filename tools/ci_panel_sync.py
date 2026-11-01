#!/usr/bin/env python3
"""Checks the panel sync against a real ARMOR-SERVER and a real Mosquitto, on this machine.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

What it starts, all on 127.0.0.1, in a folder of its own that is deleted at the end:
  * Mosquitto (`mosquitto -c ...`), listening on a free loopback port, with no persistence;
  * ARMOR-SERVER (`node dist/server.mjs` of the sibling checkout, built beforehand), on that broker, with a throw-away data folder, an administrator made for the run
    and ARMOR_ALARM_COMMANDS=1;
  * then it turns on the two settings of the arming modes and runs `python -m armor_simulator --verify-panel-sync --verify-panel-map`: a simulated alarm panel on the broker
    answers each command as it is told to, and the report of the server is compared with what must be true.

    python tools/ci_panel_sync.py                 # needs: mosquitto, node, the server built (npm ci && npm run build there), paho-mqtt installed
    python tools/ci_panel_sync.py --keep-going    # print the output of the server and the broker even when the check passes

Environment (all optional): ARMOR_SERVER_DIR (default ../ARMOR-SERVER), MOSQUITTO_BIN, NODE_BIN.
The exit code is the one of the check (0: the server did what must be true; 1: it did not; 2: the check could not run).
"""
from __future__ import annotations

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

SIMULATOR = Path(__file__).resolve().parents[1]
SERVER = Path(os.environ.get("ARMOR_SERVER_DIR", SIMULATOR.parent / "ARMOR-SERVER"))
USER = "admin"


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def wait_port(port: int, process: subprocess.Popen[bytes], what: str, seconds: float = 30.0) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if process.poll() is not None:
            raise RuntimeError(f"{what} stopped at once (exit code {process.returncode})")
        with socket.socket() as probe:
            probe.settimeout(0.3)
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.2)
    raise RuntimeError(f"{what} did not listen on port {port} in {seconds:.0f} seconds")


def call(base: str, method: str, route: str, body: object | None = None, cookie: str = "") -> tuple[int, object, str]:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json", "X-Requested-With": "armor"}
    if cookie:
        headers["Cookie"] = cookie
    request = urllib.request.Request(base + route, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as reply:
            return reply.status, json.loads(reply.read() or b"{}"), reply.headers.get("Set-Cookie", "")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf8", "replace")[:300], ""


def main() -> int:
    keep_going = "--keep-going" in sys.argv
    mosquitto = os.environ.get("MOSQUITTO_BIN") or shutil.which("mosquitto")
    node = os.environ.get("NODE_BIN") or shutil.which("node")
    if not mosquitto or not node:
        print("ci_panel_sync: needs mosquitto and node on the path (MOSQUITTO_BIN, NODE_BIN)", file=sys.stderr)
        return 2
    if not (SERVER / "dist" / "server.mjs").is_file():
        print(f"ci_panel_sync: {SERVER}/dist/server.mjs is not there: build the server first (npm ci && npm run build)", file=sys.stderr)
        return 2
    work = Path(tempfile.mkdtemp(prefix="armor-panel-sync-"))
    children: list[tuple[str, subprocess.Popen[bytes], Path]] = []
    try:
        broker_port, server_port = free_port(), free_port()
        conf = work / "mosquitto.conf"
        conf.write_text(f"listener {broker_port} 127.0.0.1\nallow_anonymous true\npersistence false\n", encoding="utf8")
        broker_log = work / "mosquitto.log"
        broker = subprocess.Popen([mosquitto, "-c", str(conf)], stdout=broker_log.open("wb"), stderr=subprocess.STDOUT)
        children.append(("mosquitto", broker, broker_log))
        wait_port(broker_port, broker, "mosquitto")

        password = secrets.token_urlsafe(24)
        data = work / "data"
        data.mkdir()
        server_log = work / "server.log"
        env = {
            **os.environ, "ARMOR_HOST": "127.0.0.1", "ARMOR_PORT": str(server_port), "ARMOR_DATA_DIR": str(data), "ARMOR_TZ": "UTC",
            "ARMOR_INGEST_TOKEN": secrets.token_urlsafe(32), "ARMOR_CONTROL_TOKEN": secrets.token_urlsafe(32), "ARMOR_OPERATOR_TOKEN": secrets.token_urlsafe(32),
            "ARMOR_STUDIO_USERNAME": USER, "ARMOR_STUDIO_PASSWORD": password, "ARMOR_STUDIO_ORIGIN": f"http://127.0.0.1:{server_port}",
            "ARMOR_MQTT_URL": f"mqtt://127.0.0.1:{broker_port}", "ARMOR_ALARM_COMMANDS": "1",
        }
        server = subprocess.Popen([node, "dist/server.mjs"], cwd=SERVER, env=env, stdout=server_log.open("wb"), stderr=subprocess.STDOUT)
        children.append(("server", server, server_log))
        wait_port(server_port, server, "the server")
        base = f"http://127.0.0.1:{server_port}"

        status, _, cookie = call(base, "POST", "/api/v1/studio/session", {"username": USER, "password": password})
        if status != 201 or not cookie:
            print(f"ci_panel_sync: the sign-in of the throw-away server answered {status}", file=sys.stderr)
            return 2
        session = cookie.split(";")[0]
        status, answer, _ = call(base, "PUT", "/api/v1/security/settings", {"alarm.arming_modes": True, "alarm.mode_panel_sync": True}, session)
        if status != 200:
            print(f"ci_panel_sync: the two settings of the modes were refused ({status}): {answer}", file=sys.stderr)
            return 2

        check = subprocess.run(
            [sys.executable, "-m", "armor_simulator", "--verify-panel-sync", "--verify-panel-map", "--server-url", base, "--studio-user", USER, "--mqtt-url", f"mqtt://127.0.0.1:{broker_port}"],
            cwd=SIMULATOR, env={**os.environ, "PYTHONPATH": str(SIMULATOR / "src"), "ARMOR_STUDIO_PASSWORD": password}, timeout=600, check=False,
        )
        if check.returncode != 0 or keep_going:
            for name, _, log in children:
                print(f"--- {name} ---", file=sys.stderr)
                print(log.read_text(encoding="utf8", errors="replace")[-3000:], file=sys.stderr)
        return check.returncode
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"ci_panel_sync: {error}", file=sys.stderr)
        for name, _, log in children:
            print(f"--- {name} ---\n{log.read_text(encoding='utf8', errors='replace')[-2000:]}", file=sys.stderr)
        return 2
    finally:
        for _, process, _ in reversed(children):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
