"""Deterministic readings of an electrical node: the grid input, a water heater and the DC bus of a battery bank, over a fast day.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

The numbers are plausible, not measured: a house load that wobbles, a water heater that switches on and off, a DC bus that follows the same fast day as the solar
readings, a short mains outage late in the day (the grid channel reads no voltage and no power), a spell of high voltage before it and one meter alarm, so that the
alarms an operator will meet are exercised. Nothing here says how a real meter or installation will behave.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterator

from .faults import Message

DAY_SAMPLES = 240


def _phase(sample: int) -> float:
    return (sample % DAY_SAMPLES) / DAY_SAMPLES


def _outage(sample: int) -> bool:
    return 0.80 <= _phase(sample) < 0.85          # the same outage as the solar readings


def _high_voltage(sample: int) -> bool:
    return 0.60 <= _phase(sample) < 0.65


def _meter_alarm(sample: int) -> bool:
    return 0.30 <= _phase(sample) < 0.33


def electrical(node_id: str, sample: int, seed: int = 0) -> dict:
    """One message of the node: three channels."""
    rng = random.Random(seed * 1_000_003 + sample + 11)
    outage = _outage(sample)
    volts = 0.0 if outage else round((256.0 if _high_voltage(sample) else 230.0) + rng.uniform(-2, 2), 1)
    house_w = 0.0 if outage else max(0.0, 650 + 250 * math.sin(sample / 9) + rng.uniform(-40, 40))
    heater_on = (sample // 20) % 3 == 0 and not outage
    heater_w = 1800.0 + rng.uniform(-30, 30) if heater_on else 0.0
    grid_w = house_w + heater_w
    grid_a = grid_w / volts if volts else 0.0
    dc_v = round(52.0 + 3 * math.sin(2 * math.pi * _phase(sample) - 1.3) + rng.uniform(-0.05, 0.05), 2)
    dc_a = round(-18 * math.sin(2 * math.pi * _phase(sample) - 0.4) + rng.uniform(-0.3, 0.3), 2)
    return {
        "kind": "electrical", "node_id": node_id, "timestamp_ms": sample * 1000, "switching_enabled": False,
        "channels": [
            {"id": "grid", "domain": "ac", "label": "Grid input", "voltage_v": volts, "current_a": round(grid_a, 3), "power_w": round(grid_w, 1),
             "energy_kwh": round(1830 + sample * 0.0009, 3), "frequency_hz": 0.0 if outage else round(50 + rng.uniform(-0.05, 0.05), 2),
             "power_factor": 0.0 if outage else round(0.97 + rng.uniform(-0.01, 0.01), 2), "state": "open" if outage else "closed", "alarm": False},
            {"id": "heater", "domain": "ac", "label": "Water heater", "voltage_v": volts, "current_a": round(heater_w / volts, 3) if volts else 0.0, "power_w": round(heater_w, 1),
             "energy_kwh": round(402 + sample * 0.0004, 3), "frequency_hz": 0.0 if outage else 50.0, "power_factor": 1.0 if heater_on else 0.0, "alarm": _meter_alarm(sample)},
            {"id": "dc-bus", "domain": "dc", "label": "Battery bus", "voltage_v": dc_v, "current_a": dc_a, "power_w": round(dc_v * dc_a, 1), "energy_kwh": round(96 + sample * 0.0002, 3), "alarm": False},
        ],
    }


def electrical_messages(node_id: str, sample: int, seed: int = 0) -> Iterator[Message]:
    """The topic and payload of one sample of the electrical node."""
    yield f"armor/electrical/{node_id}/state", electrical(node_id, sample, seed)
