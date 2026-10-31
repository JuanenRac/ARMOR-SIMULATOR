"""Command line: emit JSON-lines (MQTT-ready envelopes) and optionally deliver them to a server.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections.abc import Iterator
from pathlib import Path

from .faults import FAULTS, INVALID_FAULTS, TOPIC_KINDS, Message
from .publisher import DeliveryError, check_server_url, post
from .scenarios import SCENARIOS, health, telemetry
from .electrical import electrical_messages
from .solar import solar_messages

NODE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MAX_COUNT = 10_000


def messages(node_id: str, count: int, scenario: str, light: str, seed: int, health_every: int, solar: bool = False, electrical: bool = False) -> Iterator[Message]:
    """The clean message stream: telemetry every second, a health beat every `health_every` samples and, when asked, the solar readings and the electrical node's."""
    for sample in range(count):
        yield f"armor/node/{node_id}/telemetry", telemetry(node_id, sample, scenario, light, seed)
        if health_every and sample % health_every == 0:
            yield f"armor/node/{node_id}/health", health(node_id, sample)
        if solar:
            yield from solar_messages(node_id, sample, seed)
        if electrical:
            yield from electrical_messages(node_id, sample, seed)


def _stamp(stream: Iterator[Message], start_ms: int) -> Iterator[Message]:
    """Dates the messages from `start_ms` on (0: from the epoch, which is what keeps a run identical to another; the server replaces such dates by its own clock - give `--start-ms now`
    when it must take the dates as they are, to see a late message as late)."""
    for topic, payload in stream:
        if start_ms and isinstance(payload.get("timestamp_ms"), int):
            payload = {**payload, "timestamp_ms": payload["timestamp_ms"] + start_ms}
        yield topic, payload


def _common_validators():
    """The ARMOR-COMMON validators (node, solar and electrical messages), found next to this repository when it is not installed."""
    try:
        from armor_common import validate_topic_and_payload
        from armor_common.contracts import validate_electrical_message, validate_solar_message
    except ImportError:
        sibling = Path(__file__).resolve().parents[3] / "ARMOR-COMMON" / "src"
        if not sibling.is_dir():
            raise SystemExit("--validate needs armor_common: install ARMOR-COMMON or keep it next to this repository") from None
        sys.path.insert(0, str(sibling))
        try:
            from armor_common import validate_topic_and_payload
            from armor_common.contracts import validate_electrical_message, validate_solar_message
        except ImportError as error:
            raise SystemExit(f"--validate: the ARMOR-COMMON found does not have the validators this simulator needs ({error})") from None
    return validate_topic_and_payload, validate_solar_message, validate_electrical_message


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="armor-simulator", description="Emit A.R.M.O.R. telemetry as JSON lines")
    parser.add_argument("--node-id", default="simulator-1")
    parser.add_argument("--count", type=int, default=1, help=f"samples to generate (1-{MAX_COUNT})")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="patrol")
    parser.add_argument("--light", choices=("cycle", "night"), default="cycle", help="ambient light: a day/night cycle or a fixed night")
    parser.add_argument("--seed", type=int, default=0, help="the same seed always gives the same output")
    parser.add_argument("--health-every", type=int, default=5, help="one health message every N samples (0 disables)")
    parser.add_argument("--solar", action="store_true", help="also emit an inverter and a battery stack (armor/solar/<node>/<device>/state) every sample")
    parser.add_argument("--electrical", action="store_true", help="also emit an electrical node's three channels (armor/electrical/<node>/state) every sample")
    parser.add_argument("--fault", choices=sorted(FAULTS), default="none", help="inject a repeatable fault")
    parser.add_argument("--fault-every", type=int, default=3, help="how often the fault strikes, counted in the messages of --fault-topic (or after how many of them the node goes silent, for node-silent)")
    parser.add_argument("--fault-topic", choices=sorted(TOPIC_KINDS), default="all", help="the messages the fault looks at: the radar node's telemetry or health, the solar readings or the electrical node's; the others go through untouched (default: all of them)")
    parser.add_argument("--allow-invalid", action="store_true", help="required for faults that violate the contract on purpose")
    parser.add_argument("--validate", action="store_true", help="check every message against ARMOR-COMMON before it is emitted")
    parser.add_argument("--interval-ms", type=int, default=0, help="real pause between messages (0 = as fast as possible)")
    parser.add_argument("--server-url", help="deliver to this ARMOR-SERVER origin (http or https, no path)")
    parser.add_argument("--ingest-token", help="the server's ingest token (visible to other users of the machine in the process list: prefer ARMOR_INGEST_TOKEN or --ingest-token-file)")
    parser.add_argument("--ingest-token-file", type=Path, help="a file with a line ARMOR_INGEST_TOKEN=... (or only the token)")
    parser.add_argument("--per-node-token", action="store_true", help="send each message with the token derived for its node (needed when the server runs with ARMOR_INGEST_STRICT=1)")
    parser.add_argument("--start-ms", default="0", help="date of the first sample: 0 (the default, identical runs), a number of milliseconds, or 'now' (the date the server takes as it is)")
    return parser


