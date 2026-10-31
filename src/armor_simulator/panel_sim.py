"""A simulated ARMOR-NODE-ALARM panel, and the check that a REAL ARMOR-SERVER asks it for the right arming profile when a mode is chosen.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

With the server setting `alarm.mode_panel_sync` on, choosing away, home or night on the server also sends every alarm panel an arm command that carries the profile of the mode
(away -> `away`, home -> `stay`, night -> `night`) and reports what the panels answered in `panel_sync`. A real panel is not needed to test that: this module is a panel that speaks the
contract (state on `armor/alarm/<node>/state`, command on `.../command`, answer on `.../result`) and answers the way it is told to:

* `accept`: the command is taken and the panel arms with the profile;
* `refuse`: the command is answered with a refusal (`zones_open` by default);
* `silent`: the command is received and never answered.

`verify_panel_sync` plays that against the server through Studio's own routes: for each behaviour and each mode it disarms, chooses the mode, waits for the report and compares it with
what must be true: the server defends the mode whatever the panel does; the panel was asked for the profile of the mode and nothing else (no disarm travels); the report says `confirmed`
only when the panel accepted (`failed` for a refusal or silence, never confirmed); and a failed report is exactly one open alarm `mode_panel_sync_failed` in the alarm centre (none for a confirmed one).

Honest limits: this is a model of the panel's answer, not its firmware; the server needs a broker both share (the panel talks MQTT) and `ARMOR_ALARM_COMMANDS=1`; paho-mqtt is needed only for
the link (`pip install paho-mqtt`), not for the panel model or the check.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

BEHAVIORS = ("accept", "refuse", "silent")
MODE_PROFILE = {"away": "away", "home": "stay", "night": "night"}
MODE_BASE = {"away": "away", "home": "stay", "night": "stay"}
ALARM_CODE = "mode_panel_sync_failed"
REFUSALS = ("not_disarmed", "zones_open", "not_armed", "bad_pin", "locked_out")


class PanelLinkError(RuntimeError):
    """The panel could not be connected to the broker."""


@dataclass
class SimulatedPanel:
    node_id: str = "sim-panel"
    behavior: str = "accept"
    refusal: str = "zones_open"
    arm_profiles: bool = True
    commands_enabled: bool = True
    phase: str = "disarmed"
    mode: str = "disarmed"
    profile: str | None = None
    received: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        if self.behavior not in BEHAVIORS:
            raise ValueError(f"the behaviour is one of {', '.join(BEHAVIORS)}")
        if self.refusal not in REFUSALS:
            raise ValueError(f"the refusal is one of {', '.join(REFUSALS)}")

    def reset(self) -> None:
        """Disarmed again, and the commands received so far forgotten (the panel was armed by hand, or by the last step)."""
        with self._lock:
            self.phase, self.mode, self.profile = "disarmed", "disarmed", None
            self.received.clear()

    def state(self, now_ms: int) -> dict[str, Any]:
        """The message of `armor/alarm/<node>/state`, as ARMOR-COMMON's alarm schema has it."""
        with self._lock:
            message: dict[str, Any] = {
                "kind": "alarm", "node_id": self.node_id, "timestamp_ms": now_ms, "phase": self.phase, "mode": self.mode, "siren": False, "locked_out": False,
                "commands_enabled": self.commands_enabled, "zones": [{"id": "front-door", "kind": "entry", "state": "normal", "bypassed": False}], "open_zones": [], "events": [],
                "arm_profiles": self.arm_profiles,
            }
            if self.profile is not None:
                message["profile"] = self.profile
            return message

    def handle_command(self, payload: dict[str, Any], now_ms: int) -> dict[str, Any] | None:
        """The answer to one command (`armor/alarm/<node>/command`), or None when the panel stays silent or the message is not for it."""
        if payload.get("kind") != "alarm_command" or payload.get("node_id") != self.node_id or not isinstance(payload.get("command_id"), str):
            return None
        with self._lock:
            self.received.append(payload)
            if self.behavior == "silent":
                return None
            action = payload.get("action")
            result: dict[str, Any] = {"kind": "alarm_result", "node_id": self.node_id, "timestamp_ms": now_ms, "command_id": payload["command_id"], "action": action}
            if self.behavior == "refuse" or action not in ("arm", "disarm"):
                result.update(accepted=False, refusal=self.refusal if action == "arm" else "not_armed", phase=self.phase)
                return result
            if action == "disarm":
                self.phase, self.mode, self.profile = "disarmed", "disarmed", None
            else:
                profile = payload.get("profile")
                self.phase, self.mode = "armed", str(payload.get("mode", "away"))
                self.profile = profile.get("id") if isinstance(profile, dict) and isinstance(profile.get("id"), str) else None
            result.update(accepted=True, refusal="none", phase=self.phase)
            return result

    def arms_received(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self.received if item.get("action") == "arm"]

    def others_received(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self.received if item.get("action") != "arm"]


