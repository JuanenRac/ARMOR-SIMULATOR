"""The battery-writing loop: the real server, a broker and a simulated gateway node with a fake Pylontech console.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

The server orders a write to a Pylontech battery in two steps (arm, then execute with the serial number typed again) over the broker, and the node answers each step. Here the node
is `SimBatteryNode`: it listens on `armor/solar/<node>/maintenance/command`, keeps the state of a FAKE console (outputs, clock, serial number; nothing is written to any battery)
and answers on `.../result` with the messages the shared contract describes. Its own switch for writing is OFF until the bench turns it on, like the real node's. The checks run
through the server's real routes as an administrator who has just proved themselves again. Evidence is `simulator`: it says the two ends agree on the contract and the order of the
steps; it says nothing about a real battery, whose console, timing and password only a bench with one can show.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

SERIAL = "PYLSIM00000001"
BATTERY = {"model": "US3000C", "serial": SERIAL, "soft_version": "V2.8", "board": "PS-SIM"}


class FakeConsole:
    """What a Pylontech console keeps and answers, reduced to what the operations here touch."""

    def __init__(self) -> None:
        self.outputs = {"cfet": "ON", "dfet": "ON", "buzz": "OFF", "heat": "OFF"}
        self.clock = "2026-01-01 00:00:00"
        self.serial = SERIAL
        self.writes: list[str] = []

    def snapshot(self) -> str:
        outputs = "\n".join(f"{name:<5}: {state}" for name, state in self.outputs.items())
        return f"## output\n{outputs}\n## clock\n{self.clock}\n"

    def apply(self, op: str, params: dict[str, Any]) -> None:
        if op == "output_set":
            self.outputs[params["output"]] = params["state"].upper()
            self.writes.append(f"output {params['output']} {params['state']}")
        elif op == "set_clock":
            self.clock = "2026-11-07 12:00:00"
            self.writes.append("time set")
        else:
            raise ValueError(op)


class SimBatteryNode:
    """The node's side of the writing: answers arm, execute and cancel for one fake console. `allow_write` is the node's own switch, OFF by default."""

    SUPPORTED = ("output_set", "set_clock")

    def __init__(self, node_id: str, publish: Callable[[str, dict], None], console: FakeConsole | None = None) -> None:
        self.node_id, self.publish, self.console = node_id, publish, console or FakeConsole()
        self.allow_write = False
        self._armed: dict[str, dict] = {}     # token -> the order it was given for
        self.seen: list[tuple[str, str]] = []   # (action, op) of every order, for the checks

    def _answer(self, command: dict, stage: str, refusal: str = "none", **fields: Any) -> None:
        body = {"kind": "solar_battery_result", "node_id": self.node_id, "timestamp_ms": int(time.time() * 1000), "command_id": command["command_id"], "port": command["port"],
                "action": command["action"], "stage": stage, "accepted": refusal == "none", "refusal": refusal, **fields}
        self.publish(f"armor/solar/{self.node_id}/maintenance/result", body)

    def handle(self, command: dict) -> None:
        action = command.get("action")
        self.seen.append((str(action), str(command.get("op", ""))))
        if action == "arm":
            self._arm(command)
        elif action == "execute":
            self._execute(command)
        elif action == "cancel":
            self._answer(command, "rejected", "not_cancellable")
        else:
            self._answer(command, "rejected", "unknown_op")

    def _arm(self, command: dict) -> None:
        op, params = command.get("op"), command.get("params", {})
        if not self.allow_write:
            return self._answer(command, "rejected", "disabled")
        if op not in self.SUPPORTED:
            return self._answer(command, "rejected", "unknown_op")
        if command.get("serial") != self.console.serial:
            return self._answer(command, "rejected", "serial_mismatch")
        token = secrets.token_hex(16)
        self._armed[token] = {"op": op, "params": params, "serial": command["serial"]}
        canonical = f"{op} " + " ".join(f"{key}={value}" for key, value in sorted(params.items()))
        self._answer(command, "armed", token=token, canonical=canonical.strip(), summary=f"Simulated console: {canonical.strip()}", risk="medium", atomic=False,
                     battery=BATTERY, snapshot_before=self.console.snapshot())

    def _execute(self, command: dict) -> None:
        order = self._armed.pop(str(command.get("token")), None)     # one arm, one execute
        if order is None or order["op"] != command.get("op") or order["params"] != command.get("params", {}) or order["serial"] != command.get("serial"):
            return self._answer(command, "rejected", "bad_token")
        before = self.console.snapshot()
        self._answer(command, "started")
        self._answer(command, "progress", outcome="running", steps_done=1, steps_total=2)
        self.console.apply(order["op"], order["params"])
        self._answer(command, "progress", outcome="running", steps_done=2, steps_total=2)
        self._answer(command, "final", outcome="ok", steps_done=2, steps_total=2, before=before, after=self.console.snapshot(), transcript="\n".join(self.console.writes))


class Admin:
    """An administrator of the real server, signed in with the password of the bench, who proves themselves again when a route needs it."""

    def __init__(self, base: str, user: str, password: str) -> None:
        self.base, self.user, self.password, self.cookie = base, user, password, ""

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        headers = {"Content-Type": "application/json", **({"Cookie": self.cookie} if self.cookie else {})}
        request = urllib.request.Request(self.base + path, data=json.dumps(body).encode("utf-8") if body is not None else None, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=10) as reply:  # noqa: S310 - a loopback address chosen by the bench
                self._keep(reply.headers.get_all("Set-Cookie") or [])
                raw = reply.read()
                return reply.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                return error.code, json.loads(raw) if raw else {}
            except ValueError:
                return error.code, {}

    def _keep(self, cookies: list[str]) -> None:
        if cookies:
            self.cookie = "; ".join(item.split(";", 1)[0] for item in cookies)

    def sign_in(self) -> int:
        return self.call("POST", "/api/v1/studio/session", {"username": self.user, "password": self.password})[0]

    def elevate(self) -> int:
        return self.call("POST", "/api/v1/studio/elevate", {"password": self.password})[0]


def wait_for(check: Callable[[], Any], seconds: float = 15.0) -> Any:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.2)
    return None


def run_checks(add: Callable[..., None], base: str, operator_get: Callable[[str], tuple[int, bytes]], broker_port: int, admin_user: str, admin_password: str,
               node_id: str = "shim-solar") -> None:
    """Runs the loop against a server that was started with ARMOR_BATTERY_WRITE=1 and a battery of `node_id` that reports. `add(name, ok, detail)` records each check."""
    import paho.mqtt.client as mqtt

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="armor-sim-battery-node")
    ready = threading.Event()

    def publish(topic: str, body: dict) -> None:
        client.publish(topic, json.dumps(body), qos=1)

    node = SimBatteryNode(node_id, publish)

    def on_connect(c: Any, _u: Any, _f: Any, _r: Any, _p: Any = None) -> None:
        c.subscribe(f"armor/solar/{node_id}/maintenance/command", qos=1)
        ready.set()

    def on_message(_c: Any, _u: Any, message: Any) -> None:
        try:
            node.handle(json.loads(message.payload))
        except (ValueError, KeyError):
            pass

    client.on_connect, client.on_message = on_connect, on_message
    client.connect("127.0.0.1", broker_port, keepalive=30)
    client.loop_start()
    try:
        add("battery loop: the simulated node is on the broker", ready.wait(10))
        from . import solar
        publish(f"armor/solar/{node_id}/us3000-1/state", solar.battery(node_id, 1, 1))
        seen = wait_for(lambda: any(item.get("node_id") == node_id and item.get("kind") == "battery" for item in json.loads(operator_get("/api/v1/solar")[1]).get("devices", [])))
        add("battery loop: the server lists the battery the node reports", bool(seen))
        status, body = operator_get("/api/v1/solar/battery-ops/catalog")
        add("battery loop: the server says writing is on (ARMOR_BATTERY_WRITE=1) and gives the table", status == 200 and json.loads(body).get("enabled") is True)
        admin = Admin(base, admin_user, admin_password)
        add("battery loop: the administrator signs in", admin.sign_in() == 201)
        order = {"node": node_id, "port": 1, "op": "output_set", "params": {"output": "cfet", "state": "off"}, "serial": SERIAL}
        status, said = admin.call("POST", "/api/v1/solar/battery-ops", order)
        add("battery loop: an order without a fresh proof is refused", status == 403 and said.get("code") == "elevation_required", f"{status} {said}")
        add("battery loop: the administrator proves themselves again", admin.elevate() == 200)

        def operation(op_id: str) -> dict:
            return admin.call("GET", f"/api/v1/solar/battery-ops/{op_id}")[1]

        def stage_is(op_id: str, *stages: str) -> dict:
            return wait_for(lambda: (lambda item: item if item.get("stage") in stages else None)(operation(op_id))) or operation(op_id)

        # the node's own switch is off: the conservative default
        status, first = admin.call("POST", "/api/v1/solar/battery-ops", order)
        gate = stage_is(first.get("id", "x"), "rejected")
        add("battery loop: with the node's own switch off the order is refused by the node (disabled) and nothing is written", status == 202 and gate.get("stage") == "rejected" and gate.get("refusal") == "disabled" and not node.console.writes, f"{status} {gate.get('stage')} {gate.get('refusal')}")

        node.allow_write = True
        status, wrong = admin.call("POST", "/api/v1/solar/battery-ops", {**order, "serial": "PYLWRONG0000001"})
        refused = stage_is(wrong.get("id", "x"), "rejected")
        add("battery loop: a serial number that is not the battery's is refused by the node (serial_mismatch)", refused.get("refusal") == "serial_mismatch" and not node.console.writes, f"{refused.get('stage')} {refused.get('refusal')}")

        status, armed = admin.call("POST", "/api/v1/solar/battery-ops", order)
        armed = stage_is(armed.get("id", "x"), "armed")
        add("battery loop: the node accepts the arm and says what it will do", armed.get("stage") == "armed" and "cfet" in str(armed.get("canonical")) and not node.console.writes, f"{armed.get('stage')}")
        status, said = admin.call("POST", f"/api/v1/solar/battery-ops/{armed.get('id')}/execute", {"serial": "PYLWRONG0000001"})
        add("battery loop: executing with another serial number is refused by the server and still writes nothing", status == 400 and said.get("code") == "serial_mismatch" and not node.console.writes, f"{status} {said}")
        status, said = admin.call("POST", f"/api/v1/solar/battery-ops/{armed.get('id')}/execute", {"serial": SERIAL})
        done = stage_is(armed.get("id", "x"), "done", "rejected", "lost")
        add("battery loop: executing with the serial number typed again ends ok, the fake console changed and the difference is kept", status == 202 and done.get("stage") == "done" and done.get("outcome") == "ok"
            and node.console.outputs["cfet"] == "OFF" and bool(done.get("diff")), f"{status} {done.get('stage')} {done.get('outcome')} {done.get('code')}")
        restore = done.get("restore") or {}
        add("battery loop: the server offers the operation that puts the output back", restore.get("op") == "output_set" and restore.get("params", {}).get("state") == "on", str(restore))
        status, again = admin.call("POST", f"/api/v1/solar/battery-ops/{armed.get('id')}/restore", {"serial": SERIAL})
        again = stage_is(again.get("id", "x"), "armed")
        status, said = admin.call("POST", f"/api/v1/solar/battery-ops/{again.get('id')}/execute", {"serial": SERIAL})
        back = stage_is(again.get("id", "x"), "done", "rejected", "lost")
        add("battery loop: the restore is armed and executed and the output is back on", back.get("outcome") == "ok" and node.console.outputs["cfet"] == "ON", f"{back.get('stage')} {back.get('outcome')}")
        token_before = len(node._armed)
        status, third = admin.call("POST", "/api/v1/solar/battery-ops", order)
        third = stage_is(third.get("id", "x"), "armed")
        status, cancelled = admin.call("POST", f"/api/v1/solar/battery-ops/{third.get('id')}/cancel", {})
        add("battery loop: an armed order that is withdrawn is never executed", status in (200, 202) and cancelled.get("stage") == "withdrawn" and node.console.outputs["cfet"] == "ON" and len(node._armed) == token_before + 1,
            f"{status} {cancelled.get('stage')}")
    finally:
        client.loop_stop()
        client.disconnect()
