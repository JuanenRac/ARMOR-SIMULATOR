"""The buses of the field nodes, as bytes and text, with faults injected: what the real firmware code of each node is fed with in `tools/node_bench.py`.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

The other generators of this package emit what a node publishes. This one plays what a node RECEIVES from the equipment around it, so that the code that reads it (the
framing, the checks, the decoding) can be run, without any hardware, against well-formed input and against input that has been spoiled on purpose:

    ld2450      the serial stream of up to three HLK-LD2450 radar modules (ARMOR-NODE-RADAR): frames of 30 bytes, noise between them, frames cut short or with a bad tail,
                targets beyond what the module can measure, a target without resolution, a target at the origin, the stream handed over in pieces, silence
    pzem        the Modbus-RTU replies of the energy meters (ARMOR-NODE-ELECTRICAL): the replies of `meter_bus.py`, then a flipped bit, an exception, a short or a long reply,
                the reply of another meter, a reading no meter could give, silence
    pylontech   the text of the console of a battery stack (ARMOR-NODE-SOLAR): the `pwr` table and the `bat` table, with an absent module, a garbled row, no header, a cell
                out of range, cells out of order
    alarm-loop  the voltage of a wired alarm loop (ARMOR-NODE-ALARM) sample by sample, and a plain contact: closed, open, bouncing, noisy, cut, shorted, a converter that
                is still settling at power-up
    hmi-feed    the frames of the live channel that ARMOR-SERVER keeps open to the panel (ARMOR-NODE-HMI): summaries and everything that is not one

Every case carries what the node MUST answer, worked out here from the rules each firmware file documents (not by running the firmware), so a run is a comparison between
two separate statements of the same rules. Everything is a function of the seed: two runs are identical. Nothing here says how a real device behaves beyond what those
files already document; none of it has been compared with the real equipment.

The line the drivers read (one case per line, tab separated): `bus`, `id`, `arg`, `payload` (hex for bytes and text, plain for the loop). They answer one line per case:
`id`, tab, the answer as text. A case that was recorded can be played again later (`dump` and `load`).
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .meter_bus import BusConfig, Fault, MeterBus, default_config, with_crc

BUSES = ("ld2450", "pzem", "pylontech", "alarm-loop", "hmi-feed")
MAX_CASES_FILE = 64 * 1024 * 1024


class BusError(ValueError):
    """A recorded case file that is not understood, or a fault that does not exist."""


@dataclass(frozen=True)
class Case:
    bus: str
    id: str
    arg: str
    payload: str          # hex of the bytes (or of the text), or plain text for the alarm loop
    expect: str           # what the node must answer
    fault: str = "none"

    def line(self) -> str:
        return "\t".join((self.bus, self.id, self.arg or "-", self.payload or "-"))


FAULTS: dict[str, tuple[str, ...]] = {
    "ld2450": ("none", "noise", "truncate", "bad-tail", "out-of-range", "no-resolution", "origin", "chunks", "silence"),
    "pzem": ("none", "corrupt", "exception", "silent", "short", "long", "other-address", "implausible"),
    "pylontech": ("none", "absent", "garbled-row", "no-header", "prompt", "cell-out-of-range", "cells-out-of-order"),
    "alarm-loop": ("none", "bounce", "noise", "power-up-glitch", "cut", "short", "slow-open"),
    "hmi-feed": ("none", "wrong-type", "not-json", "truncated", "bad-mode", "no-blocks", "oversize", "silent-code", "many-alarms", "heartbeat-limits"),
}


def _check_fault(bus: str, fault: str) -> None:
    if fault not in FAULTS[bus]:
        raise BusError(f"{bus} has no fault '{fault}' (one of {', '.join(FAULTS[bus])})")


# ---- HLK-LD2450 ------------------------------------------------------------------------------------------------------------------------------------------------------

LD_HEADER, LD_TAIL = bytes((0xAA, 0xFF, 0x03, 0x00)), bytes((0x55, 0xCC))
LD_MAX_ABS_X, LD_MIN_Y, LD_MAX_Y, LD_MAX_SPEED = 6500, -500, 8500, 1000      # what the module can report; a value beyond these is a garbled frame


def _signed(value: int) -> int:
    magnitude = abs(value)
    if magnitude > 0x7FFF:
        raise BusError("a value that does not fit")
    return (0x8000 | magnitude) if value >= 0 else magnitude


def _target_bytes(x: int, y: int, speed: int, resolution: int) -> bytes:
    return b"".join(v.to_bytes(2, "little") for v in (_signed(x), _signed(y), _signed(speed), resolution))


def _ld_frame(targets: list[tuple[int, int, int, int] | None]) -> bytes:
    body = b"".join(_target_bytes(*t) if t else bytes(8) for t in (targets + [None] * 3)[:3])
    return LD_HEADER + body + LD_TAIL


def _ld_reject(x: int, y: int, speed: int, resolution: int) -> str | None:
    if resolution == 0:
        return "no-resolution"
    if abs(x) > LD_MAX_ABS_X or y < LD_MIN_Y or y > LD_MAX_Y or abs(speed) > LD_MAX_SPEED:
        return "out-of-range"
    if x == 0 and y == 0:
        return "origin"
    return None


def _ld_expect(targets: list[tuple[int, int, int, int] | None]) -> str:
    """The answer for one frame: the tracks (slot, x, y, speed in mm/s) and the targets that were refused."""
    tracks, refused = [], []
    for slot, target in enumerate((targets + [None] * 3)[:3], 1):
        if not target:
            continue
        reason = _ld_reject(*target)
        if reason:
            refused.append(f"{slot}:{reason}")
        else:
            tracks.append(f"{slot}:{target[0]}:{target[1]}:{max(-32768, min(32767, target[2] * 10))}")
    return f"tracks={','.join(tracks) or '-'} refused={','.join(refused) or '-'}"


def ld2450(seed: int, fault: str = "none", frames: int = 40, every: int = 4) -> Case:
    """A walker crossing the room (and a second one for a while): `frames` frames at 10 Hz, every `every`-th one spoiled by the fault."""
    _check_fault("ld2450", fault)
    rng = random.Random(seed)
    stream = bytearray()
    expected: list[str] = []
    cuts: list[int] = []
    for n in range(frames):
        first = (-1800 + 60 * n + rng.randint(-8, 8), 1500 + 70 * n + rng.randint(-8, 8), rng.randint(-120, 120), 360)
        second = (2200 - 45 * n, 4200 - 30 * n, -rng.randint(10, 90), 360) if 10 <= n < 30 else None
        targets: list[tuple[int, int, int, int] | None] = [first, second]
        spoiled = fault != "none" and n % every == every - 1
        if spoiled and fault == "out-of-range":
            targets[0] = (LD_MAX_ABS_X + 400 + n, first[1], first[2], 360)
        elif spoiled and fault == "no-resolution":
            targets[0] = (first[0], first[1], first[2], 0)
        elif spoiled and fault == "origin":
            targets[0] = (0, 0, 0, 360)
        frame = _ld_frame(targets)
        lost = False
        if spoiled and fault == "truncate":
            frame, lost = frame[: rng.randint(6, 28)], True
        elif spoiled and fault == "bad-tail":
            frame, lost = frame[:-2] + bytes(2), True
        if spoiled and fault == "noise":
            stream += bytes(rng.choice([b for b in range(256) if b != 0xAA]) for _ in range(rng.randint(1, 20)))
        if fault == "silence":
            continue
        stream += frame
        if not lost:
            expected.append(_ld_expect(targets))
        cuts.append(len(stream))
    if fault == "chunks":
        pieces, at = [], 0
        while at < len(stream):
            size = rng.randint(1, 37)
            pieces.append(bytes(stream[at:at + size]).hex())
            at += size
        payload = ",".join(pieces)
    else:
        payload = bytes(stream).hex()
    return Case("ld2450", f"ld2450-{fault}", "-", payload or "-", f"frames={len(expected)} " + "|".join(expected) if expected else "frames=0", fault)


# ---- PZEM (Modbus-RTU) -----------------------------------------------------------------------------------------------------------------------------------------------

PZEM_RESULTS = ("ok", "too_short", "crc", "address", "exception", "function", "length", "range")


def _pzem_values(model: str, reply: bytes) -> str:
    registers = [int.from_bytes(reply[3 + 2 * i:5 + 2 * i], "big") for i in range((len(reply) - 5) // 2)]
    if model == "pzem-004t":
        voltage, current = registers[0] / 10.0, (registers[1] | registers[2] << 16) / 1000.0
        power, energy = (registers[3] | registers[4] << 16) / 10.0, (registers[5] | registers[6] << 16) / 1000.0
        extra = f" hz={registers[7] / 10.0:.1f} pf={registers[8] / 100.0:.2f} alarm={int(registers[9] == 0xFFFF)}"
    else:
        voltage, current = registers[0] / 100.0, registers[1] / 100.0
        power, energy = (registers[2] | registers[3] << 16) / 10.0, (registers[4] | registers[5] << 16) / 1000.0
        extra = f" alarm={int(registers[6] == 0xFFFF or registers[7] == 0xFFFF)}"
    return f"ok v={voltage:.2f} i={current:.3f} p={power:.1f} e={energy:.3f}{extra}"


def pzem(seed: int, fault: str = "none", requests: int = 12) -> Case:
    """The replies of the three default meters to the read of their measurements, a different sample of the day each time, some of them spoiled by the fault."""
    _check_fault("pzem", fault)
    rng = random.Random(seed)
    config = default_config()
    if fault in ("corrupt", "exception", "silent"):
        config = BusConfig(config.meters, tuple(Fault(fault, meter.address, 3) for meter in config.meters), config.node_id, seed, config.speed)
    sample = {"n": rng.randint(0, 5000)}
    bus = MeterBus(config=config, sample=lambda: sample["n"])
    sent, expected = [], []
    for n in range(requests):
        meter = config.meters[n % len(config.meters)]
        sample["n"] += rng.randint(20, 400)
        count = 10 if meter.model == "pzem-004t" else 8
        reply = bus.answer(with_crc(bytes((meter.address, 0x04, 0, 0, 0, count))))
        spoil = fault in ("short", "long", "other-address", "implausible") and n % 2 == 1
        if spoil and reply is not None:
            if fault == "short":
                reply = reply[: rng.randint(3, len(reply) - 2)]
            elif fault == "long":
                reply = reply + b"\x00"
            elif fault == "other-address":
                other = next((m for m in config.meters if m.address != meter.address and m.model == meter.model), None)
                if other:
                    reply = bus.answer(with_crc(bytes((other.address, 0x04, 0, 0, 0, count))))
            elif fault == "implausible" and meter.model == "pzem-004t":
                reply = with_crc(bytes((meter.address, 0x04, 20, 0xFF, 0xFF)) + reply[5:-2])    # 6553.5 V with a CRC that is right: only the plausibility check can refuse it
        if reply is None or len(reply) < 5:
            answer = "too_short"
        elif reply[1] & 0x80:
            answer = "exception" if _crc_fits(reply) else "crc"
        elif len(reply) != 5 + 2 * count:
            answer = "too_short" if len(reply) < 5 + 2 * count else "length"
        elif not _crc_fits(reply):
            answer = "crc"
        elif reply[0] != meter.address:
            answer = "address"
        else:
            answer = _pzem_values(meter.model, reply)
            if answer.startswith("ok v=") and (float(answer.split()[1][2:]) > 1000):
                answer = "range"
        sent.append(f"{meter.model}:{meter.address}:{(reply or b'').hex() or '-'}")
        expected.append(answer)
    return Case("pzem", f"pzem-{fault}", "-", "|".join(sent).encode().hex(), "|".join(expected), fault)


def _crc_fits(reply: bytes) -> bool:
    from .meter_bus import crc16
    return crc16(reply[:-2]) == int.from_bytes(reply[-2:], "little")


# ---- the console of a Pylontech stack --------------------------------------------------------------------------------------------------------------------------------

PWR_HEADER = "Power Volt Curr Tempr Tlow Thigh Vlow Vhigh Base.St Volt.St Curr.St Temp.St Coulomb Time B.V.St B.T.St"


def _pwr_row(number: int, rng: random.Random) -> tuple[str, dict]:
    volt, curr, temp, soc = rng.randint(49800, 52900), rng.randint(-9000, 9000), rng.randint(17000, 31000), rng.randint(5, 100)
    state = "Charge" if curr > 300 else "Dischg" if curr < -300 else "Idle"
    row = (f"{number} {volt} {curr} {temp} {temp - 1500} {temp + 1000} {rng.randint(3300, 3340)} {rng.randint(3341, 3380)} {state} Normal Normal Normal {soc}% "
           f"2026-01-{rng.randint(1, 28):02d} {rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:{rng.randint(0, 59):02d} Normal Normal")
    return row, {"number": number, "volt": volt, "curr": curr, "temp": temp, "soc": soc, "state": state}


def _pwr_text(rows: list[str]) -> str:
    return "\n".join(rows) + "\n"


def pylontech(seed: int, fault: str = "none", modules: int = 4) -> Case:
    """The `pwr` table of a stack of `modules` modules (and the `bat` table of module 1) with the fault applied."""
    _check_fault("pylontech", fault)
    rng = random.Random(seed)
    lines = ["@", PWR_HEADER]
    expected: list[str] = []
    for number in range(1, modules + 1):
        row, values = _pwr_row(number, rng)
        if fault == "absent" and number == 3:
            lines.append(f"{number} Absent")
            expected.append(f"{number}:absent")
            continue
        if fault == "garbled-row" and number == 2:
            lines.append(f"{number} 5x1?0 -- ~~ zz Charge Normal")
            continue
        lines.append(row)
        expected.append(f"{number}:{values['volt'] / 1000.0:.3f}:{values['curr'] / 1000.0:.3f}:{values['temp'] / 1000.0:.3f}:{values['soc']}:{values['state']}")
    if fault == "no-header":
        lines.remove(PWR_HEADER)
    if fault == "prompt":
        lines += ["Command completed successfully", "$$", "pylon_debug>"]
    pwr = _pwr_text(lines)
    cells = [rng.randint(3290, 3345) for _ in range(15)]
    bat_lines = ["@", "Battery - Volt   - Curr - Tempr   - Base State - Volt. State - Curr. State - Temp.     - State - Coulomb"]
    for index, mv in enumerate(cells):
        shown = mv
        if fault == "cell-out-of-range" and index == 6:
            shown = 12000
        index_shown = index + 1 if fault == "cells-out-of-order" and index == 4 else index
        bat_lines.append(f"{index_shown} {shown} -236 18000 Dischg Normal Normal Normal 68% 33424 mAH")
    bat_lines += ["Command completed successfully", "$$", "pylon_debug>"]
    bat = _pwr_text(bat_lines)
    refused = fault in ("cell-out-of-range", "cells-out-of-order")
    bat_expect = "cells=0" if refused else f"cells={len(cells)} v={','.join(f'{c / 1000.0:.3f}' for c in cells)}"
    payload = pwr.encode().hex() + "," + bat.encode().hex()
    return Case("pylontech", f"pylontech-{fault}", "-", payload, f"pwr={len(expected)} {' '.join(expected)} | {bat_expect}".replace("  ", " "), fault)


# ---- a wired alarm loop ----------------------------------------------------------------------------------------------------------------------------------------------

LOOP_LIMITS = (400.0, 1200.0, 2400.0)      # short below, normal below, triggered below (millivolts): settings of the installer, here the defaults of the firmware
LOOP_HOLD_MS = 200


def _loop_class(mv: float) -> str:
    if mv < LOOP_LIMITS[0]:
        return "tamper"
    if mv < LOOP_LIMITS[1]:
        return "normal"
    if mv < LOOP_LIMITS[2]:
        return "triggered"
    return "tamper"


def _loop_debounce(samples: list[tuple[int, int]]) -> list[str]:
    """The rule of the firmware's debouncer, as it documents it: a reading counts only after it has held for 200 ms, and the very first reading reads 'normal'."""
    result, stable, candidate, since, started = [], "normal", "normal", 0, False
    for now, mv in samples:
        reading = _loop_class(mv)
        if not started:
            started, stable, candidate, since = True, "normal", reading, now
        else:
            if reading != candidate:
                candidate, since = reading, now
            if candidate != stable and now - since >= LOOP_HOLD_MS:
                stable = candidate
        result.append(stable)
    return result