class PanelLink:
    """The panel on an MQTT broker (the one the server uses): it publishes its state every `every_s` seconds and answers each command through [SimulatedPanel.handle_command]."""

    def __init__(self, panel: SimulatedPanel, url: str, *, username: str | None = None, password: str | None = None, every_s: float = 2.0, clock: Callable[[], float] = time.time) -> None:
        self.panel, self.url, self.every_s, self.clock = panel, url, every_s, clock
        self._username, self._password = username, password
        self._client: Any = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, timeout_s: float = 10.0) -> None:
        try:
            import paho.mqtt.client as mqtt
        except ImportError:
            raise PanelLinkError("the link to the broker needs paho-mqtt (pip install paho-mqtt)") from None
        parsed = urlparse(self.url)
        if parsed.scheme not in ("mqtt", "tcp") or not parsed.hostname:
            raise PanelLinkError("the broker address is mqtt://host[:port]")
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"sim-{self.panel.node_id}")
        if self._username:
            client.username_pw_set(self._username, self._password)
        topic = f"armor/alarm/{self.panel.node_id}"
        connected = threading.Event()

        refused: list[str] = []

        def on_connect(c: Any, _u: Any, _f: Any, reason: Any, _p: Any = None) -> None:
            if getattr(reason, "is_failure", False):
                refused.append(str(reason))
                return
            c.subscribe(f"{topic}/command", qos=0)
            connected.set()

        def on_message(c: Any, _u: Any, message: Any) -> None:
            try:
                payload = json.loads(message.payload)
            except ValueError:
                return
            if isinstance(payload, dict):
                answer = self.panel.handle_command(payload, int(self.clock() * 1000))
                if answer is not None:
                    c.publish(f"{topic}/result", json.dumps(answer), qos=0)

        client.on_connect, client.on_message = on_connect, on_message
        try:
            client.connect(parsed.hostname, parsed.port or 1883, keepalive=30)
        except OSError as error:
            raise PanelLinkError(f"the broker could not be reached: {error}") from None
        client.loop_start()
        if not connected.wait(timeout_s):
            client.loop_stop()
            raise PanelLinkError("the broker did not accept the panel" + (f" ({refused[-1]})" if refused else " (no answer)") + ": check the address, the user and the password")
        self._client = client

        def publish_state() -> None:
            while not self._stop.is_set():
                client.publish(f"{topic}/state", json.dumps(self.panel.state(int(self.clock() * 1000))), qos=0)
                self._stop.wait(self.every_s)

        self._thread = threading.Thread(target=publish_state, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(2)
        if self._client is not None:
            self._client.loop_stop()
            self._client.disconnect()


def _pending_wait(session: Any, wait_s: float, clock: Callable[[], float], sleep: Callable[[float], None]) -> dict[str, Any]:
    """The state of the system once the report of the panels is no longer pending (or when the wait is over)."""
    end = clock() + wait_s
    while True:
        state: dict[str, Any] = session.call("GET", "/api/v1/status") or {}
        sync = state.get("panel_sync")
        if not isinstance(sync, dict) or sync.get("status") != "pending" or clock() >= end:
            return state
        sleep(0.25)


def verify_panel_sync(
    session: Any, panel: SimulatedPanel, *, pin: str | None = None, modes: tuple[str, ...] = ("away", "home", "night"), behaviors: tuple[str, ...] = BEHAVIORS, wait_s: float = 9.0,
    clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[str], list[str]]:
    """Plays every mode against every behaviour of the panel and returns (problems, log). Needs: the setting alarm.mode_panel_sync (and alarm.arming_modes) on and ARMOR_ALARM_COMMANDS=1 in the server, an
    account that may arm and disarm, and the panel connected to the broker of the server."""
    problems: list[str] = []
    log: list[str] = []
    first = session.call("GET", "/api/v1/alarm/modes") or {}
    if not first.get("enabled"):
        return ["the arming modes are off in the server (alarm.arming_modes): turn them on in Studio, Configuration > Security"], log
    if not first.get("panel_sync_enabled"):
        return ["the panel sync is off in the server (alarm.mode_panel_sync): turn it on in Studio, Configuration > Security"], log
    original = panel.behavior
    try:
        for behavior in behaviors:
            panel.behavior = behavior
            for mode in modes:
                where = f"{behavior}/{mode}"
                panel.reset()
                disarm: dict[str, Any] = {"mode": "disarmed"}
                if pin:
                    disarm["pin"] = pin
                try:
                    session.call("POST", "/api/v1/mode", disarm)
                    panel.reset()
                    session.call("POST", "/api/v1/mode", {"mode": mode, "confirm_unassigned": True})
                except Exception as error:   # noqa: BLE001 - any refusal ends this step with its words
                    problems.append(f"{where}: the server refused an order ({error})")
                    continue
                state = _pending_wait(session, wait_s, clock, sleep)
                raw_sync = state.get("panel_sync")
                sync: dict[str, Any] = raw_sync if isinstance(raw_sync, dict) else {}
                want = "confirmed" if behavior == "accept" else "failed"
                if state.get("arming_mode") != mode or state.get("mode") != "armed":
                    problems.append(f"{where}: the server does not defend the mode (it says {state.get('mode')}/{state.get('arming_mode')}): a panel must never hold the server back")
                if sync.get("status") != want:
                    problems.append(f"{where}: the report says {sync.get('status')!r}, it must be {want!r}")
                if behavior != "accept" and sync.get("status") == "confirmed":
                    problems.append(f"{where}: a panel that did not accept is shown as confirmed")
                if sync.get("profile") != MODE_PROFILE[mode]:
                    problems.append(f"{where}: the report names the profile {sync.get('profile')!r}, the mode asks for {MODE_PROFILE[mode]!r}")
                arms = panel.arms_received()
                if len(arms) != 1:
                    problems.append(f"{where}: the panel received {len(arms)} arm command(s), it must be exactly one")
                else:
                    command = arms[0]
                    raw_profile = command.get("profile")
                    profile: dict[str, Any] = raw_profile if isinstance(raw_profile, dict) else {}
                    if profile.get("id") != MODE_PROFILE[mode] or command.get("mode") != MODE_BASE[mode] or profile.get("base") != MODE_BASE[mode]:
                        problems.append(f"{where}: the panel was asked for mode {command.get('mode')!r} with the profile {profile.get('id')!r}/{profile.get('base')!r}, not {MODE_BASE[mode]!r}/{MODE_PROFILE[mode]!r}")
                    if "pin" in json.dumps(command):
                        problems.append(f"{where}: a PIN travels to the panel")
                if panel.others_received():
                    problems.append(f"{where}: the panel received a command that is not an arm")
                # a report that says failed is one alarm in the alarm centre, and a confirmed one leaves none open
                listed: dict[str, Any] = session.call("GET", "/api/v1/alarms") or {}
                active = listed.get("active")
                open_alarms = [alarm for alarm in (active if isinstance(active, list) else []) if isinstance(alarm, dict) and alarm.get("code") == ALARM_CODE and not alarm.get("cleared_at")]
                if len(open_alarms) != (0 if behavior == "accept" else 1):
                    problems.append(f"{where}: {len(open_alarms)} open alarm(s) {ALARM_CODE!r}, it must be {0 if behavior == 'accept' else 1}")
                elif open_alarms and (open_alarms[0].get("severity") != "high" or open_alarms[0].get("silent")):
                    problems.append(f"{where}: the alarm {ALARM_CODE!r} must be high and not silent")
                log.append(f"{where}: the report says {sync.get('status')}, the panel received {len(arms)} arm(s)")
        # a restored state: the server disarmed, the panel as it was
        disarm_last: dict[str, Any] = {"mode": "disarmed"}
        if pin:
            disarm_last["pin"] = pin
        try:
            session.call("POST", "/api/v1/mode", disarm_last)
        except Exception:   # noqa: BLE001, S110 - best effort: the system is left as the last step left it
            pass
    finally:
        panel.behavior = original
    return problems, log
