"""The MQTT shim: the message code of a real node, built for a computer, publishing on a broker.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

    python -m armor_simulator.node_shim --node radar --driver ./mqtt_shim --node-id shim-radar --mqtt-url mqtt://127.0.0.1:1883

The program given by `--driver` is `tests/mqtt_shim.cpp` of a node repository (so far ARMOR-NODE-RADAR, ARMOR-NODE-ELECTRICAL, ARMOR-NODE-SOLAR and ARMOR-NODE-ALARM; `--node` says which), built from the core files of its firmware. This module plays it the serial
stream of the radar modules that `buses.py` makes, one chunk per line with a made-up light level, and publishes on the broker what it prints (topic, tab, payload), with the QoS and the
topic the real node uses. The framing, the decoding and the JSON are the firmware's; only the broker client and the clock are the simulator's. Nodes are added one at a time, each one
with a driver of its own. Only simulated data goes out, and only to a broker on this machine or a private network (see `mqtt_out.py`).
"""

from __future__ import annotations

import argparse
import functools
import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass

from . import buses, meter_bus, solar
from .mqtt_out import MqttOutError, MqttSink

TIMEOUT_S = 60
CHUNK_BYTES = 30          # one chunk is about one frame of the module


class ShimError(RuntimeError):
    """The driver could not be run or said something that is not a message."""


def stream_lines(seed: int = 1, frames: int = 12, start_ms: int = 1_000, step_ms: int = 100) -> tuple[list[str], int]:
    """The chunks of a clean radar stream as the driver's input lines, and how many frames they carry (the radar node)."""
    case = buses.ld2450(seed, "none", frames=frames)
    raw = bytes.fromhex(case.payload)
    lines = []
    for index in range(0, len(raw), CHUNK_BYTES):
        lines.append(f"{start_ms + step_ms * (index // CHUNK_BYTES)}\t{150.0 + index % 7:.1f}\t{raw[index:index + CHUNK_BYTES].hex()}")
    return lines, frames


def meter_lines(rounds: int = 6, start_ms: int = 1_000, step_ms: int = 1_000) -> tuple[list[str], int]:
    """The rounds of the three default meters of the meter bus as the driver's input lines (the electrical node): the replies are the Modbus-RTU frames the bus makes."""
    bus = meter_bus.MeterBus(meter_bus.default_config())
    lines = []
    for number in range(rounds):
        bus.sample = functools.partial(int, number)
        entries = []
        for meter in bus.config.meters:
            count = 10 if meter.model == "pzem-004t" else 8
            request = meter_bus.with_crc(bytes((meter.address, meter_bus.FUNCTION_INPUT, 0, 0, 0, count)))
            reply = bus.answer(request)
            if reply is not None:
                entries.append(f"{meter.channel}:{meter.model}:{meter.address}:{reply.hex()}")
        lines.append(f"{start_ms + step_ms * number}	" + "|".join(entries))
    return lines, rounds


def _qpigs(reading: dict) -> str:
    """The QPIGS reply text an inverter of the Voltronic family says for a simulated reading (the standard arrangement, with the PV power in the last field)."""
    current = reading["battery_a"]
    bits = ("1" if reading["load_on"] else "0")
    status = f"000{bits}0{'1' if reading['pv_charging'] else '0'}{'1' if reading['pv_charging'] else '0'}{'1' if reading['ac_charging'] else '0'}"
    fields = [f"{reading['grid_v']:05.1f}", f"{reading['grid_hz']:04.1f}", f"{reading['out_v']:05.1f}", f"{reading['out_hz']:04.1f}", f"{reading['out_va']:04d}", f"{reading['out_w']:04d}",
              f"{reading['load_percent']:03d}", "380", f"{reading['battery_v']:05.2f}", f"{round(max(current, 0)):03d}", f"{reading['battery_percent']:03d}", f"{reading['heatsink_c']:04d}",
              f"{round(reading['pv_a']):04d}", f"{reading['pv_v']:05.1f}", f"{reading['battery_v']:05.2f}", f"{round(max(-current, 0)):05d}", status, "00", "00", f"{reading['pv_w']:05d}"]
    return " ".join(fields)


def _qpiws(reading: dict) -> str:
    flags = ["0"] * 36
    if "line_fail" in reading["warnings"]:
        flags[5] = "1"
    return "".join(flags)


def solar_lines(rounds: int = 6, seed: int = 1, start_ms: int = 1_000, step_ms: int = 1_000, outage_at: int = 3) -> tuple[list[str], int]:
    """The rounds of an inverter and a Pylontech stack as the driver's input lines (the solar node): the inverter's replies as text (the driver frames them with the node's CRC) and the
    two consoles of the battery as hex. Round `outage_at` is on the battery with the mains lost. Two messages with readings must come out of every round."""
    lines = []
    for number in range(rounds):
        reading = solar.inverter("shim-solar", number, seed)
        if number == outage_at:
            reading.update(mode="battery", grid_v=0.0, grid_hz=0.0, warnings=["line_fail"], battery_a=-3.0)
        stamp = start_ms + step_ms * number
        lines.append(f"{stamp}	inverter	axpert-1	{_qpigs(reading)}	{'B' if reading['mode'] == 'battery' else 'L'}	{_qpiws(reading)}")
        pwr, bat = buses.pylontech(seed + number, "none", modules=2).payload.split(",")
        lines.append(f"{stamp}	battery	us3000-1	{pwr}	{bat}")
    return lines, 2 * rounds