def alarm_loop(seed: int, fault: str = "none", seconds: int = 12) -> Case:
    """A door loop sampled every 50 ms: closed, opened for a while, closed again; the fault changes what the wire does."""
    _check_fault("alarm-loop", fault)
    rng = random.Random(seed)
    samples: list[tuple[int, int]] = []
    for n in range(seconds * 20):
        now = n * 50
        level = 800
        if 3000 <= now < 5000:
            level = 1800                                           # the door is open
        if fault == "bounce" and 7000 <= now < 7300 and (now // 50) % 2 == 0:
            level = 1800                                           # a contact that flickers for 300 ms: it must not count
        elif fault == "noise":
            level += rng.randint(-120, 120)
        elif fault == "power-up-glitch" and now < 150:
            level = 2900                                           # a converter still settling
        elif fault == "cut" and now >= 9000:
            level = 2950
        elif fault == "short" and now >= 9000:
            level = 60
        elif fault == "slow-open" and 3000 <= now < 3600:
            level = 1800 if (now // 50) % 3 == 0 else 800
        samples.append((now, level))
    states = _loop_debounce(samples)
    payload = ",".join(f"{t}:{mv}" for t, mv in samples)
    return Case("alarm-loop", f"alarm-loop-{fault}", ",".join(str(int(x)) for x in LOOP_LIMITS), payload, ",".join(states), fault)


# ---- the live channel of the panel -----------------------------------------------------------------------------------------------------------------------------------

LIVE_MAX_BYTES = 8 * 1024
HEARTBEAT_LOW, HEARTBEAT_HIGH, HEARTBEAT_DEFAULT = 1000, 60000, 5000
SILENT_CODES = ("duress_disarm",)
SHOWN_ALARMS = 6


def _summary(rng: random.Random, mode: str, alarms: int, codes: tuple[str, ...] = ("intrusion", "tamper", "node_offline")) -> dict:
    items = [{"id": f"a{n}", "code": codes[n % len(codes)], "source_type": "alarm", "source_id": f"zone-{n}", "raised_at": "2026-01-05T10:00:00Z", "severity": "critical",
              "acknowledged": bool(n % 2)} for n in range(alarms)]
    return {"mode": mode, "revision": rng.randint(1, 900), "time_ms": 1_700_000_000_000 + rng.randint(0, 10**6), "nodes": {"online": rng.randint(1, 5), "total": 5},
            "alarms": {"active": alarms, "unacknowledged": sum(1 for i in items if not i["acknowledged"]), "items": items},
            "energy": {"reporting": True, "pv_w": rng.randint(0, 4000), "load_w": rng.randint(100, 2500), "soc_percent": rng.randint(5, 100), "battery_w": rng.randint(-2000, 2000)}}


def _live_expect(frame: dict) -> str:
    summary = frame["summary"]
    heartbeat = frame.get("heartbeat_ms", HEARTBEAT_DEFAULT)
    heartbeat = max(HEARTBEAT_LOW, min(HEARTBEAT_HIGH, heartbeat))
    items = summary["alarms"]["items"]
    active, unack, lines = summary["alarms"]["active"], summary["alarms"]["unacknowledged"], 0
    for item in items:
        if item["code"] in SILENT_CODES:
            active -= 1 if active > 0 else 0
            unack -= 1 if not item["acknowledged"] and unack > 0 else 0
        elif lines < SHOWN_ALARMS:
            lines += 1
    energy = 1 if "energy" in summary else 0
    return (f"ok mode={summary['mode']} nodes={summary['nodes']['online']}/{summary['nodes']['total']} active={active} unack={unack} lines={lines} hb={heartbeat} "
            f"energy={energy}")


def hmi_feed(seed: int, fault: str = "none", frames: int = 9) -> Case:
    """The frames of the live channel: a summary after another, every third one spoiled by the fault; the answer to each is what the panel keeps of it."""
    _check_fault("hmi-feed", fault)
    rng = random.Random(seed)
    texts, expected = [], []
    for n in range(frames):
        mode = "armed" if n % 4 < 2 else "disarmed"
        alarms = rng.randint(0, 3)
        codes: tuple[str, ...] = ("intrusion", "tamper", "node_offline")
        if fault == "silent-code":
            codes = ("duress_disarm", "intrusion")
            alarms = max(alarms, 2)
        if fault == "many-alarms":
            alarms = 9
        frame: dict = {"type": "summary", "heartbeat_ms": 5000, "summary": _summary(rng, mode, alarms, codes)}
        if fault == "heartbeat-limits":
            frame["heartbeat_ms"] = (200, 90000, 5000)[n % 3]
        text = json.dumps(frame, separators=(",", ":"))
        spoiled = fault != "none" and n % 3 == 2
        answer = _live_expect(frame) if not (spoiled and fault in ("wrong-type", "not-json", "truncated", "bad-mode", "no-blocks", "oversize")) else "rejected"
        if spoiled and fault == "wrong-type":
            frame["type"] = "ping"
            text = json.dumps(frame, separators=(",", ":"))
        elif spoiled and fault == "not-json":
            text = "{this is not json"
        elif spoiled and fault == "truncated":
            text = text[: len(text) // 2]
        elif spoiled and fault == "bad-mode":
            frame["summary"]["mode"] = "maybe"
            text = json.dumps(frame, separators=(",", ":"))
        elif spoiled and fault == "no-blocks":
            del frame["summary"]["nodes"]
            text = json.dumps(frame, separators=(",", ":"))
        elif spoiled and fault == "oversize":
            text = text + " " * (LIVE_MAX_BYTES + 1 - len(text) % LIVE_MAX_BYTES)
        texts.append(text)
        expected.append(answer)
    payload = ",".join(t.encode().hex() for t in texts)
    return Case("hmi-feed", f"hmi-feed-{fault}", "-", payload, "|".join(expected), fault)


GENERATORS: dict[str, Callable[..., Case]] = {"ld2450": ld2450, "pzem": pzem, "pylontech": pylontech, "alarm-loop": alarm_loop, "hmi-feed": hmi_feed}


def cases_for(bus: str, seed: int = 1, faults: tuple[str, ...] | None = None) -> list[Case]:
    """The cases of one bus: every fault it knows (or the ones asked for), each with a seed of its own derived from `seed`."""
    if bus not in GENERATORS:
        raise BusError(f"unknown bus '{bus}' (one of {', '.join(BUSES)})")
    chosen = faults or FAULTS[bus]
    return [GENERATORS[bus](seed * 1000 + index, fault) for index, fault in enumerate(chosen)]


def dump(cases: list[Case], path: Path) -> None:
    """Writes the cases as JSON lines; an existing file is never overwritten."""
    try:
        with path.open("x", encoding="utf-8", newline="\n") as out:
            for case in cases:
                out.write(json.dumps(case.__dict__, sort_keys=True, separators=(",", ":")) + "\n")
    except FileExistsError:
        raise BusError(f"{path} already exists: give another name, nothing is overwritten") from None


def load(path: Path) -> list[Case]:
    if path.stat().st_size > MAX_CASES_FILE:
        raise BusError(f"{path.name} is too big")
    cases = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            case = Case(**record)
        except (ValueError, TypeError) as error:
            raise BusError(f"line {number}: not a case ({error})") from error
        if case.bus not in BUSES or not all(isinstance(v, str) for v in record.values()):
            raise BusError(f"line {number}: not a case of a known bus")
        cases.append(case)
    if not cases:
        raise BusError(f"{path.name} has no cases")
    return cases
