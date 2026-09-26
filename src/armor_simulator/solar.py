"""Deterministic solar readings: an inverter and a two-module battery stack, over a fast day.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

The numbers are plausible, not measured: a Voltronic-style inverter fed by panels that follow a sine over half of a fast day (240 samples), a house load
that wobbles, a battery whose charge follows the balance, cells that differ by a few millivolts and one that drifts, and a short mains outage late in the
day so that the "on the battery" mode and its warning are exercised. Nothing here says how a real inverter or battery will behave.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterator

from .faults import Message

DAY_SAMPLES = 240
MODULES = 2
CELLS = 15
MODULE_FULL_AH = 74.0
MODULE_NOMINAL_V = 48.0


def _phase(sample: int) -> float:
    return (sample % DAY_SAMPLES) / DAY_SAMPLES


def _outage(sample: int) -> bool:
    return 0.80 <= _phase(sample) < 0.85


def _pv_watts(sample: int, rng: random.Random) -> float:
    phase = _phase(sample)
    if phase >= 0.5 or _outage(sample):
        return 0.0
    return max(0.0, 3200 * math.sin(math.pi * phase * 2) + rng.uniform(-60, 60))


def _soc(sample: int) -> float:
    return round(min(100.0, max(8.0, 58 + 32 * math.sin(2 * math.pi * _phase(sample) - 1.3))), 1)


def inverter(node_id: str, sample: int, seed: int = 0, device: str = "axpert-1") -> dict:
    """One reading of the inverter."""
    rng = random.Random(seed * 1_000_003 + sample)
    pv_w, load_w, soc = _pv_watts(sample, rng), 700 + 250 * math.sin(sample / 9) + rng.uniform(-40, 40), _soc(sample)
    battery_v = round(MODULE_NOMINAL_V + 6 * soc / 100 + rng.uniform(-0.05, 0.05), 2)
    outage = _outage(sample)
    battery_a = round(-load_w / battery_v, 1) if outage else round((pv_w - load_w) / battery_v, 1)
    pv_v = round(150 + pv_w / 40, 1) if pv_w else 0.0
    return {
        "kind": "inverter", "node_id": node_id, "device": device, "timestamp_ms": sample * 1000, "mode": "battery" if outage else "line",
        "grid_v": 0.0 if outage else round(230 + rng.uniform(-2, 2), 1), "grid_hz": 0.0 if outage else 50.0, "out_v": 230.0, "out_hz": 50.0,
        "out_va": round(load_w * 1.1), "out_w": round(load_w), "load_percent": round(load_w / 50), "battery_v": battery_v, "battery_a": battery_a,
        "battery_percent": round(soc), "pv_v": pv_v, "pv_a": round(pv_w / pv_v, 1) if pv_v else 0.0, "pv_w": round(pv_w),
        "heatsink_c": round(34 + load_w / 90 + pv_w / 300), "ac_charging": False, "pv_charging": pv_w > load_w, "load_on": True,
        "warnings": ["line_fail"] if outage else [],
    }


def battery(node_id: str, sample: int, seed: int = 0, device: str = "us3000-1") -> dict:
    """One reading of a battery stack: two modules of fifteen cells, with capacities."""
    rng = random.Random(seed * 1_000_003 + sample + 7)
    soc, current = _soc(sample), inverter(node_id, sample, seed)["battery_a"]
    base = 3.2 + soc / 100 * 0.2
    stack, cells_all = [], []
    for n in range(1, MODULES + 1):
        cells = [round(base + ((i * 7 + n * 3) % 5) * 0.0015 + rng.uniform(-0.0008, 0.0008) + (0.02 if (n, i) == (2, 9) else 0.0), 3) for i in range(CELLS)]
        cells_all += cells
        stack.append({
            "n": n, "present": True, "voltage_v": round(sum(cells), 3), "current_a": round(current / MODULES, 2), "temperature_c": round(21 + n + rng.uniform(-0.3, 0.3), 1),
            "soc_percent": round(soc), "state": "Charge" if current > 0 else "Dischg", "cells_v": cells,
            "temperatures_c": [round(21 + n + rng.uniform(-0.6, 0.6), 1) for _ in range(5)],
            "capacity_ah": round(MODULE_FULL_AH * soc / 100, 1), "full_capacity_ah": MODULE_FULL_AH, "cycles": 180 + n,
        })
    voltage = round(sum(module["voltage_v"] for module in stack) / MODULES, 3)
    return {
        "kind": "battery", "node_id": node_id, "device": device, "timestamp_ms": sample * 1000, "modules": MODULES, "state": "charging" if current > 0 else "discharging",
        "voltage_v": voltage, "current_a": round(current, 2), "temperature_min_c": min(m["temperature_c"] for m in stack), "temperature_max_c": max(m["temperature_c"] for m in stack),
        "cell_min_v": min(cells_all), "cell_max_v": max(cells_all), "soc_percent": round(soc), "alarm": False, "model": "US3000C",
        "capacity_ah": round(MODULE_FULL_AH * MODULES * soc / 100, 1), "full_capacity_ah": MODULE_FULL_AH * MODULES,
        "energy_kwh": round(MODULE_FULL_AH * MODULES * soc / 100 * voltage / 1000, 2), "cycles": 181, "stack": stack,
    }


def solar_messages(node_id: str, sample: int, seed: int = 0) -> Iterator[Message]:
    """The topics and payloads of one sample of the solar equipment."""
    yield f"armor/solar/{node_id}/axpert-1/state", inverter(node_id, sample, seed)
    yield f"armor/solar/{node_id}/us3000-1/state", battery(node_id, sample, seed)
