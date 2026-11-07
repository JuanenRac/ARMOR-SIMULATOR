"""The MQTT shim: the message code of a real node, built for a computer, publishing on a broker.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

    python -m armor_simulator.node_shim --node radar --driver ./mqtt_shim --node-id shim-radar --mqtt-url mqtt://127.0.0.1:1883

The program given by `--driver` is `tests/mqtt_shim.cpp` of a node repository (so far ARMOR-NODE-RADAR and ARMOR-NODE-ELECTRICAL; `--node` says which), built from the core files of its firmware. This module plays it the serial
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

from . import buses, meter_bus
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


#: What each node's shim prints: the topics it may use (the first one is the message that carries the readings) and the lines it is played.
@dataclass(frozen=True)
class NodeShim:
    prefixes: tuple[str, ...]                    # the topics the shim may print, with {id} for the node
    main: str                                    # the end of the topic of the message that carries the readings
    lines: Callable[..., tuple[list[str], int]]  # makes the input lines and says how many messages with readings must come out


NODES: dict[str, NodeShim] = {
    "radar": NodeShim(("armor/node/{id}/",), "/telemetry", stream_lines),
    "electrical": NodeShim(("armor/electrical/{id}/", "armor/health/{id}"), "/state", meter_lines),
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
        lines, frames = stream_lines(args.seed, args.frames) if args.node == "radar" else meter_lines(args.frames)
        messages = run_driver(args.driver.split(), args.node_id, lines, node=args.node)
        telemetry = [body for topic, body in messages if topic.endswith(NODES[args.node].main)]
        if len(telemetry) != frames:
            raise ShimError(f"{frames} rounds went in and {len(telemetry)} messages with the readings came out")
        count = publish(messages, args.mqtt_url, args.mqtt_allow_network)
    except (ShimError, buses.BusError, MqttOutError, OSError, subprocess.SubprocessError) as error:
        print(f"node shim: {error}", file=sys.stderr)
        return 2
    print(f"NODE_SHIM=PASS node={args.node_id} frames={frames} published={count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
