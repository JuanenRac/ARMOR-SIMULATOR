"""Deterministic scenarios: what the simulated radars and light sensor report.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

The geometry is illustrative, not a model of the real hardware: a node covers 270 degrees
with three sensors whose boresights are -75, 0 and +75 degrees, each seeing 60 degrees to
either side (x to the right, y forward, millimetres), so neighbours overlap by 45 degrees and
the 90 degrees behind the node are blind, like the 270 degree node of ARMOR-RADAR. It exists so
that consumers can be exercised with plausible, repeatable tracks; it is not evidence of
how the real modules will behave. Positions and speeds are whole numbers, as the
firmware sends them, a track keeps its id for as long as its object is in the scene, and the
speed is the radial one as seen by the sensor: negative when the object comes closer, positive
when it goes away (the sign convention is illustrative too).
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable

from .cycle import phase

# Sensor boresight (degrees from the +y axis) and the half field of view.
SENSOR_BORESIGHT = {1: -75.0, 2: 0.0, 3: 75.0}
HALF_FOV_DEG = 60.0
MAX_RANGE_MM = 6000.0
SAMPLE_PERIOD_S = 1.0
MAX_STEP_MM = 3000.0  # nothing in the scenarios moves farther than this in one sample

Track = dict[str, float | int]
Scenario = Callable[[int, random.Random], list[tuple[float, float, float]]]


def _sensor_for(x_mm: float, y_mm: float) -> int | None:
    """The sensor that sees a point, or None when it is outside every field of view."""
    distance = math.hypot(x_mm, y_mm)
    if distance == 0 or distance > MAX_RANGE_MM:
        return None
    azimuth = math.degrees(math.atan2(x_mm, y_mm))
    best = min(SENSOR_BORESIGHT, key=lambda sensor: abs(azimuth - SENSOR_BORESIGHT[sensor]))
    return best if abs(azimuth - SENSOR_BORESIGHT[best]) <= HALF_FOV_DEG else None


def _radial_speed(sensor: int, before: tuple[float, float], after: tuple[float, float]) -> float:
    """Millimetres per second along the line from the sensor to the object: negative when it comes closer. The sensors sit at the node's origin."""
    del sensor  # every sensor is at the origin; the argument keeps the call site explicit about whose view this is
    d0, d1 = math.hypot(*before), math.hypot(*after)
    return (d1 - d0) / SAMPLE_PERIOD_S


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
    """Ambient light: the day of the simulation (the same day as the solar and electrical sources: 240 samples), with a real night, or a fixed night for the low-light profile."""
    if mode == "night":
        return 0.3
    sun = max(0.0, math.sin(2 * math.pi * phase(sample)))
    return round(0.3 + 50_000 * sun ** 1.5, 2)


def tracks_for(scenario: str, sample: int, rng: random.Random) -> list[Track]:
    """The tracks the three sensors would report at this sample, at most five per sensor."""
    per_sensor: dict[int, int] = {}
    tracks: list[Track] = []
    state = rng.getstate()

    def at(index: int) -> list[tuple[float, float, float]]:
        generator = random.Random()
        generator.setstate(state)  # the same jitter at every instant, so the speed is the motion and not the noise
        return SCENARIOS[scenario](index, generator)

    now = SCENARIOS[scenario](sample, rng)
    ahead = at(sample + 1)
    # A scenario repeats after a few samples; across that jump the motion is measured backwards instead.
    if any(math.hypot(a[0] - n[0], a[1] - n[1]) > MAX_STEP_MM for a, n in zip(ahead, now)):
        ahead = [(2 * n[0] - b[0], 2 * n[1] - b[1], 0.0) for b, n in zip(at(sample - 1), now)]
    for slot, (x_mm, y_mm, _speed) in enumerate(now, start=1):
        sensor = _sensor_for(x_mm, y_mm)
        if sensor is None:
            continue
        per_sensor[sensor] = per_sensor.get(sensor, 0) + 1
        if per_sensor[sensor] > 5:  # the radar tracks at most five targets
            continue
        tracks.append({"sensor_id": sensor, "track_id": slot, "x_mm": round(x_mm), "y_mm": round(y_mm), "speed_mm_s": round(_radial_speed(sensor, (x_mm, y_mm), ahead[slot - 1][:2]))})
    return tracks


def telemetry(node_id: str, sample: int, scenario: str = "patrol", light: str = "cycle", seed: int = 0) -> dict:
    """One telemetry payload. The same arguments always give the same payload."""
    rng = random.Random(f"{seed}:{node_id}:{sample}")
    return {"node_id": node_id, "timestamp_ms": sample * 1000, "lux": lux_for(sample, light), "targets": tracks_for(scenario, sample, rng)}


def health(node_id: str, sample: int, online: bool = True) -> dict:
    return {"node_id": node_id, "timestamp_ms": sample * 1000, "online": online}
