"""The serial line of the energy meters, over TCP: Modbus-RTU frames answered like a PZEM-004T v3 (AC) and a PZEM-017 (DC) answer them.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

The other generators of this package emit what a NODE publishes. This one plays the METERS: it listens on a TCP port, reads the Modbus-RTU requests an electrical node
sends on its serial line (bridge the line to the port with a serial-over-TCP adapter, or point a host test at it) and answers with the registers of the meter at that
address, so the code that reads the meters (CRC, frames, addresses, timeouts) can be tried without a meter. The readings are the ones of `electrical.py`, so a run
of this bus and a run of `--electrical` tell the same story.

READ ONLY, like the node: the reads of the input registers (0x04) and of the holding registers (0x03) are answered; every request that writes (0x06, 0x10 and the
maker's reset of the energy counter, 0x42) is refused with the exception "illegal function" and counted, and nothing the bus holds changes. A frame whose CRC does not fit
is not answered at all, as a real meter does. The register map is the one of the makers' public description, as written in ARMOR-NODE-ELECTRICAL; nothing here has been
compared with a real meter.

Every setting (the meters, their addresses, the thresholds, the faults) lives in a JSON file (`docs/METER_BUS.md`); the defaults are the three meters of `electrical.py`.
"""

from __future__ import annotations

import json
import socket
import socketserver
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .electrical import electrical

SCHEMA = "armor-meter-bus/1"
MODELS = ("pzem-004t", "pzem-017")
FUNCTION_HOLDING, FUNCTION_INPUT = 0x03, 0x04
WRITE_FUNCTIONS = (0x06, 0x10, 0x42)
EXCEPTION_ILLEGAL_FUNCTION, EXCEPTION_ILLEGAL_ADDRESS = 0x01, 0x02
BROADCAST_ANY = 0xF8          # the address the meters answer to whatever their own
MAX_FILE_BYTES = 64 * 1024
MAX_METERS = 32
MAX_SPEED = 1000.0
FAULT_KINDS = ("silent", "corrupt", "exception")
SHUNT_CODES = {100: 0, 50: 1, 200: 2, 300: 3}
LOOPBACK = ("127.0.0.1", "::1", "localhost")


class MeterBusError(ValueError):
    """A bus file that is not understood, or an address that is not allowed."""


