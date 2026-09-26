"""Command line: emit JSON-lines (MQTT-ready envelopes) and optionally deliver them to a server.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Iterator
from pathlib import Path

from .faults import FAULTS, INVALID_FAULTS, Message
from .publisher import DeliveryError, check_server_url, post
from .scenarios import SCENARIOS, health, telemetry
from .solar import solar_messages

NODE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MAX_COUNT = 10_000


def messages(node_id: str, count: int, scenario: str, light: str, seed: int, health_every: int, solar: bool = False) -> Iterator[Message]:
    """The clean message stream: telemetry every second, a health beat every `health_every` samples and, when asked, the solar readings."""
    for sample in range(count):
        yield f"armor/node/{node_id}/telemetry", telemetry(node_id, sample, scenario, light, seed)
        if health_every and sample % health_every == 0:
            yield f"armor/node/{node_id}/health", health(node_id, sample)
        if solar:
            yield from solar_messages(node_id, sample, seed)


def _common_validators():
    """The ARMOR-COMMON validators (node messages, solar messages), found next to this repository when it is not installed."""
    try:
        from armor_common import validate_topic_and_payload
        from armor_common.contracts import validate_solar_message
    except ImportError:
        sibling = Path(__file__).resolve().parents[3] / "ARMOR-COMMON" / "src"
        if not sibling.is_dir():
            raise SystemExit("--validate needs armor_common: install ARMOR-COMMON or keep it next to this repository")
        sys.path.insert(0, str(sibling))
        from armor_common import validate_topic_and_payload
        from armor_common.contracts import validate_solar_message
    return validate_topic_and_payload, validate_solar_message


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="armor-simulator", description="Emit A.R.M.O.R. telemetry as JSON lines")
    parser.add_argument("--node-id", default="simulator-1")
    parser.add_argument("--count", type=int, default=1, help=f"samples to generate (1-{MAX_COUNT})")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="patrol")
    parser.add_argument("--light", choices=("cycle", "night"), default="cycle", help="ambient light: a day/night cycle or a fixed night")
    parser.add_argument("--seed", type=int, default=0, help="the same seed always gives the same output")
    parser.add_argument("--health-every", type=int, default=5, help="one health message every N samples (0 disables)")
    parser.add_argument("--solar", action="store_true", help="also emit an inverter and a battery stack (armor/solar/<node>/<device>/state) every sample")
    parser.add_argument("--fault", choices=sorted(FAULTS), default="none", help="inject a repeatable fault")
    parser.add_argument("--fault-every", type=int, default=3, help="how often the fault strikes (or after how many messages, for node-silent)")
    parser.add_argument("--allow-invalid", action="store_true", help="required for faults that violate the contract on purpose")
    parser.add_argument("--validate", action="store_true", help="check every message against ARMOR-COMMON before it is emitted")
    parser.add_argument("--interval-ms", type=int, default=0, help="real pause between messages (0 = as fast as possible)")
    parser.add_argument("--server-url", help="deliver to this ARMOR-SERVER origin (http or https, no path)")
    parser.add_argument("--ingest-token", help="required with --server-url; never write it to a file")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not NODE_ID.match(args.node_id):
        parser.error("--node-id must be 1-64 characters: lowercase letters, digits, '-' or '_'")
    if not 1 <= args.count <= MAX_COUNT:
        parser.error(f"--count must be between 1 and {MAX_COUNT}")
    if args.interval_ms < 0 or args.fault_every < 0 or args.health_every < 0:
        parser.error("--interval-ms, --fault-every and --health-every must not be negative")
    if bool(args.server_url) != bool(args.ingest_token):
        parser.error("--server-url and --ingest-token must be supplied together")
    if args.fault in INVALID_FAULTS and not args.allow_invalid:
        parser.error(f"--fault {args.fault} produces invalid messages on purpose; add --allow-invalid")
    if args.fault in INVALID_FAULTS and args.validate:
        parser.error("--validate and an invalid fault contradict each other")
    server = check_server_url(args.server_url) if args.server_url else None
    validate, validate_solar = _common_validators() if args.validate else (None, None)

    stream = FAULTS[args.fault](messages(args.node_id, args.count, args.scenario, args.light, args.seed, args.health_every, args.solar), args.fault_every)
    for topic, payload in stream:
        if validate:
            (validate_solar if topic.startswith("armor/solar/") else validate)(topic, payload)
        if server:
            try:
                post(server, args.ingest_token, "solar" if topic.startswith("armor/solar/") else topic.rsplit("/", 1)[1], payload)
            except DeliveryError as error:
                # A deliberately invalid message is expected to be refused: report it and go on.
                if args.fault not in INVALID_FAULTS:
                    print(f"armor-simulator: {error}", file=sys.stderr)
                    return 1
                print(f"armor-simulator: refused as expected ({error})", file=sys.stderr)
        print(json.dumps({"topic": topic, "payload": payload}, separators=(",", ":"), sort_keys=True), flush=True)
        if args.interval_ms:
            time.sleep(args.interval_ms / 1000)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
