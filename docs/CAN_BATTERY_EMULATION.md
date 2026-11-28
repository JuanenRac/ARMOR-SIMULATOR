# Battery emulated over CAN: design and simulation

**State: design and a simulator only.** No CAN interface is opened, nothing is transmitted and no inverter has ever received a frame from A.R.M.O.R.

## Purpose

A bank that A.R.M.O.R. reads (for example over a battery console or RS485) but that the inverter cannot talk to could be presented to the inverter as one Pylontech low-voltage battery over
CAN (500 kbit/s, one burst of frames per second). `armor_simulator.pylon_can` turns a state of the bank into those frames, so that the rules can be argued and tested before any wiring
exists.

```powershell
python -m armor_simulator.pylon_can bank.json
```

```json
{"voltage_v": 52.28, "current_a": 0.4, "temperature_c": 22, "soc_percent": 60, "soh_percent": 100, "modules": 2,
 "charge_voltage_v": 55.2, "discharge_voltage_v": 48.0, "max_charge_a": 50, "max_discharge_a": 80}
```

## Frames

| Id | Bytes | Content (little-endian) |
| --- | --- | --- |
| `0x351` | 8 | charge voltage (0.1 V), charge current limit (0.1 A), discharge current limit (0.1 A), discharge voltage (0.1 V) |
| `0x355` | 4 | state of charge (%), state of health (%) |
| `0x356` | 6 | voltage (0.01 V), current (0.1 A, positive while charging), temperature (0.1 C) |
| `0x359` | 7 | protections (2 bytes), warnings (2 bytes), number of modules, `PN` |
| `0x35C` | 2 | `0x80` charge allowed, `0x40` discharge allowed, `0x20` charge now |
| `0x35E` | 8 | `PYLON` padded with spaces |

The inverter sends `0x305` as a sign of life; the simulator does not model it. The layouts follow the public GPL-3 project
[ArminJo/JK-BMSToPylontechCAN](https://github.com/ArminJo/JK-BMSToPylontechCAN); they are not confirmed against an inverter here.

## Rules

* Only ever more careful than the bank: no rule raises a limit the bank gave.
* Data older than 10 s, impossible figures or a fault of the electronics: both limits are zero, both directions are closed and the system alarm is raised. No charge or voltage is made up.
* The charge current falls from 80 % of charge to a fifth of the limit at 100 %.
* Charging only between 0 and 50 C; discharging between -10 and 55 C.
* Discharge stops at 10 % of charge and starts again above 15 %; below 5 % the battery asks to be charged.

These figures are starting values for a simulation, not the maker's.

## What a real gateway would still need (not done, and not to be done without the owner deciding it)

* A board with a CAN transceiver, an isolated bus and its own power; none of the current nodes has one.
* A watchdog that stops sending frames when the data stops, so that the inverter falls back to its own safe behaviour (each model must be checked: some keep the last limits).
* The behaviour of the chosen inverter on every frame, on silence and on zero limits, measured with a test load and a protected battery before a real bank.
* The bank's own protections (BMS, fuses, breaker) staying in charge: an emulated battery is never a protection.
* A switch, off by default, to enable any transmission, and a record of what was sent.
