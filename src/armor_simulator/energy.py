"""Realistic, deterministic solar and electrical data: a day of sun with clouds, a house that eats by the hour, a tariff, a Pylontech-style battery and a noisy meter.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

Unlike solar.py and electrical.py (a fast day of 240 samples, for exercising a consumer), this model runs in real time: a sample is `step_s` seconds (900 by default) and a
day is 86 400 s, so a run of days looks like the data of a real installation. Everything that can be tuned (the sun, the clouds, the house, the tariff, the battery and the
meter) is in a configuration (`DEFAULTS`, overridden by a JSON file), validated strictly. Same seed and same configuration, same data.

What the model guarantees (and the tests check): the production is exactly zero outside the hours of sun; the state of charge never leaves `min_soc`..100 %; the power that goes
in and the power that comes out balance at every step (the house, the panels, the battery and the grid); the energy counters never go down; the price follows the tariff.
It is a plausible model, not a measurement: nothing here says how a real panel, inverter, battery or meter will behave.
"""

from __future__ import annotations

import copy
import math
import random
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from .alarm_scenarios import ScenarioError, read_json
from .faults import Message
from .solar import battery as battery_template
from .solar import inverter as inverter_template

MAX_STEPS = 10_000
DAY_S = 86_400

DEFAULTS: dict[str, Any] = {
    "sun": {"sunrise_h": 6.5, "sunset_h": 20.5, "shape": 1.3},
    "pv": {"peak_w": 3200.0, "mean_cloud": 0.35, "cloud_persistence": 0.92, "cloud_variability": 0.12, "cloud_loss": 0.85, "noise_w": 40.0},
    "load": {"base_w": 250.0, "morning_peak_w": 900.0, "evening_peak_w": 1400.0, "noise_w": 60.0, "weekend_factor": 1.15,
             "appliance_w": 2000.0, "appliances_per_day": 4.0, "appliance_minutes": 25.0},
    "tariff": {
        "periods": [{"from": "00:00", "to": "08:00", "name": "valley", "eur_kwh": 0.08}, {"from": "08:00", "to": "10:00", "name": "flat", "eur_kwh": 0.15},
                    {"from": "10:00", "to": "14:00", "name": "peak", "eur_kwh": 0.24}, {"from": "14:00", "to": "18:00", "name": "flat", "eur_kwh": 0.15},
                    {"from": "18:00", "to": "22:00", "name": "peak", "eur_kwh": 0.24}, {"from": "22:00", "to": "00:00", "name": "flat", "eur_kwh": 0.15}],
        "weekend_eur_kwh": 0.08, "export_eur_kwh": 0.06,
    },
    "battery": {"modules": 2, "module_ah": 74.0, "nominal_v": 48.0, "min_soc": 10.0, "initial_soc": 60.0, "max_charge_w": 3000.0, "max_discharge_w": 3000.0,
                "efficiency": 0.95, "initial_cycles": 180},
    "grid": {"export": True, "voltage_v": 230.0, "voltage_noise_v": 2.0, "outages": []},
    "meter": {"noise_percent": 1.0, "dropout_probability": 0.02, "dropout_burst_max": 4},
    "start_weekday": 0,
}
# State of charge (%) against the voltage of one lithium iron phosphate cell (V): flat in the middle, steep at the ends, as such cells are.
CELL_CURVE = ((0.0, 3.00), (10.0, 3.20), (20.0, 3.25), (50.0, 3.28), (80.0, 3.33), (90.0, 3.38), (100.0, 3.45))
CELLS = 15


def _merge(base: dict[str, Any], override: Mapping[str, Any], where: str) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key not in result:
            raise ScenarioError(f"{where}{key} is not a setting of the energy model")
        if isinstance(result[key], dict):
            if not isinstance(value, dict):
                raise ScenarioError(f"{where}{key} must be an object")
            result[key] = _merge(result[key], value, f"{where}{key}.")
        else:
            kind = type(result[key])
            if kind in (int, float):
                right = isinstance(value, (int, float)) and not isinstance(value, bool)
            else:
                right = isinstance(value, kind)
            if not right:
                raise ScenarioError(f"{where}{key} has the wrong type")
            result[key] = value
    return result


def _minutes(value: Any, where: str) -> int:
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":" or not (value[:2] + value[3:]).isdigit():
        raise ScenarioError(f"{where} must be a time of day as HH:MM")
    hours, minutes = int(value[:2]), int(value[3:])
    if hours > 24 or minutes > 59 or (hours == 24 and minutes):
        raise ScenarioError(f"{where} must be a time of day as HH:MM")
    return hours * 60 + minutes