def _token(args: argparse.Namespace) -> str:
    if args.ingest_token:
        return args.ingest_token
    if args.ingest_token_file:
        text = Path(args.ingest_token_file).read_text(encoding="utf-8").strip()
        for line in text.splitlines():
            if line.startswith("ARMOR_INGEST_TOKEN="):
                return line.split("=", 1)[1].strip()
        return text.splitlines()[0].strip() if text else ""
    return os.environ.get("ARMOR_INGEST_TOKEN", "").strip()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not NODE_ID.match(args.node_id):
        parser.error("--node-id must be 1-64 characters: lowercase letters, digits, '-' or '_'")
    if not 1 <= args.count <= MAX_COUNT:
        parser.error(f"--count must be between 1 and {MAX_COUNT}")
    if args.interval_ms < 0 or args.fault_every < 0 or args.health_every < 0:
        parser.error("--interval-ms, --fault-every and --health-every must not be negative")
    token = _token(args)
    if bool(args.server_url) != bool(token):
        parser.error("--server-url needs a token (--ingest-token, --ingest-token-file or ARMOR_INGEST_TOKEN), and a token needs --server-url")
    if args.start_ms == "now":
        start_ms = int(time.time() * 1000)
    else:
        try:
            start_ms = int(args.start_ms)
        except ValueError:
            parser.error("--start-ms must be a number of milliseconds or 'now'")
        if start_ms < 0:
            parser.error("--start-ms must not be negative")
    if args.fault == "flapping" and not args.health_every:
        parser.error("--fault flapping needs health messages: --health-every must not be 0")
    if args.fault in ("node-silent", "out-of-order", "duplicates", "corrupt-lux", "unknown-field", "oversized-targets") and not args.fault_every:
        parser.error(f"--fault {args.fault} needs --fault-every of at least 1")
    if args.fault != "none" and args.fault_topic == "health" and not args.health_every:
        parser.error("--fault-topic health needs health messages: --health-every must not be 0")
    if args.fault != "none" and (args.fault_topic == "solar" and not args.solar or args.fault_topic == "electrical" and not args.electrical):
        parser.error(f"--fault-topic {args.fault_topic} needs --{args.fault_topic} (there are no such messages to spoil)")
    if args.fault in INVALID_FAULTS and not args.allow_invalid:
        parser.error(f"--fault {args.fault} produces invalid messages on purpose; add --allow-invalid")
    if args.fault in INVALID_FAULTS and args.validate:
        parser.error("--validate and an invalid fault contradict each other")
    server = check_server_url(args.server_url) if args.server_url else None
    validate, validate_solar, validate_electrical = _common_validators() if args.validate else (None, None, None)

    stream = FAULTS[args.fault](_stamp(messages(args.node_id, args.count, args.scenario, args.light, args.seed, args.health_every, args.solar, args.electrical), start_ms), args.fault_every, TOPIC_KINDS[args.fault_topic])
    accepted_invalid = refused = 0
    for number, (topic, payload) in enumerate(stream, start=1):
        if validate:
            try:
                (validate_solar if topic.startswith("armor/solar/") else validate_electrical if topic.startswith("armor/electrical/") else validate)(topic, payload)  # type: ignore[misc]
            except (ValueError, KeyError, TypeError) as error:
                print(f"armor-simulator: message {number} on {topic} is not valid for ARMOR-COMMON: {error}", file=sys.stderr)
                return 1
        if server:
            try:
                post(server, token, "solar" if topic.startswith("armor/solar/") else "electrical" if topic.startswith("armor/electrical/") else topic.rsplit("/", 1)[1], payload, per_node=args.per_node_token)
                if args.fault in INVALID_FAULTS and _is_invalid(args.fault, topic, payload):
                    accepted_invalid += 1
            except DeliveryError as error:
                # A deliberately invalid message is expected to be refused: report it and go on.
                if args.fault not in INVALID_FAULTS:
                    print(f"armor-simulator: {error}", file=sys.stderr)
                    return 1
                refused += 1
                print(f"armor-simulator: refused as expected ({error})", file=sys.stderr)
        print(json.dumps({"topic": topic, "payload": payload}, separators=(",", ":"), sort_keys=True), flush=True)
        if args.interval_ms:
            time.sleep(args.interval_ms / 1000)
    if server and args.fault in INVALID_FAULTS:
        print(f"armor-simulator: of the invalid messages, {refused} were refused and {accepted_invalid} were accepted by the server (it accepts unknown fields in solar, electrical and MQTT messages on purpose)", file=sys.stderr)
    return 0


def _is_invalid(fault: str, topic: str, payload: dict) -> bool:
    """Whether this message is one the fault spoiled (so that an accepted one can be counted)."""
    if fault == "corrupt-lux":
        return topic.endswith("/telemetry") and payload.get("lux", 0) > 200_000
    if fault == "unknown-field":
        return "firmware_debug" in payload
    return topic.endswith("/telemetry") and len(payload.get("targets", [])) > 15


if __name__ == "__main__":
    raise SystemExit(main())
