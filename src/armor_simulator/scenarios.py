"""Deterministic scenarios: what the simulated radars and light sensor report.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

The geometry is illustrative, not a model of the real hardware: a node covers a
90 degree corner with three sensors whose boresights are 0, 45 and 90 degrees
(x to the right, y forward, millimetres). It exists so that consumers can be
exercised with plausible, repeatable tracks; it is not evidence of how the real
LD2450 modules will behave.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable

# Sensor boresight (degrees from the +y axis) and the half field of view.
SENSOR_BORESIGHT = {1: -45.0, 2: 0.0, 3: 45.0}
HALF_FOV_DEG = 60.0
MAX_RANGE_MM = 6000.0
SAMPLE_PERIOD_S = 1.0

Track = dict[str, float | int]
Scenario = Callable[[int, random.Random], list[tuple[float, float, float]]]


def _sensor_for(x_mm: float, y_mm: float) -> int | None:
    """The sensor that sees a point, or None when it is outside every field of view."""
    if y_mm <= 0 or math.hypot(x_mm, y_mm) > MAX_RANGE_MM:
        return None
    azimuth = math.degrees(math.atan2(x_mm, y_mm))
    best = min(SENSOR_BORESIGHT, key=lambda sensor: abs(azimuth - SENSOR_BORESIGHT[sensor]))
    return best if abs(azimuth - SENSOR_BORESIGHT[best]) <= HALF_FOV_DEG else None


def patrol(sample: int, _rng: random.Random) -> list[tuple[float, float, float]]:
    """One target circling at 3 m. Only the half of the circle in front of the node is seen, so it drops out and returns."""
    angle = sample * math.pi / 12
    return [(3000 * math.cos(angle), 3000 * math.sin(angle), 785.4)]


def crossing(sample: int, rng: random.Random) -> list[tuple[float, float, float]]:
    """A person walking left to right across the field at about 1.2 m/s, 3.5 m out."""
    period = 12
    step = sample % period
    x = -3600 + step * (7200 / (period - 1))
    y = 3500 + rng.uniform(-60, 60)
    return [(x, y, 1200.0)]


def two_intruders(sample: int, rng: random.Random) -> list[tuple[float, float, float]]:
    """Two people approaching from different sides: the case that raises a high alert while armed."""
    progress = (sample % 10) / 9
    a = (-2500 + 2300 * progress, 5200 - 3000 * progress + rng.uniform(-40, 40), 900.0)
    b = (2600 - 2400 * progress, 5000 - 2600 * progress + rng.uniform(-40, 40), 900.0)
    return [a, b]


def empty(_sample: int, _rng: random.Random) -> list[tuple[float, float, float]]:
    """A quiet perimeter: nothing to report."""
    return []


SCENARIOS: dict[str, Scenario] = {"patrol": patrol, "crossing": crossing, "two-intruders": two_intruders, "empty": empty}


def lux_for(sample: int, mode: str) -> float:
    """Ambient light: a day/night cycle, or a fixed night for the low-light profile."""
    if mode == "night":
        return 0.3
    angle = sample * math.pi / 12
    return round(4000 + 3000 * max(0.0, math.sin(angle)), 2)


def tracks_for(scenario: str, sample: int, rng: random.Random) -> list[Track]:
    """The tracks the three sensors would report at this sample, at most five per sensor."""
    per_sensor: dict[int, int] = {}
    tracks: list[Track] = []
    for x_mm, y_mm, speed in SCENARIOS[scenario](sample, rng):
        sensor = _sensor_for(x_mm, y_mm)
        if sensor is None:
            continue
        per_sensor[sensor] = per_sensor.get(sensor, 0) + 1
        if per_sensor[sensor] > 5:  # the radar tracks at most five targets
            continue
        tracks.append({"sensor_id": sensor, "track_id": len(tracks) + 1, "x_mm": round(x_mm, 1), "y_mm": round(y_mm, 1), "speed_mm_s": speed})
    return tracks


def telemetry(node_id: str, sample: int, scenario: str = "patrol", light: str = "cycle", seed: int = 0) -> dict:
    """One telemetry payload. The same arguments always give the same payload."""
    rng = random.Random(f"{seed}:{node_id}:{sample}")
    return {"node_id": node_id, "timestamp_ms": sample * 1000, "lux": lux_for(sample, light), "targets": tracks_for(scenario, sample, rng)}


def health(node_id: str, sample: int, online: bool = True) -> dict:
    return {"node_id": node_id, "timestamp_ms": sample * 1000, "online": online}
