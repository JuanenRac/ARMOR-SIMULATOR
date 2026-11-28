"""What a battery emulated over CAN would tell an inverter: the frames of the Pylontech low-voltage CAN protocol, built from the state of a bank. SIMULATION ONLY.

Nothing here opens a CAN interface or sends anything: it turns a state into the bytes of the frames and prints them. See docs/CAN_BATTERY_EMULATION.md for the design and for what a real
gateway would still need. The layouts follow the public GPL-3 project ArminJo/JK-BMSToPylontechCAN; no inverter has been driven with them.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from dataclasses import dataclass, fields
from pathlib import Path

BITRATE = 500_000
PERIOD_S = 1.0
MAX_AGE_S = 10.0

LIMITS_ID, SOC_ID, VALUES_ID, ALARMS_ID, REQUEST_ID, MAKER_ID = 0x351, 0x355, 0x356, 0x359, 0x35C, 0x35E

# the flags of 0x359: (byte of protections, byte of warnings) share the same bit of their byte
_FIRST_BITS = {"cell_high_v": 0x02, "cell_low_v": 0x04, "temperature_high": 0x08, "temperature_low": 0x10, "discharge_over_current": 0x80}
_SECOND_BITS = {"charge_over_current": 0x01, "system": 0x80}


@dataclass(frozen=True)
class Bank:
    """The state of a battery bank as the gateway knows it. Currents are positive amperes; `current_a` is positive while charging."""

    voltage_v: float
    current_a: float
    temperature_c: float
    soc_percent: float
    soh_percent: float
    modules: int
    charge_voltage_v: float
    discharge_voltage_v: float
    max_charge_a: float
    max_discharge_a: float
    age_s: float = 0.0
    protections: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class Policy:
    """The caution of the emulated battery. Every figure only ever lowers what the bank itself allows."""

    taper_from_soc: float = 80.0
    taper_to_share: float = 0.2
    charge_min_c: float = 0.0
    charge_max_c: float = 50.0
    discharge_min_c: float = -10.0
    discharge_max_c: float = 55.0
    discharge_stop_soc: float = 10.0
    discharge_resume_soc: float = 15.0
    force_charge_soc: float = 5.0


@dataclass(frozen=True)
class Order:
    charge_a: float
    discharge_a: float
    charge_enable: bool
    discharge_enable: bool
    force_charge: bool


def _usable(bank: Bank) -> bool:
    numbers = [getattr(bank, f.name) for f in fields(bank) if f.name not in ("protections", "warnings")]
    return (all(math.isfinite(float(n)) for n in numbers) and 0 <= bank.age_s <= MAX_AGE_S and bank.modules >= 1 and 0 < bank.discharge_voltage_v < bank.charge_voltage_v <= 1000
            and 0 <= bank.soc_percent <= 100 and bank.max_charge_a >= 0 and bank.max_discharge_a >= 0)


def decide(bank: Bank, policy: Policy | None = None, discharge_was_stopped: bool = False) -> Order:
    """What the inverter may do. Old or impossible data, or any fault of the electronics, closes both directions."""
    policy = policy or Policy()
    if not _usable(bank) or "system" in bank.protections:
        return Order(0.0, 0.0, False, False, False)
    protections = set(bank.protections)
    charge = bank.max_charge_a
    if bank.soc_percent > policy.taper_from_soc and policy.taper_from_soc < 100:
        way = (bank.soc_percent - policy.taper_from_soc) / (100 - policy.taper_from_soc)
        charge *= 1 - way * (1 - policy.taper_to_share)
    charge_enable = (policy.charge_min_c <= bank.temperature_c <= policy.charge_max_c and bank.voltage_v < bank.charge_voltage_v
                     and not protections & {"cell_high_v", "temperature_high", "temperature_low", "charge_over_current"})
    floor = policy.discharge_resume_soc if discharge_was_stopped else policy.discharge_stop_soc
    discharge_enable = (policy.discharge_min_c <= bank.temperature_c <= policy.discharge_max_c and bank.voltage_v > bank.discharge_voltage_v and bank.soc_percent > floor
                        and not protections & {"cell_low_v", "temperature_high", "temperature_low", "discharge_over_current"})
    return Order(charge if charge_enable else 0.0, bank.max_discharge_a if discharge_enable else 0.0, charge_enable, discharge_enable,
                 charge_enable and bank.soc_percent <= policy.force_charge_soc)


def _tenth(value: float, lowest: int, highest: int) -> int:
    return max(lowest, min(highest, round(value * 10)))


def _flags(names: tuple[str, ...]) -> tuple[int, int]:
    return sum(bit for name, bit in _FIRST_BITS.items() if name in names), sum(bit for name, bit in _SECOND_BITS.items() if name in names)


def frames(bank: Bank, order: Order) -> list[tuple[int, bytes]]:
    """The frames of one period, little-endian. With unusable data only the closed limits, the alarm of the system and the maker are said: no figure is made up."""
    maker = (MAKER_ID, b"PYLON   ")
    if not _usable(bank):
        return [(LIMITS_ID, struct.pack("<HhhH", 0, 0, 0, 0)), (ALARMS_ID, bytes([0, 0x80, 0, 0, 0, ord("P"), ord("N")])), (REQUEST_ID, bytes([0, 0])), maker]
    first, second = _flags(bank.protections)
    warn_first, warn_second = _flags(bank.warnings)
    request = (0x80 if order.charge_enable else 0) | (0x40 if order.discharge_enable else 0) | (0x20 if order.force_charge else 0)
    return [
        (LIMITS_ID, struct.pack("<HhhH", _tenth(bank.charge_voltage_v, 0, 65535), _tenth(order.charge_a, 0, 32767), _tenth(order.discharge_a, 0, 32767),
                                _tenth(bank.discharge_voltage_v, 0, 65535))),
        (SOC_ID, struct.pack("<HH", round(bank.soc_percent), max(0, min(100, round(bank.soh_percent))))),
        (VALUES_ID, struct.pack("<hhh", max(-32768, min(32767, round(bank.voltage_v * 100))), _tenth(bank.current_a, -32768, 32767), _tenth(bank.temperature_c, -32768, 32767))),
        (ALARMS_ID, bytes([first, second, warn_first, warn_second, min(255, bank.modules), ord("P"), ord("N")])),
        (REQUEST_ID, bytes([request, 0])),
        maker,
    ]


def bank_from(document: object) -> Bank:
    """A bank read from a JSON object: unknown members and wrong types are refused."""
    if not isinstance(document, dict):
        raise ValueError("the state must be a JSON object")
    known = {f.name for f in fields(Bank)}
    unknown = sorted(set(document) - known)
    if unknown:
        raise ValueError("unknown member: " + ", ".join(unknown))
    values: dict[str, object] = {}
    for name, value in document.items():
        if name in ("protections", "warnings"):
            if not isinstance(value, list) or any(item not in _FIRST_BITS and item not in _SECOND_BITS for item in value):
                raise ValueError(f"{name} must be a list of known names")
            values[name] = tuple(value)
        elif isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name} must be a number")
        else:
            values[name] = value
    try:
        return Bank(**values)  # type: ignore[arg-type]
    except TypeError as error:
        raise ValueError(str(error)) from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print the CAN frames an emulated battery would say. Simulation only: nothing is sent.")
    parser.add_argument("state", type=Path, help="a JSON file with the state of the bank")
    args = parser.parse_args(argv)
    try:
        bank = bank_from(json.loads(args.state.read_text(encoding="utf-8-sig")))
    except (OSError, ValueError) as error:
        print(f"the state cannot be read: {error}", file=sys.stderr)
        return 2
    order = decide(bank)
    for identifier, data in frames(bank, order):
        print(f"(simulated) {identifier:03X} [{len(data)}] {data.hex(' ').upper()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