def crc16(data: bytes) -> int:
    """CRC-16/MODBUS: polynomial 0xA001 reflected, start 0xFFFF; sent low byte first."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def with_crc(frame: bytes) -> bytes:
    crc = crc16(frame)
    return frame + bytes((crc & 0xFF, crc >> 8))


@dataclass(frozen=True)
class Meter:
    address: int
    model: str                 # "pzem-004t" (AC) or "pzem-017" (DC)
    channel: str               # the channel of `electrical.py` whose readings it gives
    power_alarm_w: int = 2300                  # pzem-004t: the alarm threshold it keeps (1 W)
    high_voltage_v: float = 58.0               # pzem-017: the high and the low voltage alarm thresholds
    low_voltage_v: float = 44.0
    shunt_a: int = 100                         # pzem-017: 100, 50, 200 or 300


@dataclass(frozen=True)
class Fault:
    kind: str                  # silent: never answers; corrupt: every Nth reply has a flipped bit; exception: answers "illegal address"
    address: int               # the meter it strikes
    every: int = 1


@dataclass(frozen=True)
class BusConfig:
    meters: tuple[Meter, ...]
    faults: tuple[Fault, ...] = ()
    node_id: str = "simulator-1"
    seed: int = 0
    speed: float = 1.0         # samples of the day per real second


DEFAULT_METERS = (
    Meter(1, "pzem-004t", "grid"),
    Meter(2, "pzem-004t", "heater"),
    Meter(7, "pzem-017", "dc-bus", shunt_a=100),
)


def default_config() -> BusConfig:
    return BusConfig(DEFAULT_METERS)


def _int(value, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise MeterBusError(f"{name} must be a whole number from {low} to {high}")
    return value


def _number(value, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise MeterBusError(f"{name} must be a number from {low} to {high}")
    return float(value)


def parse_config(document: object) -> BusConfig:
    """A bus described in a JSON document, strictly: whatever is not understood refuses the whole file."""
    if not isinstance(document, dict):
        raise MeterBusError("the file must hold a JSON object")
    if document.get("schema") != SCHEMA:
        raise MeterBusError(f'"schema" must be "{SCHEMA}"')
    unknown = set(document) - {"schema", "node_id", "seed", "speed", "meters", "faults"}
    if unknown:
        raise MeterBusError(f"unknown field(s): {', '.join(sorted(unknown))}")
    meters_in = document.get("meters")
    if not isinstance(meters_in, list) or not 1 <= len(meters_in) <= MAX_METERS:
        raise MeterBusError(f'"meters" must be a list of 1 to {MAX_METERS} meters')
    meters: list[Meter] = []
    for number, item in enumerate(meters_in, start=1):
        if not isinstance(item, dict):
            raise MeterBusError(f"meter {number} must be an object")
        extra = set(item) - {"address", "model", "channel", "power_alarm_w", "high_voltage_v", "low_voltage_v", "shunt_a"}
        if extra:
            raise MeterBusError(f"meter {number}: unknown field(s): {', '.join(sorted(extra))}")
        model = item.get("model")
        if model not in MODELS:
            raise MeterBusError(f"meter {number}: \"model\" must be one of {', '.join(MODELS)}")
        channel = item.get("channel")
        if not isinstance(channel, str) or channel not in ("grid", "heater", "dc-bus"):
            raise MeterBusError(f"meter {number}: \"channel\" must be one of grid, heater, dc-bus")
        if (model == "pzem-017") != (channel == "dc-bus"):
            raise MeterBusError(f"meter {number}: the PZEM-017 reads the DC bus and the PZEM-004T the AC channels")
        shunt = _int(item.get("shunt_a", 100), f"meter {number}: shunt_a", 0, 1000)
        if shunt not in SHUNT_CODES:
            raise MeterBusError(f"meter {number}: shunt_a must be 50, 100, 200 or 300")
        meters.append(Meter(
            address=_int(item.get("address"), f"meter {number}: address", 1, 247), model=model, channel=channel,
            power_alarm_w=_int(item.get("power_alarm_w", 2300), f"meter {number}: power_alarm_w", 0, 22000),
            high_voltage_v=_number(item.get("high_voltage_v", 58.0), f"meter {number}: high_voltage_v", 0, 300),
            low_voltage_v=_number(item.get("low_voltage_v", 44.0), f"meter {number}: low_voltage_v", 0, 300), shunt_a=shunt))
    if len({m.address for m in meters}) != len(meters):
        raise MeterBusError("two meters cannot share an address")
    faults: list[Fault] = []
    faults_in = document.get("faults", [])
    if not isinstance(faults_in, list) or len(faults_in) > MAX_METERS * 3:
        raise MeterBusError('"faults" must be a list')
    for number, item in enumerate(faults_in, start=1):
        if not isinstance(item, dict) or set(item) - {"kind", "address", "every"}:
            raise MeterBusError(f"fault {number} must be an object with kind, address and every")
        if item.get("kind") not in FAULT_KINDS:
            raise MeterBusError(f"fault {number}: \"kind\" must be one of {', '.join(FAULT_KINDS)}")
        address = _int(item.get("address"), f"fault {number}: address", 1, 247)
        if address not in {m.address for m in meters}:
            raise MeterBusError(f"fault {number}: no meter has the address {address}")
        faults.append(Fault(item["kind"], address, _int(item.get("every", 1), f"fault {number}: every", 1, 1_000_000)))
    node_id = document.get("node_id", "simulator-1")
    if not isinstance(node_id, str) or not node_id or len(node_id) > 64:
        raise MeterBusError('"node_id" must be a text of 1 to 64 characters')
    return BusConfig(tuple(meters), tuple(faults), node_id, _int(document.get("seed", 0), "seed", 0, 2**31 - 1), _number(document.get("speed", 1.0), "speed", 0.0, MAX_SPEED))


def load_config(path: Path | None) -> BusConfig:
    if path is None:
        return default_config()
    try:
        raw = Path(path).read_bytes()
    except OSError as error:
        raise MeterBusError(f"cannot read {path}: {error.strerror or error}") from None
    if len(raw) > MAX_FILE_BYTES:
        raise MeterBusError(f"the file is larger than {MAX_FILE_BYTES} bytes")
    try:
        return parse_config(json.loads(raw.decode("utf-8"), parse_constant=_refuse_constant))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MeterBusError(f"the file is not valid JSON: {error}") from None


def _refuse_constant(name: str):
    raise MeterBusError(f"{name} is not a JSON value")


def _words32(value: float) -> list[int]:
    """A 32-bit value as two registers, the low word first (the order of the PZEM)."""
    value = max(0, min(int(round(value)), 0xFFFFFFFF))
    return [value & 0xFFFF, value >> 16]


def input_registers(meter: Meter, channel: dict) -> list[int]:
    """The measurements of a channel as the registers the meter would give."""
    voltage, current, power, energy_kwh = (float(channel.get(k, 0.0)) for k in ("voltage_v", "current_a", "power_w", "energy_kwh"))
    if meter.model == "pzem-004t":
        alarm = 0xFFFF if channel.get("alarm") else 0
        return [max(0, min(round(voltage * 10), 0xFFFF)), *_words32(abs(current) * 1000), *_words32(power * 10), *_words32(energy_kwh * 1000),
                max(0, min(round(float(channel.get("frequency_hz", 0.0)) * 10), 0xFFFF)), max(0, min(round(float(channel.get("power_factor", 0.0)) * 100), 0xFFFF)), alarm]
    high = 0xFFFF if voltage > meter.high_voltage_v else 0      # the shunt gives no sign: a battery that gives or takes reads the same
    low = 0xFFFF if voltage < meter.low_voltage_v else 0
    return [max(0, min(round(voltage * 100), 0xFFFF)), max(0, min(round(abs(current) * 100), 0xFFFF)), *_words32(abs(power) * 10), *_words32(energy_kwh * 1000), high, low]


def holding_registers(meter: Meter) -> tuple[int, list[int]]:
    """The first holding register and the settings the meter keeps."""
    if meter.model == "pzem-004t":
        return 0x0001, [meter.power_alarm_w, meter.address]
    return 0x0000, [round(meter.high_voltage_v * 100), round(meter.low_voltage_v * 100), meter.address, SHUNT_CODES[meter.shunt_a]]


@dataclass
class MeterBus:
    """The meters on one line: `answer` takes a request frame and gives the reply (or None, when a real meter would stay silent)."""

    config: BusConfig = field(default_factory=default_config)
    sample: Callable[[], int] = lambda: 0
    requests: int = 0
    answered: int = 0
    silent: int = 0
    refused_writes: int = 0
    bad_crc: int = 0
    _per_fault: dict = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _meter_for(self, address: int) -> Meter | None:
        if address == BROADCAST_ANY:
            return self.config.meters[0]
        return next((m for m in self.config.meters if m.address == address), None)

    def _channel(self, meter: Meter) -> dict:
        message = electrical(self.config.node_id, self.sample(), self.config.seed)
        return next(c for c in message["channels"] if c["id"] == meter.channel)

    def answer(self, request: bytes) -> bytes | None:
        with self._lock:
            self.requests += 1
            reply = self._answer(bytes(request))
            if reply is None:
                self.silent += 1
            else:
                self.answered += 1
            return reply

    def _answer(self, request: bytes) -> bytes | None:
        if len(request) < 4 or crc16(request[:-2]) != int.from_bytes(request[-2:], "little"):
            self.bad_crc += 1
            return None                                  # a meter does not answer what it cannot trust
        address, function = request[0], request[1]
        meter = self._meter_for(address)
        if meter is None:
            return None                                  # not for any meter on this line
        fault = self._fault(meter)
        if fault and fault.kind == "silent":
            return None
        if function in WRITE_FUNCTIONS:
            self.refused_writes += 1                     # nothing here can be written; the meter is told so
            return self._exception(address, function, EXCEPTION_ILLEGAL_FUNCTION)
        if function not in (FUNCTION_HOLDING, FUNCTION_INPUT):
            return self._exception(address, function, EXCEPTION_ILLEGAL_FUNCTION)
        if len(request) != 8:
            return None
        if fault and fault.kind == "exception":
            return self._exception(address, function, EXCEPTION_ILLEGAL_ADDRESS)
        first, count = int.from_bytes(request[2:4], "big"), int.from_bytes(request[4:6], "big")
        if function == FUNCTION_INPUT:
            registers, base = input_registers(meter, self._channel(meter)), 0
        else:
            base, registers = holding_registers(meter)
        if count < 1 or first < base or first + count > base + len(registers):
            return self._exception(address, function, EXCEPTION_ILLEGAL_ADDRESS)
        chosen = registers[first - base:first - base + count]
        body = bytes((address, function, 2 * len(chosen))) + b"".join(r.to_bytes(2, "big") for r in chosen)
        reply = with_crc(body)
        if fault and fault.kind == "corrupt":
            reply = reply[:3] + bytes((reply[3] ^ 0x01,)) + reply[4:]       # one bit flipped after the CRC was made
        return reply

    def _fault(self, meter: Meter) -> Fault | None:
        """The fault that strikes this request (counted per fault: every Nth request to the meter)."""
        for index, fault in enumerate(self.config.faults):
            if fault.address != meter.address:
                continue
            seen = self._per_fault.get(index, 0) + 1
            self._per_fault[index] = seen
            if seen % fault.every == 0:
                return fault
        return None

    @staticmethod
    def _exception(address: int, function: int, code: int) -> bytes:
        return with_crc(bytes((address, function | 0x80, code)))


def request_length(buffer: bytes) -> int | None:
    """How long the request at the start of the buffer is, once its function is known (None while it cannot be told)."""
    if len(buffer) < 2:
        return None
    function = buffer[1]
    if function in (FUNCTION_HOLDING, FUNCTION_INPUT, 0x06, 0x42):
        return 8 if function != 0x42 else 4
    if function == 0x10:
        return None if len(buffer) < 7 else 9 + buffer[6]
    return 8


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        bus: MeterBus = self.server.bus          # type: ignore[attr-defined]
        self.request.settimeout(0.25)
        buffer = b""
        while not self.server.stopping.is_set():  # type: ignore[attr-defined]
            try:
                chunk = self.request.recv(256)
            except socket.timeout:
                buffer = b""                      # the silence between two frames: what was half there is lost, as on a serial line
                continue
            except OSError:
                return
            if not chunk:
                return
            buffer = (buffer + chunk)[-512:]
            while True:
                length = request_length(buffer)
                if length is None or len(buffer) < length:
                    break
                frame, buffer = buffer[:length], buffer[length:]
                reply = bus.answer(frame)
                if reply:
                    try:
                        self.request.sendall(reply)
                    except OSError:
                        return


class MeterBusServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(bus: MeterBus, host: str = "127.0.0.1", port: int = 0) -> tuple[MeterBusServer, threading.Thread]:
    """Listens on a port (0: any free one) and answers in a thread; the caller stops it with `stop(server)`. Only the loopback is allowed unless the caller names another host."""
    if not 0 <= port <= 65535:
        raise MeterBusError("the port must be between 0 and 65535")
    server = MeterBusServer((host, port), _Handler)
    server.bus = bus                              # type: ignore[attr-defined]
    server.stopping = threading.Event()           # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, name="meter-bus", daemon=True)
    thread.start()
    return server, thread


def stop(server: MeterBusServer) -> None:
    server.stopping.set()                         # type: ignore[attr-defined]
    server.shutdown()
    server.server_close()


def real_time_sample(speed: float) -> Callable[[], int]:
    """The sample of the day for the clock: `speed` samples per real second from now on."""
    start = time.monotonic()
    return lambda: int((time.monotonic() - start) * speed)
