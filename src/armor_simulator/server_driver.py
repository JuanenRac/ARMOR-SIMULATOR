"""Plays an alarm scenario against a REAL ARMOR-SERVER and checks what the server raised, including the arming modes (away, home, night).

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

The scenario files describe the mode of the system as events and a calendar. Until now those were labels: the simulator could not tell whether a server defended what the mode
says. Here the mode events become calls to `POST /api/v1/mode` of the server, the telemetry goes to the ingest routes at the pace of the scenario (one second of scenario per
second of the clock, because the delays of the server are real), and at the end the alarms the server really raised (`GET /api/v1/alarms`) are compared with the expectation of
the scenario by the same `verify_alarms` as for a file.

What the server must have: the setting `alarm.arming_modes` on (an administrator turns it on in Studio, Configuration > Security; this module never changes a security setting), an
account that may arm (an operator) and, to define the modes from the scenario (`--apply-modes`), an administrator. Home and night defend nothing until they are defined: a scenario
may carry the definitions in its `server_modes` key, else they are derived from the `armed_in` of its zones (a radar node is defended in a mode when any zone of that node is armed in
it, because the server defends a radar node as a whole).

The alarm that the server raises for a radar track names the node and never the zone (the server defends a radar node as a whole), so an expectation that names a `zone` is checked at the
level of the node that sees that zone (`zone_expectations_at_node`); when that would make two zones of the same node indistinguishable (one is expected and the other forbidden in
overlapping seconds) the run is refused instead of giving an answer it cannot stand behind.

Honest limits: a radar node is defended as a whole, so a scenario run here cannot tell zones of the same node apart; the clock of the server and of this machine are compared with the `Date`
header of one answer, so they are as close as one second; a second factor (TOTP) at sign-in is not supported.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from datetime import datetime
from email.utils import parsedate_to_datetime
from http.cookiejar import CookieJar
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener

from .alarm_scenarios import Scenario, build_stream, mode_at, verify_alarms
from .publisher import DeliveryError, post

SERVER_MODES = ("away", "home", "night")


class DriverError(RuntimeError):
    """The run could not be carried out (the server is not ready, refused, or could not be reached)."""


class Refusal(Exception):
    """The server answered with a refusal: its HTTP status and the short code it gives."""

    def __init__(self, status: int, code: str, text: str = "") -> None:
        super().__init__(f"HTTP {status} {code}")
        self.status, self.code, self.text = status, code, text


@dataclass
class DriveResult:
    observed: list[dict[str, Any]]
    problems: list[str]
    log: list[str] = field(default_factory=list)


class Session:
    """A signed-in session of Studio with the server (the cookie it gives), for the routes of the modes and of the alarms."""

    def __init__(self, origin: str, timeout: float = 10.0, track_clock: bool = True) -> None:
        self.origin = origin.rstrip("/")
        self.timeout = timeout
        self.track_clock = track_clock
        self._opener = build_opener(HTTPCookieProcessor(CookieJar()))
        self.server_offset_ms = 0

    def call(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        data = json.dumps(body).encode() if body is not None else None
        request = Request(self.origin + path, data=data, method=method, headers={"Accept": "application/json", **({"Content-Type": "application/json"} if data else {})})
        try:
            with self._opener.open(request, timeout=self.timeout) as response:  # noqa: S310 - the scheme is checked by check_server_url
                self._note_clock(response.headers.get("Date"))
                raw = response.read()
        except HTTPError as error:
            raw = error.read()
            error.close()
            try:
                parsed = json.loads(raw) if raw else {}
            except ValueError:
                parsed = {}
            code = parsed.get("code", "") if isinstance(parsed, dict) else ""
            raise Refusal(error.code, str(code), str(parsed.get("error", "")) if isinstance(parsed, dict) else "") from None
        except (URLError, OSError) as error:
            raise DriverError(f"the server could not be reached: {error}") from None
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            raise DriverError(f"the server answered {path} with something that is not JSON") from None

    def _note_clock(self, header: str | None) -> None:
        if not header or not self.track_clock:
            return
        try:
            self.server_offset_ms = int(parsedate_to_datetime(header).timestamp() * 1000 - time.time() * 1000)
        except (TypeError, ValueError):
            pass

    def login(self, username: str, password: str) -> None:
        try:
            answer = self.call("POST", "/api/v1/studio/session", {"username": username, "password": password})
        except Refusal as refusal:
            raise DriverError(f"the server refused the sign-in (HTTP {refusal.status} {refusal.code}); check the user and the password" + (": the second factor is required here and this tool cannot give it" if refusal.code == "totp_setup_required" else "")) from None
        if isinstance(answer, dict) and answer.get("totp_required"):
            raise DriverError("this account has a second factor; use an account without it for the simulator (it cannot give a code)")


def modes_document(scenario: Scenario) -> dict[str, Any]:
    """The definitions of the modes to put in the server: `server_modes` of the scenario, else the radar nodes that have a zone armed in each mode."""
    explicit = getattr(scenario, "server_modes", None)
    modes: dict[str, dict[str, Any]] = {"away": {}, "home": {}, "night": {}}
    if explicit:
        for mode, definition in explicit.items():
            modes[mode] = {key: (list(value) if isinstance(value, (list, tuple)) else value) for key, value in definition.items()}
        return {"modes": modes, "schedule": []}
    for mode in ("home", "night"):
        nodes = sorted({zone.node for zone in scenario.zones.values() if mode in zone.armed_in})
        if nodes:
            modes[mode] = {"defends": [f"node:{node}" for node in nodes]}
    return {"modes": modes, "schedule": []}


def _overlap(low_a: float, high_a: float, low_b: float, high_b: float) -> bool:
    return low_a <= high_b and low_b <= high_a


def zone_expectations_at_node(scenario: Scenario) -> tuple[Scenario, list[str]]:
    """The scenario with every expectation that names a `zone` rewritten to name the node of that zone, and a note for each rewritten one.

    The server raises the alarm of a radar track for the node, so a `zone` can never match what it says. Rewriting is only honest while the zones involved can be told apart by their node: an
    expected alarm in one zone and a forbidden alarm of the same code in another zone of the same node in overlapping seconds cannot (the server would raise the same alarm for both), and that
    raises DriverError so that the person splits the zones over nodes or drops the zone from the expectation.
    """
    expected = [(entry, entry.get("zone")) for entry in scenario.expect_alarms]
    forbidden = [(entry, entry.get("zone")) for entry in scenario.expect_forbidden]
    for want, want_zone in expected:
        if want_zone is None:
            continue
        for ban, ban_zone in forbidden:
            if ban_zone is None or ban_zone == want_zone or ban["code"] != want["code"]:
                continue
            if scenario.zones[ban_zone].node == scenario.zones[want_zone].node and _overlap(*want["window"], ban["from_s"], ban["to_s"]):
                raise DriverError(
                    f"the zones {want_zone!r} (expected {want['code']}) and {ban_zone!r} (forbidden) are seen by the same node, {scenario.zones[want_zone].node!r}, and the server raises its alarm for the node: "
                    "it cannot tell the two zones apart, so this scenario cannot be checked against it; put the zones on different nodes or leave the zone out of the expectation")
    notes: list[str] = []

    def at_node(entry: dict[str, Any]) -> dict[str, Any]:
        zone = entry.get("zone")
        if zone is None:
            return entry
        node = scenario.zones[zone].node
        if "node" in entry and entry["node"] != node:
            raise DriverError(f"the expectation names the zone {zone!r}, which is seen by {node!r}, and the node {entry['node']!r}: they cannot both hold")
        notes.append(f"{entry['code']} in the zone {zone} is checked as {entry['code']} of the node {node}")
        return {key: value for key, value in entry.items() if key != "zone"} | {"node": node}

    return replace(scenario, expect_alarms=tuple(at_node(e) for e in scenario.expect_alarms), expect_forbidden=tuple(at_node(e) for e in scenario.expect_forbidden)), notes


def mode_changes(scenario: Scenario) -> list[tuple[int, str]]:
    """The seconds at which the mode of the scenario changes (the calendar and the `mode` events), the first being second 0 when the scenario does not start disarmed."""
    changes: list[tuple[int, str]] = []
    current = "disarmed"
    for second in range(scenario.duration_s):
        wanted = mode_at(scenario, second)
        if wanted != current:
            changes.append((second, wanted))
            current = wanted
    return changes


def _seconds(stream: Iterator[tuple[str, dict[str, Any]]]) -> Iterator[tuple[int, list[tuple[str, dict[str, Any]]]]]:
    """The messages of the scenario grouped by the second they belong to."""
    current = -1
    batch: list[tuple[str, dict[str, Any]]] = []
    for topic, payload in stream:
        second = int(payload.get("timestamp_ms", 0)) // 1000
        if second != current:
            if batch:
                yield current, batch
            current, batch = second, []
        batch.append((topic, payload))
    if batch:
        yield current, batch


def _observed(alarms: dict[str, Any], t0_server_ms: float) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for item in [*alarms.get("active", []), *alarms.get("recent", [])]:
        if not isinstance(item, dict) or not isinstance(item.get("raised_at"), str):
            continue
        try:
            raised_ms = datetime.fromisoformat(item["raised_at"].replace("Z", "+00:00")).timestamp() * 1000
        except ValueError:
            continue
        source: dict[str, Any] = item["source"] if isinstance(item.get("source"), dict) else {}
        entry: dict[str, Any] = {"t_s": round((raised_ms - t0_server_ms) / 1000, 3), "code": str(item.get("code", ""))}
        if source.get("type") == "node" and source.get("id"):
            entry["node"] = str(source["id"])
        if item.get("severity"):
            entry["severity"] = str(item["severity"])
        seen[str(item.get("id", len(seen)))] = entry
    return sorted((entry for entry in seen.values() if entry["t_s"] >= -1), key=lambda entry: entry["t_s"])


def drive(
    scenario: Scenario, session: Session, *, ingest_url: str, ingest_token: str, per_node: bool = False, apply_modes: bool = False, pin: str | None = None, health_every: int = 5,
    settle_s: float = 3.0, clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep, send: Callable[..., int] = post,
) -> DriveResult:
    """Plays the scenario against the server and compares what it raised with the expectation. Raises DriverError when the server is not ready or refuses an order."""
    log: list[str] = []
    checked, zone_notes = zone_expectations_at_node(scenario)
    changes = mode_changes(scenario)
    wants_modes = any(mode in ("home", "night") for _, mode in changes)
    state: dict[str, Any] = session.call("GET", "/api/v1/alarm/modes") or {}
    if wants_modes and not state.get("enabled"):
        raise DriverError("the scenario uses the home or night mode and the arming modes are off in the server: an administrator turns them on in Studio (Configuration > Security) and the run is repeated")
    if apply_modes:
        document = modes_document(scenario)
        try:
            session.call("PUT", "/api/v1/alarm/modes", {"revision": state.get("revision"), **document})
        except Refusal as refusal:
            raise DriverError(f"the definitions of the modes were refused (HTTP {refusal.status} {refusal.code}): an administrator account is needed, and the nodes must be named as node:<id>") from None
        log.append("modes defined in the server: " + json.dumps({mode: definition.get("defends", []) for mode, definition in document["modes"].items() if mode != "away"}, sort_keys=True))
    elif wants_modes:
        wanted_modes: dict[str, Any] = modes_document(scenario)["modes"]
        mine = {mode: sorted(wanted_modes[mode].get("defends", [])) for mode in ("home", "night")}
        theirs = {mode: sorted(state.get("modes", {}).get(mode, {}).get("defends", [])) for mode in ("home", "night")}
        if mine != theirs:
            raise DriverError(f"the modes defined in the server ({theirs}) are not what the scenario needs ({mine}); add --apply-modes to define them (an administrator account)")

    start_ms = int(clock() * 1000)
    t0 = clock()
    pending = list(changes)
    for second, batch in _seconds(build_stream(scenario, health_every)):
        wait = t0 + second - clock()
        if wait > 0:
            sleep(wait)
        while pending and pending[0][0] <= second:
            at, wanted = pending.pop(0)
            body: dict[str, Any] = {"mode": wanted}
            if pin:
                body["pin"] = pin
            try:
                session.call("POST", "/api/v1/mode", body)
            except Refusal as refusal:
                hint = " (this change defends less than the mode before it: give the PIN of the account with --studio-pin-file or ARMOR_STUDIO_PIN)" if refusal.code in ("wrong_pin", "pin_not_set") else ""
                raise DriverError(f"the server refused the mode {wanted} at second {at}: HTTP {refusal.status} {refusal.code}{hint}") from None
            log.append(f"second {at}: mode {wanted}")
        for topic, payload in batch:
            kind = topic.rsplit("/", 1)[1]
            kind = "solar" if topic.startswith("armor/solar/") else "electrical" if topic.startswith("armor/electrical/") else kind
            try:
                send(ingest_url, ingest_token, kind, {**payload, "timestamp_ms": int(payload["timestamp_ms"]) + start_ms}, per_node=per_node)
            except DeliveryError as error:
                raise DriverError(str(error)) from None
    end = t0 + scenario.duration_s + settle_s
    if end - clock() > 0:
        sleep(end - clock())
    alarms = session.call("GET", "/api/v1/alarms")
    observed = _observed(alarms, t0 * 1000 + session.server_offset_ms)
    if zone_notes:
        log.append("the server names the node, not the zone, of a radar alarm: " + "; ".join(zone_notes))
    return DriveResult(observed, verify_alarms(checked, observed), log)
