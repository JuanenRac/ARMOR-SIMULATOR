"""Alarm scenarios described in files: what happens in a house and what the system is expected to answer.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

A scenario is a JSON file (schema `armor-alarm-scenario/1`, documented in docs/ALARM_SCENARIOS.md) with a timeline of events (people crossing zones, a pet, wind,
a sensor that lies, a node that falls silent, a mains outage, the mode of the system) and, optionally, what the system is expected to raise in answer: which alarms,
in which order and in which window of time. The file is validated strictly and refused whole at the first thing that is not understood (unknown key, wrong type,
a time outside the scenario, a zone that does not exist, an expectation that cannot hold in the mode the system is in): a scenario that is half understood would
test something other than what its author meant.

`build_stream` turns the timeline into the messages the radar nodes (and, with power events, the solar and electrical equipment) would publish, deterministic for a
seed; `verify_alarms` compares the alarms a server really raised with the expectation. The geometry is the illustrative one of scenarios.py; nothing here says how a
real radar will see a person, a pet or the wind.
"""

from __future__ import annotations

import json
import math
import random
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .electrical import electrical_messages
from .faults import Message
from .scenarios import SENSOR_BORESIGHT, _sensor_for, lux_for
from .solar import solar_messages

SCHEMA = "armor-alarm-scenario/1"
MAX_FILE_BYTES = 1_000_000
MAX_DURATION_S = 10_000
MAX_EVENTS = 2_000
MAX_ZONES = 64
MAX_NODES = 8
MAX_PEOPLE = 5
MAX_PATH = 16
MODES = ("disarmed", "home", "away", "night")
FAULT_KINDS = ("stuck", "noise", "drift", "dead")
SEVERITIES = ("info", "warning", "high", "critical")
EVENT_TYPES = ("mode", "intrusion", "pet", "wind", "sensor_fault", "node_comm_loss", "mains_outage")
# The alarm codes a scenario may expect (all are codes of ARMOR-COMMON's alarm table; a test checks it when that checkout is next to this one).
ALARM_CODES = (
    "intrusion", "node_down", "camera_down", "camera_motion", "motion", "door_open", "window_open", "glass_break", "vibration", "tamper", "triggered", "device_offline", "low_battery",
    "panic", "smoke", "co", "gas", "water_leak", "alarm_sounding", "alarm_tamper", "alarm_zone_trouble", "alarm_offline", "solar_offline", "solar_battery_low", "electrical_grid_lost",
    "electrical_voltage", "electrical_offline", "duress_disarm",
)
# Codes that only matter while the system is armed (as in the server): expecting one while it is disarmed is a contradiction.
ARMED_ONLY_CODES = frozenset({"intrusion", "motion", "door_open", "window_open", "glass_break", "vibration", "node_down", "camera_down", "camera_motion"})
ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
CLOCK = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class ScenarioError(ValueError):
    """A scenario or an observed-alarms file that is not valid."""


@dataclass(frozen=True)
class Zone:
    id: str
    node: str
    sensor: int
    x_mm: float
    y_mm: float
    armed_in: tuple[str, ...]


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    nodes: tuple[str, ...]
    duration_s: int
    seed: int
    light: str
    power: bool
    start_minute: int
    schedule: tuple[tuple[int, int, str], ...]
    zones: dict[str, Zone]
    events: tuple[dict[str, Any], ...]
    expect_alarms: tuple[dict[str, Any], ...] = ()
    expect_order: str = "any"
    expect_forbidden: tuple[dict[str, Any], ...] = ()
    allow_extra: bool = True


# ---------------------------------------------------------------- strict reading of a JSON document

def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ScenarioError(f"the key {key!r} appears twice in the same object")
        result[key] = value
    return result


def _no_constants(name: str) -> Any:
    raise ScenarioError(f"{name} is not a number JSON allows")


