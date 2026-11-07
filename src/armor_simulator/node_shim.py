"""The MQTT shim: the message code of a real node, built for a computer, publishing on a broker.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

    python -m armor_simulator.node_shim --driver ./mqtt_shim --node-id shim-radar --mqtt-url mqtt://127.0.0.1:1883

The program given by `--driver` is `tests/mqtt_shim.cpp` of a node repository (so far ARMOR-NODE-RADAR), built from the core files of its firmware. This module plays it the serial
stream of the radar modules that `buses.py` makes, one chunk per line with a made-up light level, and publishes on the broker what it prints (topic, tab, payload), with the QoS and the
topic the real node uses. The framing, the decoding and the JSON are the firmware's; only the broker client and the clock are the simulator's. Nodes are added one at a time, each one
with a driver of its own. Only simulated data goes out, and only to a broker on this machine or a private network (see `mqtt_out.py`).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable

from . import buses
from .mqtt_out import MqttOutError, MqttSink

TIMEOUT_S = 60
CHUNK_BYTES = 30          # one chunk is about one frame of the module


class ShimError(RuntimeError):
    """The driver could not be run or said something that is not a message."""


def stream_lines(seed: int = 1, frames: int = 12, start_ms: int = 1_000, step_ms: int = 100) -> tuple[list[str], int]:
    """The chunks of a clean radar stream as the driver's input lines, and how many frames they carry."""
    case = buses.ld2450(seed, "none", frames=frames)
    raw = bytes.fromhex(case.payload)
    lines = []
    for index in range(0, len(raw), CHUNK_BYTES):
        lines.append(f"{start_ms + step_ms * (index // CHUNK_BYTES)}\t{150.0 + index % 7:.1f}\t{raw[index:index + CHUNK_BYTES].hex()}")
    return lines, frames


def run_driver(driver: list[str], node_id: str, lines: list[str], timeout: float = TIMEOUT_S) -> list[tuple[str, dict]]:
    """Plays the lines to the driver; gives the (topic, payload) messages it printed. A line that is not a topic and a JSON object is an error."""
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
        if not topic.startswith(f"armor/node/{node_id}/") or not isinstance(body, dict):
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
    parser.add_argument("--driver", required=True, help="the program built from tests/mqtt_shim.cpp of a node")
    parser.add_argument("--node-id", required=True)
    parser.add_argument("--mqtt-url", required=True)
    parser.add_argument("--mqtt-allow-network", action="store_true")
    parser.add_argument("--frames", type=int, default=12)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args(argv)
    try:
        lines, frames = stream_lines(args.seed, args.frames)
        messages = run_driver(args.driver.split(), args.node_id, lines)
        telemetry = [body for topic, body in messages if topic.endswith("/telemetry")]
        if len(telemetry) != frames:
            raise ShimError(f"{frames} frames went in and {len(telemetry)} telemetry messages came out")
        count = publish(messages, args.mqtt_url, args.mqtt_allow_network)
    except (ShimError, buses.BusError, MqttOutError, OSError, subprocess.SubprocessError) as error:
        print(f"node shim: {error}", file=sys.stderr)
        return 2
    print(f"NODE_SHIM=PASS node={args.node_id} frames={frames} published={count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