def _num(config: Mapping[str, Any], key: str, where: str, low: float, high: float) -> float:
    value = config[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ScenarioError(f"{where}{key} must be a number from {low} to {high}")
    return float(value)


def check_config(config: dict[str, Any]) -> dict[str, Any]:
    """Validates a complete configuration (limits, types, a tariff that covers the whole day once); raises ScenarioError."""
    sun, pv, load, bat, grid, meter = config["sun"], config["pv"], config["load"], config["battery"], config["grid"], config["meter"]
    if not 0 <= _num(sun, "sunrise_h", "sun.", 0, 24) < _num(sun, "sunset_h", "sun.", 0, 24):
        raise ScenarioError("sun.sunrise_h must be earlier than sun.sunset_h")
    _num(sun, "shape", "sun.", 0.5, 4)
    _num(pv, "peak_w", "pv.", 0, 100_000)
    _num(pv, "mean_cloud", "pv.", 0, 1)
    _num(pv, "cloud_persistence", "pv.", 0, 0.999)
    _num(pv, "cloud_variability", "pv.", 0, 1)
    _num(pv, "cloud_loss", "pv.", 0, 1)
    _num(pv, "noise_w", "pv.", 0, 10_000)
    for key, high in (("base_w", 50_000), ("morning_peak_w", 50_000), ("evening_peak_w", 50_000), ("noise_w", 10_000), ("appliance_w", 50_000), ("appliances_per_day", 50), ("appliance_minutes", 600)):
        _num(load, key, "load.", 0, high)
    _num(load, "weekend_factor", "load.", 0.1, 5)
    _num(bat, "module_ah", "battery.", 1, 1000)
    _num(bat, "nominal_v", "battery.", 1, 1000)
    _num(bat, "min_soc", "battery.", 0, 99)
    _num(bat, "initial_soc", "battery.", 0, 100)
    _num(bat, "max_charge_w", "battery.", 0, 1_000_000)
    _num(bat, "max_discharge_w", "battery.", 0, 1_000_000)
    _num(bat, "efficiency", "battery.", 0.5, 1)
    if isinstance(bat["modules"], bool) or not isinstance(bat["modules"], int) or not 1 <= bat["modules"] <= 16:
        raise ScenarioError("battery.modules must be a whole number from 1 to 16")
    if isinstance(bat["initial_cycles"], bool) or not isinstance(bat["initial_cycles"], int) or not 0 <= bat["initial_cycles"] <= 100_000:
        raise ScenarioError("battery.initial_cycles must be a whole number from 0 to 100000")
    if bat["initial_soc"] < bat["min_soc"]:
        raise ScenarioError("battery.initial_soc must not be below battery.min_soc")
    if not isinstance(grid["export"], bool):
        raise ScenarioError("grid.export must be true or false")
    _num(grid, "voltage_v", "grid.", 100, 600)
    _num(grid, "voltage_noise_v", "grid.", 0, 50)
    outages = grid["outages"]
    if not isinstance(outages, list) or len(outages) > 100:
        raise ScenarioError("grid.outages must be a list of at most 100 entries")
    for i, outage in enumerate(outages):
        if not isinstance(outage, dict) or set(outage) != {"at_s", "duration_s"}:
            raise ScenarioError(f"grid.outages[{i}] must be an object with at_s and duration_s")
        for key in ("at_s", "duration_s"):
            if isinstance(outage[key], bool) or not isinstance(outage[key], int) or outage[key] < 0 or (key == "duration_s" and outage[key] < 1):
                raise ScenarioError(f"grid.outages[{i}].{key} must be a whole number of seconds")
    _num(meter, "noise_percent", "meter.", 0, 50)
    _num(meter, "dropout_probability", "meter.", 0, 1)
    if isinstance(meter["dropout_burst_max"], bool) or not isinstance(meter["dropout_burst_max"], int) or not 1 <= meter["dropout_burst_max"] <= 100:
        raise ScenarioError("meter.dropout_burst_max must be a whole number from 1 to 100")
    if isinstance(config["start_weekday"], bool) or not isinstance(config["start_weekday"], int) or not 0 <= config["start_weekday"] <= 6:
        raise ScenarioError("start_weekday must be 0 (Monday) to 6 (Sunday)")
    tariff = config["tariff"]
    _num(tariff, "weekend_eur_kwh", "tariff.", 0, 100)
    _num(tariff, "export_eur_kwh", "tariff.", 0, 100)
    periods = tariff["periods"]
    if not isinstance(periods, list) or not 1 <= len(periods) <= 24:
        raise ScenarioError("tariff.periods must be a list of 1 to 24 periods")
    covered = [0] * 1440
    for i, period in enumerate(periods):
        if not isinstance(period, dict) or set(period) != {"from", "to", "name", "eur_kwh"} or not isinstance(period["name"], str) or not 0 < len(period["name"]) <= 32:
            raise ScenarioError(f"tariff.periods[{i}] must be an object with from, to, name and eur_kwh")
        _num(period, "eur_kwh", f"tariff.periods[{i}].", 0, 100)
        start, end = _minutes(period["from"], f"tariff.periods[{i}].from"), _minutes(period["to"], f"tariff.periods[{i}].to")
        if start == end:
            raise ScenarioError(f"tariff.periods[{i}] is empty")
        for minute in (range(start, end) if start < end else [*range(start, 1440), *range(0, end)]):
            covered[minute % 1440] += 1
    if any(count != 1 for count in covered):
        raise ScenarioError("tariff.periods must cover every minute of the day exactly once")
    return config


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    """The default configuration, or the default one with the settings of a JSON file on top of it."""
    if path is None:
        return check_config(copy.deepcopy(DEFAULTS))
    data = read_json(path)
    if not isinstance(data, dict):
        raise ScenarioError("the energy configuration must be an object")
    data = {key: value for key, value in data.items() if key != "schema"}
    return check_config(_merge(DEFAULTS, data, ""))


def price_at(config: Mapping[str, Any], second: float, weekday0: int | None = None) -> float:
    """The price of a kWh bought from the grid at a second of the run (the weekend has a single price all day)."""
    day = int(second // DAY_S)
    weekday = ((config["start_weekday"] if weekday0 is None else weekday0) + day) % 7
    tariff = config["tariff"]
    if weekday >= 5:
        return float(tariff["weekend_eur_kwh"])
    minute = int(second % DAY_S // 60)
    for period in tariff["periods"]:
        start, end = _minutes(period["from"], ""), _minutes(period["to"], "")
        if (start <= minute < end) if start < end else (minute >= start or minute < end):
            return float(period["eur_kwh"])
    raise AssertionError("the tariff covers the whole day")   # check_config guarantees it


def cell_voltage(soc: float) -> float:
    """Voltage of one cell at a state of charge (linear between the points of CELL_CURVE)."""
    soc = min(100.0, max(0.0, soc))
    for (s0, v0), (s1, v1) in zip(CELL_CURVE, CELL_CURVE[1:], strict=False):
        if soc <= s1:
            return v0 + (v1 - v0) * (soc - s0) / (s1 - s0)
    return CELL_CURVE[-1][1]


def _bump(hour: float, centre: float, width: float) -> float:
    return math.exp(-((hour - centre) / width) ** 2 / 2)


def simulate(config: dict[str, Any], seed: int, steps: int, step_s: int) -> Iterator[dict[str, Any]]:
    """The rows of the model, one per step: what the sun gave, what the house asked, what the battery and the grid did, and what a meter would have read."""
    rng = random.Random(f"energy:{seed}")
    pv, load, bat, grid, meter, sun = config["pv"], config["load"], config["battery"], config["grid"], config["meter"], config["sun"]
    hours = step_s / 3600
    capacity_wh = bat["modules"] * bat["module_ah"] * bat["nominal_v"]
    stored_wh = capacity_wh * bat["initial_soc"] / 100
    floor_wh = capacity_wh * bat["min_soc"] / 100
    cloud = pv["mean_cloud"]
    appliance_left = 0.0
    counters = {"import": 0.0, "export": 0.0, "load": 0.0, "pv": 0.0, "discharge": 0.0, "charge": 0.0}
    dropout_left = 0
    for step in range(steps):
        second = step * step_s
        hour = second % DAY_S / 3600
        weekday = (config["start_weekday"] + second // DAY_S) % 7
        cloud = min(1.0, max(0.0, pv["cloud_persistence"] * cloud + (1 - pv["cloud_persistence"]) * pv["mean_cloud"] + rng.gauss(0, pv["cloud_variability"] * (1 - pv["cloud_persistence"]) ** 0.5)))
        daylight = sun["sunrise_h"] <= hour < sun["sunset_h"]
        if daylight:
            span = sun["sunset_h"] - sun["sunrise_h"]
            clear = pv["peak_w"] * math.sin(math.pi * (hour - sun["sunrise_h"]) / span) ** sun["shape"]
            pv_w = max(0.0, clear * (1 - pv["cloud_loss"] * cloud) + rng.gauss(0, pv["noise_w"]) * (clear / pv["peak_w"] if pv["peak_w"] else 0))
        else:
            rng.gauss(0, 1)   # keep the stream aligned with the day, so a run is a prefix of a longer one
            pv_w = 0.0
        if appliance_left <= 0 and rng.random() < load["appliances_per_day"] * step_s / DAY_S:
            appliance_left = load["appliance_minutes"] * 60 * rng.uniform(0.5, 1.5)
        appliance_w = load["appliance_w"] if appliance_left > 0 else 0.0
        appliance_left -= step_s
        house_w = max(30.0, (load["base_w"] + load["morning_peak_w"] * _bump(hour, 7.5, 1.0) + load["evening_peak_w"] * _bump(hour, 21.0, 1.8)) * (load["weekend_factor"] if weekday >= 5 else 1.0)
                      + appliance_w + rng.gauss(0, load["noise_w"]))
        mains_out = any(o["at_s"] <= second < o["at_s"] + o["duration_s"] for o in grid["outages"])

        net_w = pv_w - house_w
        charge_w = discharge_w = import_w = export_w = curtailed_w = unserved_w = 0.0
        if net_w >= 0:
            room_wh = capacity_wh - stored_wh
            charge_w = min(net_w, bat["max_charge_w"], room_wh / (bat["efficiency"] * hours))
            stored_wh += charge_w * bat["efficiency"] * hours
            spare = net_w - charge_w
            if grid["export"] and not mains_out:
                export_w = spare
            else:
                curtailed_w = spare
        else:
            need_w = -net_w
            available_wh = max(0.0, stored_wh - floor_wh)
            discharge_w = min(need_w, bat["max_discharge_w"], available_wh * bat["efficiency"] / hours)
            stored_wh -= discharge_w / bat["efficiency"] * hours
            rest = need_w - discharge_w
            if mains_out:
                unserved_w = rest
            else:
                import_w = rest
        stored_wh = min(capacity_wh, max(floor_wh, stored_wh))
        soc = stored_wh / capacity_wh * 100
        for key, power in (("import", import_w), ("export", export_w), ("load", house_w - unserved_w), ("pv", pv_w), ("discharge", discharge_w), ("charge", charge_w)):
            counters[key] += power * hours / 1000
        price = price_at(config, second)

        # What the meter reads: the true power with noise, and now and then no reading at all (a hole of a few steps).
        if dropout_left > 0:
            dropout_left -= 1
            gap = True
        elif rng.random() < meter["dropout_probability"]:
            dropout_left = rng.randint(1, meter["dropout_burst_max"]) - 1
            gap = True
        else:
            gap = False
        noise = meter["noise_percent"] / 100
        grid_w = import_w - export_w
        yield {
            "t_s": second, "hour": round(hour, 4), "weekday": weekday, "cloud": round(cloud, 4), "pv_w": pv_w, "house_w": house_w, "unserved_w": unserved_w,
            "charge_w": charge_w, "discharge_w": discharge_w, "import_w": import_w, "export_w": export_w, "curtailed_w": curtailed_w, "grid_w": grid_w,
            "soc_percent": soc, "stored_wh": stored_wh, "cycles": bat["initial_cycles"] + counters["discharge"] * 1000 / (2 * capacity_wh), "mains": not mains_out,
            "price_eur_kwh": price, "export_price_eur_kwh": config["tariff"]["export_eur_kwh"], "cost_eur": import_w * hours / 1000 * price - export_w * hours / 1000 * config["tariff"]["export_eur_kwh"],
            "counters_kwh": dict(counters), "meter_gap": gap,
            "meter_grid_w": grid_w * (1 + rng.gauss(0, noise)), "meter_house_w": house_w * (1 + rng.gauss(0, noise)), "meter_voltage_v": 0.0 if mains_out else grid["voltage_v"] + rng.gauss(0, grid["voltage_noise_v"]),
        }


def energy_messages(node_id: str, config: dict[str, Any], seed: int, steps: int, step_s: int) -> Iterator[Message]:
    """The model as messages of the solar and electrical contracts (an inverter, a battery stack and an electrical node), so they can be validated and delivered like the others.
    A step in which the meter has a hole produces no electrical message."""
    bat = config["battery"]
    capacity_ah = bat["modules"] * bat["module_ah"]
    inverter_base = inverter_template(node_id, 0, seed)
    battery_base = battery_template(node_id, 0, seed)
    base_cell = 3.2 + battery_base["soc_percent"] / 100 * 0.2
    offsets = [[cell - base_cell for cell in module["cells_v"]] for module in battery_base["stack"]]
    for row in simulate(config, seed, steps, step_s):
        timestamp = row["t_s"] * 1000
        soc, v_cell = row["soc_percent"], cell_voltage(row["soc_percent"])
        pack_v = round(CELLS * v_cell, 3)
        current = (row["charge_w"] - row["discharge_w"]) / pack_v
        out_w = row["house_w"] - row["unserved_w"]
        state = "charging" if current > 0.05 else "discharging" if current < -0.05 else "idle"
        inverter = {**inverter_base, "timestamp_ms": timestamp, "mode": "line" if row["mains"] else "battery", "grid_v": 0.0 if not row["mains"] else round(row["meter_voltage_v"], 1),
                    "grid_hz": 50.0 if row["mains"] else 0.0, "out_w": round(out_w), "out_va": round(out_w * 1.1), "load_percent": round(min(200.0, out_w / 50)),
                    "battery_v": pack_v, "battery_a": round(current, 1), "battery_percent": round(soc), "pv_w": round(row["pv_w"]), "pv_v": round(150 + row["pv_w"] / 40, 1) if row["pv_w"] >= 1 else 0.0,
                    "pv_a": round(row["pv_w"] / (150 + row["pv_w"] / 40), 1) if row["pv_w"] >= 1 else 0.0, "pv_charging": row["pv_w"] > row["house_w"], "ac_charging": False,
                    "warnings": [] if row["mains"] else ["line_fail"]}
        yield f"armor/solar/{node_id}/axpert-1/state", inverter
        stack = []
        for n, module in enumerate(battery_base["stack"]):
            cells = [round(v_cell + offset, 3) for offset in offsets[n]]
            stack.append({**module, "voltage_v": round(sum(cells), 3), "current_a": round(current / bat["modules"], 2), "soc_percent": round(soc), "state": "Charge" if current > 0.05 else "Dischg" if current < -0.05 else "Idle",
                          "cells_v": cells, "capacity_ah": round(bat["module_ah"] * soc / 100, 1), "full_capacity_ah": bat["module_ah"], "cycles": int(row["cycles"])})
        yield f"armor/solar/{node_id}/us3000-1/state", {
            **battery_base, "timestamp_ms": timestamp, "modules": bat["modules"], "state": state, "voltage_v": pack_v, "current_a": round(current, 2), "soc_percent": round(soc), "power_w": round(row["charge_w"] - row["discharge_w"], 1),
            "cell_min_v": min(c for m in stack for c in m["cells_v"]), "cell_max_v": max(c for m in stack for c in m["cells_v"]), "capacity_ah": round(capacity_ah * soc / 100, 1), "full_capacity_ah": capacity_ah,
            "energy_kwh": round(capacity_ah * soc / 100 * pack_v / 1000, 2), "cycles": int(row["cycles"]), "stack": stack,
        }
        if not row["meter_gap"]:
            volts = row["meter_voltage_v"] if row["mains"] else 0.0
            grid_power = row["meter_grid_w"] if row["mains"] else 0.0
            counters = row["counters_kwh"]
            yield f"armor/electrical/{node_id}/state", {
                "kind": "electrical", "node_id": node_id, "timestamp_ms": timestamp, "switching_enabled": False,
                "channels": [
                    {"id": "grid", "domain": "ac", "label": "Grid input", "voltage_v": round(volts, 1), "current_a": round(grid_power / volts, 3) if volts else 0.0, "power_w": round(grid_power, 1),
                     "energy_kwh": round(counters["import"], 3), "frequency_hz": 50.0 if row["mains"] else 0.0, "state": "closed" if row["mains"] else "open", "alarm": False},
                    {"id": "house", "domain": "ac", "label": "House", "voltage_v": round(volts, 1), "current_a": round(max(0.0, row["meter_house_w"]) / volts, 3) if volts else 0.0,
                     "power_w": round(max(0.0, row["meter_house_w"]), 1), "energy_kwh": round(counters["load"], 3), "alarm": False},
                    {"id": "dc-bus", "domain": "dc", "label": "Battery bus", "voltage_v": pack_v, "current_a": round(current, 2), "power_w": round(row["charge_w"] - row["discharge_w"], 1),
                     "energy_kwh": round(counters["charge"] + counters["discharge"], 3), "alarm": False},
                ],
            }