ALARM_STEPS = ("-", "arm_away", "-", "-", "restart", "disarm", "arm_away", "-")   # what happens to the panel, one step per second
ALARM_DOOR_OPEN_AT = (3, 4)                                                          # the steps where the door loop reads "open"
ALARM_PHASES = ("exit_delay", "armed", "alarm", "disarmed")                          # the phases the panel must go through


def alarm_lines(rounds: int = 8, seed: int = 1, start_ms: int = 1_000, step_ms: int = 1_000) -> tuple[list[str], int]:
    """The steps of a wired alarm panel as the driver's input lines (the alarm node): armed away, the door loop opens and the siren starts, a power cut and the restart that
    takes the alarm back, the PIN that disarms, armed again. The voltages are the ones the bus of the simulator calls a closed loop and an open one."""
    lines = []
    for number in range(rounds):
        door = 1_800 if number in ALARM_DOOR_OPEN_AT else 800 + (seed + number) % 3 * 10
        lines.append(f"{start_ms + step_ms * number}	{ALARM_STEPS[number % len(ALARM_STEPS)]}	door:instant:{door}|hall:interior:{800 + number % 4 * 5}")
    return lines, rounds


def alarm_verify(messages: list[tuple[str, dict]]) -> str | None:
    """The panel must have gone through every phase of the scenario, in the message it wrote and not only in the last one."""
    seen = [body.get("phase") for topic, body in messages if topic.endswith("/state")]
    missing = [phase for phase in ALARM_PHASES if phase not in seen]
    return f"the panel never reported the phases {missing}" if missing else None


#: What each node's shim prints: the topics it may use (the first one is the message that carries the readings) and the lines it is played.
@dataclass(frozen=True)
class NodeShim:
    prefixes: tuple[str, ...]                    # the topics the shim may print, with {id} for the node
    main: str                                    # the end of the topic of the message that carries the readings
    lines: Callable[..., tuple[list[str], int]]  # makes the input lines and says how many messages with readings must come out
    verify: Callable[[list[tuple[str, dict]]], str | None] | None = None   # a check on the whole of what the driver printed; says what is wrong, or None


NODES: dict[str, NodeShim] = {
    "radar": NodeShim(("armor/node/{id}/",), "/telemetry", stream_lines),
    "electrical": NodeShim(("armor/electrical/{id}/", "armor/health/{id}"), "/state", meter_lines),
    "alarm": NodeShim(("armor/alarm/{id}/", "armor/health/{id}"), "/state", alarm_lines, alarm_verify),
    "solar": NodeShim(("armor/solar/{id}/", "armor/health/{id}"), "/state", solar_lines),
}


def run_driver(driver: list[str], node_id: str, lines: list[str], timeout: float = TIMEOUT_S, node: str = "radar") -> list[tuple[str, dict]]:
    """Plays the lines to the driver; gives the (topic, payload) messages it printed. A line that is not a topic and a JSON object is an error."""
    prefixes = tuple(prefix.format(id=node_id) for prefix in NODES[node].prefixes)
    done = subprocess.run([*driver, node_id], input="".join(line + "\n" for line in lines), capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603
    if done.returncode != 0:
        raise ShimError(f"the driver stopped with status {done.returncode}: {done.stderr.strip()[:300]}")
    messages = []
    for line in done.stdout.splitlines():
        topic, _, payload = line.partition("\t")
        try:
            body = json.loads(payload)
        except ValueError:
            raise ShimError(f"the driver printed something that is not a message: {line[:120]}") from None
        if not topic.startswith(prefixes) or not isinstance(body, dict):
            raise ShimError(f"the driver printed a topic that is not the node's own: {topic[:120]}")
        messages.append((topic, body))
    return messages


def publish(messages: list[tuple[str, dict]], url: str, allow_network: bool = False, client_id: str = "armor-node-shim",
            client_factory: Callable[[str], object] | None = None) -> int:
    sink = MqttSink(url, allow_network=allow_network, client_id=client_id, client_factory=client_factory)
    sink.open()
    try:
        for topic, body in messages:
            sink.publish(topic, body)
    finally:
        sink.close()
    return sink.published


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="armor_simulator.node_shim", description=__doc__.split("\n\n")[0])
    parser.add_argument("--node", choices=sorted(NODES), default="radar", help="which node the driver is the shim of")
    parser.add_argument("--driver", required=True, help="the program built from tests/mqtt_shim.cpp of a node")
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--mqtt-url", required=True)
    parser.add_argument("--mqtt-allow-network", action="store_true")
    parser.add_argument("--frames", type=int, default=12)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args(argv)
    try:
        if args.node == "radar":
            lines, frames = stream_lines(args.seed, args.frames)
        elif args.node == "solar":
            lines, frames = solar_lines(args.frames, args.seed)
        elif args.node == "alarm":
            lines, frames = alarm_lines(max(args.frames, len(ALARM_STEPS)), args.seed)
        else:
            lines, frames = meter_lines(args.frames)
        messages = run_driver(args.driver.split(), args.node_id, lines, node=args.node)
        telemetry = [body for topic, body in messages if topic.endswith(NODES[args.node].main)]
        if len(telemetry) != frames:
            raise ShimError(f"{frames} rounds went in and {len(telemetry)} messages with the readings came out")
        verify = NODES[args.node].verify
        problem = verify(messages) if verify is not None else None
        if problem:
            raise ShimError(problem)
        count = publish(messages, args.mqtt_url, args.mqtt_allow_network)
    except (ShimError, buses.BusError, MqttOutError, OSError, subprocess.SubprocessError) as error:
        print(f"node shim: {error}", file=sys.stderr)
        return 2
    print(f"NODE_SHIM=PASS node={args.node_id} frames={frames} published={count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