def read_json(path: Path | str) -> Any:
    """Reads a JSON file with the limits of this module: a bounded size, UTF-8, no repeated keys and no NaN or Infinity."""
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError as error:
        raise ScenarioError(f"cannot read {path}: {error.strerror or error}") from None
    if size > MAX_FILE_BYTES:
        raise ScenarioError(f"{path.name} is larger than {MAX_FILE_BYTES} bytes")
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_no_constants)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ScenarioError(f"{path.name} is not valid JSON in UTF-8: {error}") from None


def _object(value: Any, where: str, required: tuple[str, ...], optional: tuple[str, ...] = ()) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ScenarioError(f"{where} must be an object")
    unknown = sorted(set(value) - set(required) - set(optional))
    if unknown:
        raise ScenarioError(f"{where} has keys that are not part of the schema: {', '.join(unknown)}")
    missing = [key for key in required if key not in value]
    if missing:
        raise ScenarioError(f"{where} lacks: {', '.join(missing)}")
    return value


def _int(value: Any, where: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ScenarioError(f"{where} must be a whole number from {low} to {high}")
    return value


def _number(value: Any, where: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ScenarioError(f"{where} must be a number from {low} to {high}")
    return float(value)


def _text(value: Any, where: str, maximum: int = 200) -> str:
    if not isinstance(value, str) or not 0 < len(value) <= maximum:
        raise ScenarioError(f"{where} must be a text of 1 to {maximum} characters")
    return value


def _id(value: Any, where: str) -> str:
    if not isinstance(value, str) or not ID.match(value):
        raise ScenarioError(f"{where} must be 1-64 characters: lowercase letters, digits, '-' or '_'")
    return value


def _choice(value: Any, where: str, options: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in options:
        raise ScenarioError(f"{where} must be one of: {', '.join(options)}")
    return value


def _clock(value: Any, where: str) -> int:
    match = CLOCK.match(value) if isinstance(value, str) else None
    if not match:
        raise ScenarioError(f"{where} must be a time of day as HH:MM")
    return int(match.group(1)) * 60 + int(match.group(2))


def _window(value: Any, where: str, duration: int) -> tuple[float, float]:
    if not isinstance(value, list) or len(value) != 2:
        raise ScenarioError(f"{where} must be a list [from, to] of seconds")
    low, high = _number(value[0], f"{where}[0]", 0, duration), _number(value[1], f"{where}[1]", 0, duration)
    if low > high:
        raise ScenarioError(f"{where}: the start is after the end")
    return low, high


# ---------------------------------------------------------------- the scenario

def parse_scenario(data: Any) -> Scenario:
    """Validates a scenario already read from JSON and returns it normalised; raises ScenarioError at the first thing that is wrong."""
    top = _object(data, "the scenario", ("schema", "name", "duration_s", "zones", "events"), ("description", "nodes", "seed", "light", "power", "start_clock", "schedule", "expect"))
    if top["schema"] != SCHEMA:
        raise ScenarioError(f"schema must be {SCHEMA!r}")
    name = _text(top["name"], "name", 80)
    duration = _int(top["duration_s"], "duration_s", 1, MAX_DURATION_S)
    nodes_raw = top.get("nodes", ["simulator-1"])
    if not isinstance(nodes_raw, list) or not 1 <= len(nodes_raw) <= MAX_NODES:
        raise ScenarioError(f"nodes must be a list of 1 to {MAX_NODES} node ids")
    nodes = tuple(_id(node, f"nodes[{i}]") for i, node in enumerate(nodes_raw))
    if len(set(nodes)) != len(nodes):
        raise ScenarioError("a node id appears twice in nodes")
    light = _choice(top.get("light", "night"), "light", ("cycle", "night"))
    power = top.get("power", False)
    if not isinstance(power, bool):
        raise ScenarioError("power must be true or false")
    start_minute = _clock(top["start_clock"], "start_clock") if "start_clock" in top else 0

    schedule = []
    schedule_raw = top.get("schedule", [])
    if not isinstance(schedule_raw, list) or len(schedule_raw) > 16:
        raise ScenarioError("schedule must be a list of at most 16 entries")
    for i, item in enumerate(schedule_raw):
        entry = _object(item, f"schedule[{i}]", ("from", "to", "mode"))
        schedule.append((_clock(entry["from"], f"schedule[{i}].from"), _clock(entry["to"], f"schedule[{i}].to"), _choice(entry["mode"], f"schedule[{i}].mode", MODES)))

    zones: dict[str, Zone] = {}
    zones_raw = top["zones"]
    if not isinstance(zones_raw, list) or not 1 <= len(zones_raw) <= MAX_ZONES:
        raise ScenarioError(f"zones must be a list of 1 to {MAX_ZONES} zones")
    for i, item in enumerate(zones_raw):
        where = f"zones[{i}]"
        zone = _object(item, where, ("id",), ("node", "sensor_id", "x_mm", "y_mm", "armed_in"))
        zone_id = _id(zone["id"], f"{where}.id")
        if zone_id in zones:
            raise ScenarioError(f"the zone {zone_id!r} appears twice")
        node = _id(zone["node"], f"{where}.node") if "node" in zone else nodes[0]
        if node not in nodes:
            raise ScenarioError(f"{where}.node {node!r} is not in nodes")
        if ("x_mm" in zone) != ("y_mm" in zone):
            raise ScenarioError(f"{where} needs both x_mm and y_mm, or neither")
        if "x_mm" in zone:
            x_mm, y_mm = _number(zone["x_mm"], f"{where}.x_mm", -6000, 6000), _number(zone["y_mm"], f"{where}.y_mm", -6000, 6000)
            sensor = _sensor_for(x_mm, y_mm)
            if sensor is None:
                raise ScenarioError(f"{where} is outside the field of view of every sensor (6 m, 270 degrees)")
            if "sensor_id" in zone and zone["sensor_id"] != sensor:
                raise ScenarioError(f"{where}.sensor_id is {zone['sensor_id']} but the sensor that sees that point is {sensor}")
        else:
            if "sensor_id" not in zone:
                raise ScenarioError(f"{where} needs x_mm and y_mm, or a sensor_id")
            sensor = _int(zone["sensor_id"], f"{where}.sensor_id", 1, 3)
            angle = math.radians(SENSOR_BORESIGHT[sensor])
            x_mm, y_mm = round(3000 * math.sin(angle)), round(3000 * math.cos(angle))
        armed_raw = zone.get("armed_in", ["away", "night"])
        if not isinstance(armed_raw, list) or not armed_raw:
            raise ScenarioError(f"{where}.armed_in must be a non-empty list of modes")
        armed = tuple(_choice(mode, f"{where}.armed_in", MODES[1:]) for mode in armed_raw)
        zones[zone_id] = Zone(zone_id, node, sensor, float(x_mm), float(y_mm), armed)

    events = _parse_events(top["events"], duration, nodes, zones)
    expect_alarms: tuple[dict[str, Any], ...] = ()
    expect_order, allow_extra = "any", True
    expect_forbidden: tuple[dict[str, Any], ...] = ()
    if "expect" in top:
        expect = _object(top["expect"], "expect", (), ("alarms", "order", "forbidden", "allow_extra"))
        expect_order = _choice(expect.get("order", "any"), "expect.order", ("any", "strict"))
        allow_extra = expect.get("allow_extra", True)
        if not isinstance(allow_extra, bool):
            raise ScenarioError("expect.allow_extra must be true or false")
        expect_alarms = tuple(_parse_expected(item, f"expect.alarms[{i}]", duration, nodes, zones) for i, item in enumerate(_list(expect.get("alarms", []), "expect.alarms", 200)))
        expect_forbidden = tuple(_parse_forbidden(item, f"expect.forbidden[{i}]", duration, zones) for i, item in enumerate(_list(expect.get("forbidden", []), "expect.forbidden", 200)))
    scenario = Scenario(
        name=name, description=_text(top["description"], "description", 400) if "description" in top else "", nodes=nodes, duration_s=duration,
        seed=_int(top.get("seed", 0), "seed", 0, 2**31 - 1), light=light, power=power or any(e["type"] == "mains_outage" for e in events), start_minute=start_minute,
        schedule=tuple(schedule), zones=zones, events=tuple(events), expect_alarms=expect_alarms, expect_order=expect_order, expect_forbidden=expect_forbidden, allow_extra=allow_extra,
    )
    for item in scenario.expect_alarms:
        _check_possible(scenario, item)
    return scenario


def _list(value: Any, where: str, maximum: int) -> list[Any]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ScenarioError(f"{where} must be a list of at most {maximum} entries")
    return value


def _zone_ref(value: Any, where: str, zones: dict[str, Zone]) -> str:
    zone = _id(value, where)
    if zone not in zones:
        raise ScenarioError(f"{where}: the zone {zone!r} is not declared in zones")
    return zone


def _parse_events(raw: Any, duration: int, nodes: tuple[str, ...], zones: dict[str, Zone]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for i, item in enumerate(_list(raw, "events", MAX_EVENTS)):
        where = f"events[{i}]"
        if not isinstance(item, dict) or "type" not in item:
            raise ScenarioError(f"{where} must be an object with a type")
        kind = _choice(item["type"], f"{where}.type", EVENT_TYPES)
        if kind == "mode":
            event = _object(item, where, ("type", "at_s", "mode"))
            parsed = {"type": kind, "at_s": _int(event["at_s"], f"{where}.at_s", 0, duration), "mode": _choice(event["mode"], f"{where}.mode", MODES)}
        elif kind == "intrusion":
            event = _object(item, where, ("type", "at_s", "path"), ("people",))
            path: list[dict[str, Any]] = []
            for j, step in enumerate(_list(event["path"], f"{where}.path", MAX_PATH)):
                entry = _object(step, f"{where}.path[{j}]", ("zone", "dwell_s"))
                path.append({"zone": _zone_ref(entry["zone"], f"{where}.path[{j}].zone", zones), "dwell_s": _int(entry["dwell_s"], f"{where}.path[{j}].dwell_s", 1, MAX_DURATION_S)})
            if not path:
                raise ScenarioError(f"{where}.path must have at least one zone")
            at = _int(event["at_s"], f"{where}.at_s", 0, duration)
            if at + sum(step["dwell_s"] for step in path) > duration:
                raise ScenarioError(f"{where} ends after the scenario does")
            parsed = {"type": kind, "at_s": at, "path": path, "people": _int(event.get("people", 1), f"{where}.people", 1, MAX_PEOPLE)}
        elif kind in ("pet", "wind", "sensor_fault"):
            extra = {"pet": (), "wind": ("intensity",), "sensor_fault": ("magnitude",)}[kind]
            required = ("type", "at_s", "zone", "duration_s") + (("fault",) if kind == "sensor_fault" else ())
            event = _object(item, where, required, extra)
            at, length = _int(event["at_s"], f"{where}.at_s", 0, duration), _int(event["duration_s"], f"{where}.duration_s", 1, duration)
            if at + length > duration:
                raise ScenarioError(f"{where} ends after the scenario does")
            parsed = {"type": kind, "at_s": at, "duration_s": length, "zone": _zone_ref(event["zone"], f"{where}.zone", zones)}
            if kind == "wind":
                parsed["intensity"] = _number(event.get("intensity", 0.3), f"{where}.intensity", 0.01, 1.0)
            if kind == "sensor_fault":
                parsed["fault"] = _choice(event["fault"], f"{where}.fault", FAULT_KINDS)
                parsed["magnitude"] = _number(event.get("magnitude", 0.5 if parsed["fault"] == "noise" else 50.0), f"{where}.magnitude", 0.0, 1.0 if parsed["fault"] == "noise" else 1000.0)
        elif kind == "node_comm_loss":
            event = _object(item, where, ("type", "at_s", "duration_s"), ("node",))
            at, length = _int(event["at_s"], f"{where}.at_s", 0, duration), _int(event["duration_s"], f"{where}.duration_s", 1, duration)
            node = _id(event["node"], f"{where}.node") if "node" in event else nodes[0]
            if node not in nodes:
                raise ScenarioError(f"{where}.node {node!r} is not in nodes")
            if at + length > duration:
                raise ScenarioError(f"{where} ends after the scenario does")
            parsed = {"type": kind, "at_s": at, "duration_s": length, "node": node}
        else:
            event = _object(item, where, ("type", "at_s", "duration_s"))
            at, length = _int(event["at_s"], f"{where}.at_s", 0, duration), _int(event["duration_s"], f"{where}.duration_s", 1, duration)
            if at + length > duration:
                raise ScenarioError(f"{where} ends after the scenario does")
            parsed = {"type": kind, "at_s": at, "duration_s": length}
        events.append(parsed)
    events.sort(key=lambda e: e["at_s"])   # stable: events at the same second keep the order of the file
    return events


def _parse_expected(item: Any, where: str, duration: int, nodes: tuple[str, ...], zones: dict[str, Zone]) -> dict[str, Any]:
    entry = _object(item, where, ("code", "at_s"), ("zone", "node", "severity"))
    parsed: dict[str, Any] = {"code": _choice(entry["code"], f"{where}.code", ALARM_CODES), "window": _window(entry["at_s"], f"{where}.at_s", duration)}
    if "zone" in entry:
        parsed["zone"] = _zone_ref(entry["zone"], f"{where}.zone", zones)
    if "node" in entry:
        parsed["node"] = _choice(entry["node"], f"{where}.node", nodes)
    if "severity" in entry:
        parsed["severity"] = _choice(entry["severity"], f"{where}.severity", SEVERITIES)
    return parsed


def _parse_forbidden(item: Any, where: str, duration: int, zones: dict[str, Zone]) -> dict[str, Any]:
    entry = _object(item, where, ("code",), ("zone", "from_s", "to_s"))
    parsed: dict[str, Any] = {"code": _choice(entry["code"], f"{where}.code", ALARM_CODES), "from_s": _number(entry.get("from_s", 0), f"{where}.from_s", 0, duration),
                              "to_s": _number(entry.get("to_s", duration), f"{where}.to_s", 0, duration)}
    if parsed["from_s"] > parsed["to_s"]:
        raise ScenarioError(f"{where}: from_s is after to_s")
    if "zone" in entry:
        parsed["zone"] = _zone_ref(entry["zone"], f"{where}.zone", zones)
    return parsed


def load_scenario(path: Path | str) -> Scenario:
    return parse_scenario(read_json(path))


# ---------------------------------------------------------------- modes and the clock

def mode_at(scenario: Scenario, second: float) -> str:
    """The mode of the system at a second: the schedule of the clock until a `mode` event says otherwise (an event wins from its second on)."""
    mode, manual_at = "disarmed", -1
    minute = (scenario.start_minute + int(second) // 60) % 1440
    for start, end, scheduled in scenario.schedule:
        inside = start <= minute < end if start < end else minute >= start or minute < end
        if inside:
            mode = scheduled
    for event in scenario.events:
        if event["type"] == "mode" and event["at_s"] <= second and event["at_s"] >= manual_at:
            mode, manual_at = event["mode"], event["at_s"]
    return mode


def guarded(scenario: Scenario, zone: str | None, second: float) -> bool:
    """Whether the system defends a zone (or, with None, anything at all) at a second."""
    mode = mode_at(scenario, second)
    if mode == "disarmed":
        return False
    return zone is None or mode in scenario.zones[zone].armed_in


def _check_possible(scenario: Scenario, item: dict[str, Any]) -> None:
    if item["code"] not in ARMED_ONLY_CODES:
        return
    low, high = item["window"]
    if not any(guarded(scenario, item.get("zone"), second) for second in range(int(math.ceil(low)), int(high) + 1)):
        raise ScenarioError(f"an alarm {item['code']!r} is expected between {low:g} s and {high:g} s but the system is not defending that zone then (mode and armed_in)")


# ---------------------------------------------------------------- the message stream

def _active(scenario: Scenario, kind: str, second: int) -> list[dict[str, Any]]:
    return [e for e in scenario.events if e["type"] == kind and e["at_s"] <= second < e["at_s"] + _length(e)]


def _length(event: dict[str, Any]) -> int:
    return sum(step["dwell_s"] for step in event["path"]) if event["type"] == "intrusion" else event["duration_s"]


def _targets(scenario: Scenario, node: str, second: int, rng: random.Random) -> list[dict[str, int]]:
    points: list[tuple[float, float, float]] = []
    faults = {e["zone"]: e for e in _active(scenario, "sensor_fault", second)}
    where_node = lambda zone: scenario.zones[zone].node == node   # noqa: E731

    def add(zone: str, spread: float, speed: tuple[float, float], offset: float = 0.0) -> None:
        fault = faults.get(zone)
        if fault and fault["fault"] == "dead":
            return
        place = scenario.zones[zone]
        x, y = place.x_mm + offset + rng.uniform(-spread, spread), place.y_mm + rng.uniform(-spread, spread)
        if fault and fault["fault"] == "drift":
            x += fault["magnitude"] * (second - fault["at_s"])
        points.append((x, y, rng.uniform(*speed)))

    for event in _active(scenario, "intrusion", second):
        elapsed, zone = second - event["at_s"], None
        for step in event["path"]:
            if elapsed < step["dwell_s"]:
                zone = step["zone"]
                break
            elapsed -= step["dwell_s"]
        if zone and where_node(zone):
            for person in range(event["people"]):
                add(zone, 120, (-1200, -300), person * 400.0)
    for event in _active(scenario, "pet", second):
        if where_node(event["zone"]):
            add(event["zone"], 500, (-800, 800))
    for event in _active(scenario, "wind", second):
        if where_node(event["zone"]) and rng.random() < event["intensity"]:
            add(event["zone"], 200, (-150, 150))
    for zone, fault in faults.items():
        if not where_node(zone):
            continue
        if fault["fault"] == "stuck":
            place = scenario.zones[zone]
            points.append((place.x_mm, place.y_mm, 0.0))
        elif fault["fault"] == "noise":
            for _ in range(2):
                if rng.random() < fault["magnitude"]:
                    place = scenario.zones[zone]
                    points.append((place.x_mm + rng.uniform(-900, 900), place.y_mm + rng.uniform(-900, 900), rng.uniform(-500, 500)))
    per_sensor: dict[int, int] = {}
    targets: list[dict[str, int]] = []
    for x, y, speed in points:
        sensor = _sensor_for(x, y)
        if sensor is None or per_sensor.get(sensor, 0) >= 5 or len(targets) >= 15:
            continue
        per_sensor[sensor] = per_sensor.get(sensor, 0) + 1
        targets.append({"sensor_id": sensor, "track_id": len(targets) + 1, "x_mm": round(x), "y_mm": round(y), "speed_mm_s": round(speed)})
    return targets


def build_stream(scenario: Scenario, health_every: int = 5) -> Iterator[Message]:
    """The messages of the scenario, a second at a time: telemetry per node (and a health beat every `health_every` seconds), then the power equipment when the scenario has it.
    A node that lost its link says nothing at all while it lasts."""
    for second in range(scenario.duration_s):
        silent = {e["node"] for e in _active(scenario, "node_comm_loss", second)}
        for node in scenario.nodes:
            if node in silent:
                continue
            rng = random.Random(f"{scenario.seed}:{node}:{second}")
            yield f"armor/node/{node}/telemetry", {"node_id": node, "timestamp_ms": second * 1000, "lux": lux_for(second, scenario.light), "targets": _targets(scenario, node, second, rng)}
            if health_every and second % health_every == 0:
                yield f"armor/node/{node}/health", {"node_id": node, "timestamp_ms": second * 1000, "online": True}
        if scenario.power and scenario.nodes[0] not in silent:
            # The power equipment follows the shared simulated day, entering the window of the mains outage while the scenario has one.
            reference = 192 + second % 12 if _active(scenario, "mains_outage", second) else 24 + second % 24
            for topic, payload in (*solar_messages(scenario.nodes[0], reference, scenario.seed), *electrical_messages(scenario.nodes[0], reference, scenario.seed)):
                yield topic, {**payload, "timestamp_ms": second * 1000}


# ---------------------------------------------------------------- what the system answered

def load_observed(path: Path | str) -> list[dict[str, Any]]:
    """The alarms a server raised, from a JSON list or JSON lines: each `{"t_s": seconds from the start of the scenario, "code": ..., "zone"?, "node"?, "severity"?}`."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
        if len(text) > MAX_FILE_BYTES:
            raise ScenarioError(f"{path.name} is larger than {MAX_FILE_BYTES} bytes")
        raw = json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constants) if text.lstrip().startswith("[") else [json.loads(line, object_pairs_hook=_no_duplicates, parse_constant=_no_constants) for line in text.splitlines() if line.strip()]
    except OSError as error:
        raise ScenarioError(f"cannot read {path}: {error.strerror or error}") from None
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ScenarioError(f"{path.name} is not valid JSON in UTF-8: {error}") from None
    observed = []
    for i, item in enumerate(_list(raw, "the observed alarms", 10_000)):
        entry = _object(item, f"alarm {i}", ("t_s", "code"), ("zone", "node", "severity", "detail"))
        parsed: dict[str, Any] = {"t_s": _number(entry["t_s"], f"alarm {i}.t_s", 0, 10**7), "code": _text(entry["code"], f"alarm {i}.code", 64)}
        for key in ("zone", "node", "severity"):
            if key in entry:
                parsed[key] = _text(entry[key], f"alarm {i}.{key}", 64)
        observed.append(parsed)
    observed.sort(key=lambda a: a["t_s"])
    return observed


def _matches(expected: Mapping[str, Any], alarm: Mapping[str, Any]) -> bool:
    return all(alarm.get(key) == expected[key] for key in ("code", "zone", "node", "severity") if key in expected)


def verify_alarms(scenario: Scenario, observed: list[dict[str, Any]]) -> list[str]:
    """What is wrong in the answer of the system compared with the expectation of the scenario; an empty list means it behaved as expected."""
    problems: list[str] = []
    used: set[int] = set()
    matched_times: list[float] = []
    for number, expected in enumerate(scenario.expect_alarms, start=1):
        low, high = expected["window"]
        label = f"expected alarm {number} ({expected['code']}{' in ' + expected['zone'] if 'zone' in expected else ''}, between {low:g} s and {high:g} s)"
        found = next((i for i, alarm in enumerate(observed) if i not in used and _matches(expected, alarm) and low <= alarm["t_s"] <= high), None)
        if found is None:
            same = [alarm["t_s"] for alarm in observed if _matches(expected, alarm)]
            problems.append(f"{label} did not happen" + (f" in time: it came at {', '.join(f'{t:g}' for t in same)} s" if same else ""))
            continue
        used.add(found)
        matched_times.append(observed[found]["t_s"])
        if scenario.expect_order == "strict" and len(matched_times) > 1 and matched_times[-1] < matched_times[-2]:
            problems.append(f"{label} came at {matched_times[-1]:g} s, before the alarm expected earlier ({matched_times[-2]:g} s): the order is wrong")
    for forbidden in scenario.expect_forbidden:
        for alarm in observed:
            if _matches(forbidden, alarm) and forbidden["from_s"] <= alarm["t_s"] <= forbidden["to_s"]:
                problems.append(f"the alarm {alarm['code']} at {alarm['t_s']:g} s must not happen (a false alarm)")
    if not scenario.allow_extra:
        problems.extend(f"the alarm {alarm['code']} at {alarm['t_s']:g} s was not expected" for i, alarm in enumerate(observed) if i not in used)
    return problems


def summary(scenario: Scenario) -> str:
    kinds: dict[str, int] = {}
    for event in scenario.events:
        kinds[event["type"]] = kinds.get(event["type"], 0) + 1
    listing = ", ".join(f"{count} {kind}" for kind, count in sorted(kinds.items())) or "no events"
    return (f"{scenario.name}: {scenario.duration_s} s, {len(scenario.nodes)} node(s), {len(scenario.zones)} zone(s), {listing}; "
            f"{len(scenario.expect_alarms)} expected alarm(s), {len(scenario.expect_forbidden)} forbidden")
