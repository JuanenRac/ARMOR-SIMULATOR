"""Vision scenarios described in files: people and objects crossing the detection zones of a camera in each arming mode, and the vision events the rules would raise.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

A scenario is a JSON file (schema `armor-vision-scenario/1`, documented in docs/VISION_SCENARIOS.md) with the cameras and their detection zones and mode profiles (the same
shape the server keeps and hands to the observation service under `cameras[].detection`), and a timeline of the arming mode and of objects walking across the picture. `build_events`
plays the timeline against the zones with the same rules as the vision service (an object counts when its feet are inside a watched zone, the label is accepted and it stayed long
enough; one event per visit; a mode with no profile watches every zone) and gives the vision events (`armor.vision.event/v1`) in order of time. `verify_events` compares them with
what the file expects. Nothing here sees a picture or runs a detector: it is a host twin of the rules, and it says nothing about how well a real detector sees a person at night.
The file is refused whole at the first thing that is not understood.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .alarm_scenarios import MODES, ScenarioError, read_json

SCHEMA = "armor-vision-scenario/1"
MAX_DURATION_S = 3600
MAX_CAMERAS = 8
MAX_ZONES = 16
MIN_POINTS = 3
MAX_POINTS = 12
MAX_PATH = 32
MAX_EVENTS = 500
MAX_STEPS = 50_000
SENSITIVITIES = ("low", "normal", "high")
KINDS = ("alert", "detection")
ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
LABEL = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
BOX_W, BOX_H = 0.08, 0.25     # the size of the box of a walker, as a fraction of the picture
CONFIDENCE = 0.9
SPEED_RANGE = (0.001, 2.0)    # picture widths per second


@dataclass(frozen=True)
class Zone:
    id: str
    name: str
    points: tuple[tuple[float, float], ...]
    kind: str
    labels: tuple[str, ...]
    min_frames: int
    min_seconds: float


@dataclass(frozen=True)
class Camera:
    id: str
    zones: tuple[Zone, ...]
    profiles: dict[str, tuple[str, ...]]   # mode -> ids of the zones watched


@dataclass(frozen=True)
class Walk:
    at_s: float
    camera: str
    label: str
    speed: float
    path: tuple[tuple[float, float], ...]   # where the feet go, in the order of the walk


@dataclass(frozen=True)
class VisionScenario:
    name: str
    description: str
    duration_s: float
    step_s: float
    cameras: dict[str, Camera]
    modes: tuple[tuple[float, str], ...]    # (time, mode) sorted; the scenario starts in the first one
    walks: tuple[Walk, ...]
    expect: tuple[dict[str, Any], ...] = ()
    forbidden: tuple[dict[str, Any], ...] = ()


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise ScenarioError(message)


def _number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _only(raw: Any, allowed: set[str], where: str) -> dict[str, Any]:
    _need(isinstance(raw, dict), f"{where} must be an object")
    unknown = sorted(set(raw) - allowed)
    _need(not unknown, f"{where}: unknown field {unknown[0][:30]!r}" if unknown else "")
    return raw


def _point(raw: Any, where: str) -> tuple[float, float]:
    _need(isinstance(raw, list) and len(raw) == 2 and all(_number(v) and 0 <= v <= 1 for v in raw), f"{where}: a point is [x, y] with both between 0 and 1")
    return float(raw[0]), float(raw[1])


def point_in_polygon(point: tuple[float, float], polygon: tuple[tuple[float, float], ...]) -> bool:
    """Ray casting; a point on the edge counts as inside."""
    x, y = point
    inside = False
    for index, (x1, y1) in enumerate(polygon):
        x2, y2 = polygon[(index + 1) % len(polygon)]
        if abs((x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)) < 1e-12 and min(x1, x2) - 1e-12 <= x <= max(x1, x2) + 1e-12 and min(y1, y2) - 1e-12 <= y <= max(y1, y2) + 1e-12:
            return True
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _parse_zone(raw: Any, where: str) -> Zone:
    item = _only(raw, {"id", "name", "points", "kind", "labels", "min_frames", "min_seconds"}, where)
    _need(isinstance(item.get("id"), str) and ID.match(item["id"]) is not None, f"{where}: id is 1 to 32 characters of a-z, 0-9, - and _")
    _need(isinstance(item.get("name"), str) and 0 < len(item["name"].strip()) <= 60, f"{where}: name is 1 to 60 characters")
    points = item.get("points")
    _need(isinstance(points, list) and MIN_POINTS <= len(points) <= MAX_POINTS, f"{where}: {MIN_POINTS} to {MAX_POINTS} corners")
    corners = tuple(_point(p, where) for p in points)
    area = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(corners, corners[1:] + corners[:1]))) / 2
    _need(area >= 0.0001, f"{where}: the corners enclose no area")
    kind = item.get("kind", "alert")
    _need(kind in KINDS, f"{where}: kind is alert or detection")
    labels = item.get("labels", [])
    _need(isinstance(labels, list) and len(labels) <= 8 and all(isinstance(v, str) and LABEL.match(v) for v in labels), f"{where}: labels are up to 8 names")
    frames, seconds = item.get("min_frames", 1), item.get("min_seconds", 0)
    _need(isinstance(frames, int) and not isinstance(frames, bool) and 1 <= frames <= 300, f"{where}: min_frames is a whole number from 1 to 300")
    _need(_number(seconds) and 0 <= seconds <= 3600, f"{where}: min_seconds is from 0 to 3600")
    return Zone(item["id"], item["name"].strip(), corners, kind, tuple(dict.fromkeys(labels)), frames, float(seconds))


def _parse_camera(raw: Any, index: int) -> Camera:
    where = f"camera #{index + 1}"
    item = _only(raw, {"id", "detection"}, where)
    _need(isinstance(item.get("id"), str) and ID.match(item["id"]) is not None, f"{where}: id is 1 to 32 characters of a-z, 0-9, - and _")
    detection = _only(item.get("detection"), {"zones", "profiles"}, f"{where} detection")
    raw_zones = detection.get("zones")
    _need(isinstance(raw_zones, list) and 1 <= len(raw_zones) <= MAX_ZONES, f"{where}: 1 to {MAX_ZONES} zones")
    zones = tuple(_parse_zone(z, f"{where} zone #{i + 1}") for i, z in enumerate(raw_zones))
    ids = [z.id for z in zones]
    _need(len(set(ids)) == len(ids), f"{where}: a zone id is used twice")
    profiles: dict[str, tuple[str, ...]] = {}
    raw_profiles = detection.get("profiles", {})
    _need(isinstance(raw_profiles, dict), f"{where}: profiles must be an object")
    for mode, entry in raw_profiles.items():
        _need(mode in MODES, f"{where}: unknown mode {str(mode)[:20]!r}")
        profile = _only(entry, {"watch", "sensitivity", "notify"}, f"{where} profile {mode}")
        watch = profile.get("watch")
        _need(isinstance(watch, list) and all(isinstance(w, str) and w in ids for w in watch), f"{where} profile {mode}: watch lists the ids of zones of this camera")
        _need(profile.get("sensitivity", "normal") in SENSITIVITIES, f"{where} profile {mode}: sensitivity is low, normal or high")
        _need(isinstance(profile.get("notify", True), bool), f"{where} profile {mode}: notify is true or false")
        profiles[mode] = tuple(dict.fromkeys(watch))
    return Camera(item["id"], zones, profiles)


def load_scenario(path: Path | str) -> VisionScenario:
    raw = _only(read_json(path), {"schema", "name", "description", "duration_s", "step_s", "cameras", "events", "expect"}, "the scenario")
    _need(raw.get("schema") == SCHEMA, f"schema must be {SCHEMA!r}")
    name, description = raw.get("name"), raw.get("description", "")
    _need(isinstance(name, str) and 0 < len(name) <= 80 and isinstance(description, str) and len(description) <= 600, "name is 1 to 80 characters and description at most 600")
    duration, step = raw.get("duration_s"), raw.get("step_s", 0.5)
    _need(_number(duration) and 1 <= duration <= MAX_DURATION_S, f"duration_s is from 1 to {MAX_DURATION_S}")
    _need(_number(step) and 0.05 <= step <= 5, "step_s is from 0.05 to 5")
    _need(duration / step <= MAX_STEPS, "duration_s and step_s give too many steps")
    raw_cameras = raw.get("cameras")
    _need(isinstance(raw_cameras, list) and 1 <= len(raw_cameras) <= MAX_CAMERAS, f"1 to {MAX_CAMERAS} cameras")
    cameras: dict[str, Camera] = {}
    for index, item in enumerate(raw_cameras):
        camera = _parse_camera(item, index)
        _need(camera.id not in cameras, f"the camera {camera.id} appears twice")
        cameras[camera.id] = camera
    events = raw.get("events")
    _need(isinstance(events, list) and 1 <= len(events) <= MAX_EVENTS, f"1 to {MAX_EVENTS} events")
    modes: list[tuple[float, str]] = []
    walks: list[Walk] = []
    for index, event in enumerate(events):
        where = f"event #{index + 1}"
        _need(isinstance(event, dict) and event.get("type") in ("mode", "walk"), f"{where}: type is mode or walk")
        at = event.get("at_s")
        _need(_number(at) and 0 <= at < duration, f"{where}: at_s is inside the scenario")
        if event["type"] == "mode":
            item = _only(event, {"type", "at_s", "mode"}, where)
            _need(item.get("mode") in MODES, f"{where}: mode is one of {', '.join(MODES)}")
            modes.append((float(at), item["mode"]))
            continue
        item = _only(event, {"type", "at_s", "camera", "label", "speed", "path"}, where)
        _need(item.get("camera") in cameras, f"{where}: the camera does not exist")
        _need(isinstance(item.get("label"), str) and LABEL.match(item["label"]) is not None, f"{where}: label is a name of a-z, 0-9, - and _")
        speed = item.get("speed", 0.1)
        _need(_number(speed) and SPEED_RANGE[0] <= speed <= SPEED_RANGE[1], f"{where}: speed is from {SPEED_RANGE[0]} to {SPEED_RANGE[1]} picture widths per second")
        path = item.get("path")
        _need(isinstance(path, list) and 2 <= len(path) <= MAX_PATH, f"{where}: path has 2 to {MAX_PATH} points")
        walks.append(Walk(float(at), item["camera"], item["label"], float(speed), tuple(_point(p, where) for p in path)))
    _need(bool(modes) and min(t for t, _ in modes) == 0, "the first mode event must be at 0 s (the scenario has to start in a mode)")
    _need(len({t for t, _ in modes}) == len(modes), "two mode events at the same time")
    expect, forbidden = _parse_expect(raw.get("expect", {}), cameras, duration)
    return VisionScenario(name, description, float(duration), float(step), cameras, tuple(sorted(modes)), tuple(sorted(walks, key=lambda w: w.at_s)), expect, forbidden)


def _parse_expect(raw: Any, cameras: dict[str, Camera], duration: float) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    item = _only(raw, {"events", "forbidden"}, "expect")
    out: list[tuple[dict[str, Any], ...]] = []
    for key in ("events", "forbidden"):
        rows = item.get(key, [])
        _need(isinstance(rows, list) and len(rows) <= 100, f"expect.{key} is a list of at most 100 rows")
        clean = []
        for index, row in enumerate(rows):
            where = f"expect.{key} #{index + 1}"
            allowed = {"camera", "zone", "label", "between_s"} if key == "events" else {"camera", "zone", "label"}
            entry = _only(row, allowed, where)
            _need(entry.get("camera") in cameras, f"{where}: the camera does not exist")
            _need(entry.get("zone") in {z.id for z in cameras[entry["camera"]].zones}, f"{where}: the zone does not exist in that camera")
            window = entry.get("between_s")
            if window is not None:
                _need(isinstance(window, list) and len(window) == 2 and all(_number(v) and 0 <= v <= duration for v in window) and window[0] <= window[1], f"{where}: between_s is [from, to] inside the scenario")
            clean.append(dict(entry))
        out.append(tuple(clean))
    return out[0], out[1]


def _position(walk: Walk, t: float) -> tuple[float, float] | None:
    """Where the feet are at time t, or None before the walk starts and after it ends."""
    lengths = [math.dist(a, b) for a, b in zip(walk.path, walk.path[1:])]
    total = sum(lengths)
    duration = total / walk.speed
    local = t - walk.at_s
    if local < 0 or local > duration:
        return None
    if total == 0:
        return walk.path[0]
    travelled = local * walk.speed
    for (a, b), length in zip(zip(walk.path, walk.path[1:]), lengths):
        if travelled <= length:
            ratio = 0.0 if length == 0 else travelled / length
            return a[0] + (b[0] - a[0]) * ratio, a[1] + (b[1] - a[1]) * ratio
        travelled -= length
    return walk.path[-1]


def _mode_at(scenario: VisionScenario, t: float) -> str:
    mode = scenario.modes[0][1]
    for at, name in scenario.modes:
        if at <= t:
            mode = name
    return mode


def watched(camera: Camera, mode: str) -> tuple[Zone, ...]:
    """The zones that count in a mode: every zone when the mode has no profile (an unknown mode never watches less), else the ones the profile lists."""
    ids = camera.profiles.get(mode)
    return camera.zones if ids is None else tuple(z for z in camera.zones if z.id in ids)


def build_events(scenario: VisionScenario) -> list[dict[str, Any]]:
    """The vision events of the scenario in order of time, deterministic."""
    events: list[dict[str, Any]] = []
    visits: dict[tuple[int, str], tuple[int, float, bool]] = {}   # (walk, zone) -> (steps inside, time of entry, already reported)
    steps = int(scenario.duration_s / scenario.step_s) + 1
    for index in range(steps):
        t = round(index * scenario.step_s, 6)
        if t >= scenario.duration_s:
            break
        mode = _mode_at(scenario, t)
        for number, walk in enumerate(scenario.walks):
            foot = _position(walk, t)
            camera = scenario.cameras[walk.camera]
            on = {z.id for z in watched(camera, mode)}
            for zone in camera.zones:
                key = (number, zone.id)
                inside = foot is not None and zone.id in on and (not zone.labels or walk.label in zone.labels) and point_in_polygon(foot, zone.points)
                if not inside:
                    visits.pop(key, None)
                    continue
                assert foot is not None
                frames, entered, done = visits.get(key, (0, t, False))
                frames += 1
                if not done and frames >= zone.min_frames and t - entered >= zone.min_seconds:
                    done = True
                    events.append({
                        "schema": "armor.vision.event/v1", "type": zone.kind, "camera_id": camera.id, "zone_id": zone.id, "zone_name": zone.name, "track_id": number + 1,
                        "label": walk.label, "confidence": CONFIDENCE,
                        "box": [round(foot[0] - BOX_W / 2, 4), round(foot[1] - BOX_H, 4), round(foot[0] + BOX_W / 2, 4), round(foot[1], 4)],
                        "timestamp": t, "timestamp_ms": int(round(t * 1000)), "authorizes_action": False,
                    })
                visits[key] = (frames, entered, done)
    for event in events:
        event["box"] = [min(max(v, 0.0), 1.0) for v in event["box"]]
    return events


def verify_events(scenario: VisionScenario, events: list[dict[str, Any]]) -> list[str]:
    """The differences between the events and what the file expects: each expected row needs an event of that camera and zone (and label, and time window); a forbidden one must not appear."""
    problems: list[str] = []

    def matches(row: dict[str, Any], event: dict[str, Any]) -> bool:
        return event["camera_id"] == row["camera"] and event["zone_id"] == row["zone"] and row.get("label", event["label"]) == event["label"]

    for row in scenario.expect:
        window = row.get("between_s")
        found = [e for e in events if matches(row, e) and (window is None or window[0] <= e["timestamp"] <= window[1])]
        if not found:
            problems.append(f"expected an event in zone {row['zone']} of {row['camera']}" + (f" between {window[0]:g} and {window[1]:g} s" if window else "") + ", there was none")
    for row in scenario.forbidden:
        for event in events:
            if matches(row, event):
                problems.append(f"zone {row['zone']} of {row['camera']} must stay quiet, but raised an event at {event['timestamp']:g} s ({event['label']})")
                break
    return problems


def summary(scenario: VisionScenario) -> str:
    zones = sum(len(c.zones) for c in scenario.cameras.values())
    profiles = sum(len(c.profiles) for c in scenario.cameras.values())
    return (f"{scenario.name}: {scenario.duration_s:g} s in steps of {scenario.step_s:g} s, {len(scenario.cameras)} camera(s), {zones} zone(s), {profiles} profile(s), "
            f"{len(scenario.modes)} mode change(s), {len(scenario.walks)} walk(s), {len(scenario.expect)} expected and {len(scenario.forbidden)} forbidden event(s)")
