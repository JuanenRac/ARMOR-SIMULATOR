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
from typing import Any

from .alarm_scenarios import ScenarioError, build_stream, load_observed, load_scenario, summary, verify_alarms
from .energy import MAX_STEPS, DAY_S, energy_messages, load_config
from .faults import FAULTS, INVALID_FAULTS, TOPIC_KINDS, Message
from .http_faults import HTTP_FAULTS, MAX_LATENCY_MS, plan as delivery_plan
from .panel_sim import BEHAVIORS, PanelLink, PanelLinkError, SimulatedPanel, verify_panel_map, verify_panel_sync
from .publisher import DeliveryError, check_server_url, kind_of, post
from .recording import RecordingError, load_recording, open_for_recording, tee
from .scenarios import SCENARIOS, health, scenario_for_node, telemetry
from .server_driver import DriverError, Session, drive
from .electrical import electrical_messages
from .mqtt_out import MqttOutError, MqttSink
from .nodes import alarm_state, info as node_info, network_state
from .meter_bus import LOOPBACK, MeterBus, MeterBusError, load_config as load_meter_bus, real_time_sample, serve as serve_meter_bus, stop as stop_meter_bus
from .solar import solar_messages

NODE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MAX_COUNT = 10_000


INFO_EVERY = 30      # samples between the "info" messages of a node (and one at the start)
NETWORK_EVERY = 5    # samples between the messages of a simulated network watcher


def messages(node_id: str, count: int, scenario: str, light: str, seed: int, health_every: int, solar: bool = False, electrical: bool = False, *,
              nodes: tuple[str, ...] = (), info: bool = False, alarm_node: str | None = None, network_node: str | None = None) -> Iterator[Message]:
    """The clean message stream: telemetry every second, a health beat every `health_every` samples and, when asked, the solar readings and the electrical node's.

    `nodes` simulates several radar nodes at once (the first one also carries the solar and electrical readings); with the scenario `relay` one walker goes from node to node.
    `info` adds what each radar node says about itself, `alarm_node` and `network_node` a simulated alarm panel and a network watcher.
    """
    radars = nodes or (node_id,)
    for sample in range(count):
        for index, radar in enumerate(radars):
            yield f"armor/node/{radar}/telemetry", telemetry(radar, sample, scenario_for_node(scenario, index, len(radars), sample), light, seed)
            if health_every and sample % health_every == 0:
                yield f"armor/node/{radar}/health", health(radar, sample)
            if info and sample % INFO_EVERY == 0:
                yield f"armor/node/{radar}/info", node_info(radar, sample)
        if solar:
            yield from solar_messages(radars[0], sample, seed)
        if electrical:
            yield from electrical_messages(radars[0], sample, seed)
        if alarm_node:
            yield f"armor/alarm/{alarm_node}/state", alarm_state(alarm_node, sample)
        if network_node and sample % NETWORK_EVERY == 0:
            yield f"armor/network/{network_node}/state", network_state(network_node, sample)


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
        from armor_common.contracts import validate_alarm_message, validate_electrical_message, validate_network_message, validate_solar_message
    except ImportError:
        sibling = Path(__file__).resolve().parents[3] / "ARMOR-COMMON" / "src"
        if not sibling.is_dir():
            raise SystemExit("--validate needs armor_common: install ARMOR-COMMON or keep it next to this repository") from None
        sys.path.insert(0, str(sibling))
        try:
            from armor_common import validate_topic_and_payload
            from armor_common.contracts import validate_alarm_message, validate_electrical_message, validate_network_message, validate_solar_message
        except ImportError as error:
            raise SystemExit(f"--validate: the ARMOR-COMMON found does not have the validators this simulator needs ({error})") from None
    return validate_topic_and_payload, validate_solar_message, validate_electrical_message, validate_alarm_message, validate_network_message


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
    parser.add_argument("--alarm-scenario", type=Path, metavar="FILE", help="play an alarm scenario described in a JSON file (see docs/ALARM_SCENARIOS.md) instead of --scenario/--count")
    parser.add_argument("--check-alarm-scenario", action="store_true", help="only validate the file of --alarm-scenario and print what it contains")
    parser.add_argument("--verify-alarms", type=Path, metavar="FILE", help="compare the alarms a server raised (a JSON list or JSON lines) with what the file of --alarm-scenario expects; exit 1 when they differ")
    parser.add_argument("--drive-server", action="store_true", help="play the file of --alarm-scenario against the real ARMOR-SERVER of --server-url (the mode events become orders to the server, in real time) and check the alarms it raised; needs --studio-user")
    parser.add_argument("--studio-user", help="the account of Studio that arms the server for --drive-server (an operator; an administrator with --apply-modes); the password comes from ARMOR_STUDIO_PASSWORD or --studio-password-file")
    parser.add_argument("--studio-password-file", type=Path, metavar="FILE", help="a file whose first line is the password of --studio-user (never on the command line)")
    parser.add_argument("--studio-pin-file", type=Path, metavar="FILE", help="a file whose first line is the PIN of --studio-user, for a mode change that defends less (or ARMOR_STUDIO_PIN)")
    parser.add_argument("--apply-modes", action="store_true", help="with --drive-server, define in the server what home and night defend, from the scenario (an administrator account)")
    parser.add_argument("--settle-s", type=float, default=3.0, help="with --drive-server, seconds to wait after the scenario before reading the alarms (default 3)")
    parser.add_argument("--verify-panel-sync", action="store_true", help="check a real ARMOR-SERVER with alarm.mode_panel_sync on: a simulated alarm panel on the broker of the server answers (accept, refuse, silent) while every mode is chosen, and the report of the server is compared with what must be true; needs --server-url, --studio-user and --mqtt-url")
    parser.add_argument("--verify-panel-map", action="store_true", help="with --verify-panel-sync, also check the choices of the owner about how the modes reach the panels (the profile of a mode and the list of panels); it changes the document of the modes and puts it back (needs an administrator)")
    parser.add_argument("--mqtt-url", help="a broker (mqtt://host[:port]): the messages are also published there with their topics (this machine or a private network; others need --mqtt-allow-network); with --verify-panel-sync, the broker the server uses (mqtt://host[:port]); the simulated panel connects to it")
    parser.add_argument("--mqtt-user", help="with --verify-panel-sync, the user of the broker (the password in ARMOR_MQTT_PASSWORD or --mqtt-password-file)")
    parser.add_argument("--mqtt-password-file", type=Path, metavar="FILE", help="a file whose first line is the password of the broker (never on the command line)")
    parser.add_argument("--mqtt-allow-network", action="store_true", help="allow --mqtt-url to name a broker that is neither this machine nor a private network address")
    parser.add_argument("--nodes", help="simulate several radar nodes at once: ids separated by commas (the first one carries --solar and --electrical); with --scenario relay one walker passes from node to node")
    parser.add_argument("--info", action="store_true", help="also emit what each radar node says about itself (armor/node/<id>/info; the server takes it from the broker only)")
    parser.add_argument("--alarm-node", metavar="ID", help="also emit the state of a simulated alarm panel with this id (armor/alarm/<id>/state): disarmed, delay, armed, entry delay, siren")
    parser.add_argument("--network-node", metavar="ID", help="also emit the state of a simulated network watcher with this id (armor/network/<id>/state)")
    parser.add_argument("--panel-id", default="sim-panel", help="with --verify-panel-sync, the node id of the simulated panel (default sim-panel)")
    parser.add_argument("--panel-behavior", choices=BEHAVIORS, action="append", help="with --verify-panel-sync, play only this behaviour of the panel (repeat for several; default all)")
    parser.add_argument("--save-observed", type=Path, metavar="FILE", help="with --drive-server, write the alarms the server raised as JSON, to repeat the check with --verify-alarms")
    parser.add_argument("--energy", action="store_true", help="emit realistic solar and electrical data (sun with clouds, house by the hour, tariff, battery, noisy meter) instead of the fast day of --solar/--electrical")
    parser.add_argument("--energy-config", type=Path, metavar="FILE", help="a JSON file with the settings of --energy (see docs/ENERGY_MODEL.md); the defaults apply to what it does not say")
    parser.add_argument("--energy-days", type=float, default=1.0, help="days of data of --energy (default 1)")
    parser.add_argument("--energy-step-s", type=int, default=900, help="seconds between the samples of --energy (default 900)")
    parser.add_argument("--record", type=Path, metavar="FILE", help="also write every emitted message to FILE as JSON lines, to play it again with --replay (an existing file is never overwritten)")
    parser.add_argument("--replay", type=Path, metavar="FILE", help="emit the messages of a recording made with --record instead of generating them (faults, --validate and --server-url still apply)")
    parser.add_argument("--http-fault", choices=HTTP_FAULTS, default="none", help="spoil the delivery to --server-url, not the messages: a slow link (latency), a message that never arrives (drop) or one sent twice (duplicate)")
    parser.add_argument("--http-fault-every", type=int, default=3, help="every Nth message suffers --http-fault (default 3)")
    parser.add_argument("--http-latency-ms", type=int, default=1500, help=f"pause of --http-fault latency, up to {MAX_LATENCY_MS} (default 1500)")
    parser.add_argument("--meter-bus-port", type=int, metavar="PORT", help="instead of emitting messages, play the serial line of the energy meters over TCP on this port (0: any free one): Modbus-RTU requests are answered like a PZEM-004T and a PZEM-017 answer them (see docs/METER_BUS.md)")
    parser.add_argument("--meter-bus-config", type=Path, metavar="FILE", help="a JSON file with the meters, thresholds and faults of --meter-bus-port; the defaults are the three meters of --electrical")
    parser.add_argument("--meter-bus-host", default="127.0.0.1", help="the address --meter-bus-port listens on (default 127.0.0.1, this computer only)")
    parser.add_argument("--meter-bus-allow-network", action="store_true", help="required to listen on an address that is not the loopback; the bus has no authentication")
    parser.add_argument("--meter-bus-seconds", type=float, default=0.0, help="stop the meter bus after this many seconds (0: until interrupted)")
    return parser


def _meter_bus(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """--meter-bus-port: the meters answer on a TCP port until the time is up or the run is interrupted."""
    if not 0 <= args.meter_bus_port <= 65535:
        parser.error("--meter-bus-port must be between 0 and 65535")
    if not 0 <= args.meter_bus_seconds <= 86400 * 7:
        parser.error("--meter-bus-seconds must be between 0 and 604800")
    if args.meter_bus_host not in LOOPBACK and not args.meter_bus_allow_network:
        parser.error("--meter-bus-host: only the loopback is allowed unless you add --meter-bus-allow-network (the bus has no authentication)")
    try:
        config = load_meter_bus(args.meter_bus_config)
    except MeterBusError as error:
        print(f"armor-simulator: meter bus: {error}", file=sys.stderr)
        return 2
    bus = MeterBus(config, real_time_sample(config.speed))
    try:
        server, _ = serve_meter_bus(bus, args.meter_bus_host, args.meter_bus_port)
    except OSError as error:
        print(f"armor-simulator: meter bus: cannot listen on {args.meter_bus_host}:{args.meter_bus_port}: {str(error.strerror or error)}", file=sys.stderr)
        return 2
    host, port = str(server.server_address[0]), server.server_address[1]
    print(f"armor-simulator: meter bus listening on {host}:{port} with {len(config.meters)} meter(s) at address(es) {', '.join(str(m.address) for m in config.meters)}", file=sys.stderr, flush=True)
    try:
        if args.meter_bus_seconds:
            time.sleep(args.meter_bus_seconds)
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        stop_meter_bus(server)
    print(f"armor-simulator: meter bus: {bus.requests} request(s), {bus.answered} answered, {bus.silent} left without an answer, {bus.refused_writes} write(s) refused", file=sys.stderr)
    return 0


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


def _first_line(parser: argparse.ArgumentParser, path: Path | None, variable: str) -> str:
    if path:
        try:
            text = Path(path).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as error:
            parser.error(f"cannot read {path}: {getattr(error, 'strerror', None) or error}")
        return text.splitlines()[0].strip() if text else ""
    return os.environ.get(variable, "").strip()


def _drive(parser: argparse.ArgumentParser, args: argparse.Namespace, scenario: Any, token: str) -> int:
    """--drive-server: the scenario played against a real server, the alarms it raised compared with the expectation."""
    if not args.server_url or not token or not args.studio_user:
        parser.error("--drive-server needs --server-url, the ingest token and --studio-user (the password in ARMOR_STUDIO_PASSWORD or --studio-password-file)")
    if args.fault != "none" or args.validate or args.interval_ms:
        parser.error("--drive-server plays in real time with no faults: it cannot be combined with --fault, --validate or --interval-ms")
    if not 0 <= args.settle_s <= 300:
        parser.error("--settle-s must be between 0 and 300")
    password = _first_line(parser, args.studio_password_file, "ARMOR_STUDIO_PASSWORD")
    if not password:
        parser.error("--drive-server needs the password of --studio-user in ARMOR_STUDIO_PASSWORD or in --studio-password-file")
    pin = _first_line(parser, args.studio_pin_file, "ARMOR_STUDIO_PIN") or None
    server = check_server_url(args.server_url)
    session = Session(server)
    try:
        session.login(args.studio_user, password)
        result = drive(scenario, session, ingest_url=server, ingest_token=token, per_node=args.per_node_token, apply_modes=args.apply_modes, pin=pin, health_every=args.health_every, settle_s=args.settle_s)
    except DriverError as error:
        print(f"armor-simulator: {error}", file=sys.stderr)
        return 2
    for line in result.log:
        print(f"armor-simulator: {line}", file=sys.stderr)
    if args.save_observed:
        Path(args.save_observed).write_text(json.dumps(result.observed, indent=1) + "\n", encoding="utf-8")
    for problem in result.problems:
        print(f"armor-simulator: {problem}", file=sys.stderr)
    print(f"armor-simulator: {scenario.name}: the server raised {len(result.observed)} alarm(s); " + ("it answered as expected" if not result.problems else f"{len(result.problems)} difference(s) with what was expected"))
    return 1 if result.problems else 0


def _verify_panel_sync(parser: argparse.ArgumentParser, args: argparse.Namespace) -> int:
    """--verify-panel-sync: a simulated alarm panel and every mode chosen on a real server, the report compared with what must be true."""
    if not args.server_url or not args.studio_user or not args.mqtt_url:
        parser.error("--verify-panel-sync needs --server-url, --studio-user (the password in ARMOR_STUDIO_PASSWORD or --studio-password-file) and --mqtt-url")
    password = _first_line(parser, args.studio_password_file, "ARMOR_STUDIO_PASSWORD")
    if not password:
        parser.error("--verify-panel-sync needs the password of --studio-user in ARMOR_STUDIO_PASSWORD or in --studio-password-file")
    pin = _first_line(parser, args.studio_pin_file, "ARMOR_STUDIO_PIN") or None
    broker_password = _first_line(parser, args.mqtt_password_file, "ARMOR_MQTT_PASSWORD") or None
    if not NODE_ID.match(args.panel_id):
        parser.error("--panel-id must be 1-64 characters: lowercase letters, digits, '-' or '_'")
    server = check_server_url(args.server_url)
    panel = SimulatedPanel(node_id=args.panel_id)
    link = PanelLink(panel, args.mqtt_url, username=args.mqtt_user, password=broker_password)
    session = Session(server)
    try:
        session.login(args.studio_user, password)
        link.start()
        time.sleep(3)   # the server must have seen the first state of the panel
        problems, log = verify_panel_sync(session, panel, pin=pin, behaviors=tuple(args.panel_behavior or BEHAVIORS))
        if args.verify_panel_map:
            more, more_log = verify_panel_map(session, panel, pin=pin)
            problems, log = [*problems, *more], [*log, *more_log]
    except (DriverError, PanelLinkError) as error:
        print(f"armor-simulator: {error}", file=sys.stderr)
        return 2
    finally:
        link.stop()
    for line in log:
        print(f"armor-simulator: {line}", file=sys.stderr)
    for problem in problems:
        print(f"armor-simulator: {problem}", file=sys.stderr)
    print("armor-simulator: panel sync: " + ("the server asked the panel for the profile of each mode and reported what the panel answered" if not problems else f"{len(problems)} difference(s) with what must be true"))
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not NODE_ID.match(args.node_id):
        parser.error("--node-id must be 1-64 characters: lowercase letters, digits, '-' or '_'")
    if not 1 <= args.count <= MAX_COUNT:
        parser.error(f"--count must be between 1 and {MAX_COUNT}")
    radars: tuple[str, ...] = ()
    if args.nodes:
        radars = tuple(item.strip() for item in args.nodes.split(","))
        if not 1 <= len(radars) <= 8 or len(set(radars)) != len(radars) or not all(NODE_ID.match(item) for item in radars):
            parser.error("--nodes is 1 to 8 different ids separated by commas (each 1-64 characters: lowercase letters, digits, '-' or '_')")
        if args.node_id != "simulator-1" or args.alarm_scenario or args.replay or args.energy:
            parser.error("--nodes replaces --node-id and cannot be combined with --alarm-scenario (which brings its own nodes), --replay or --energy")
    for option, value in (("--alarm-node", args.alarm_node), ("--network-node", args.network_node)):
        if value is not None and not NODE_ID.match(value):
            parser.error(f"{option} must be 1-64 characters: lowercase letters, digits, '-' or '_'")
    if (args.info or args.alarm_node or args.network_node) and (args.alarm_scenario or args.replay or args.energy):
        parser.error("--info, --alarm-node and --network-node cannot be combined with --alarm-scenario, --replay or --energy")
    if args.mqtt_allow_network and not args.mqtt_url:
        parser.error("--mqtt-allow-network needs --mqtt-url")
    if args.meter_bus_port is not None:
        if args.alarm_scenario or args.replay or args.record or args.server_url or args.solar or args.electrical or args.energy or args.fault != "none" or args.verify_panel_sync:
            parser.error("--meter-bus-port plays the meters and emits no messages: it cannot be combined with --alarm-scenario, --replay, --record, --server-url, --solar, --electrical, --energy, --fault or --verify-panel-sync")
        return _meter_bus(parser, args)
    if args.meter_bus_config or args.meter_bus_allow_network or args.meter_bus_seconds or args.meter_bus_host != "127.0.0.1":
        parser.error("--meter-bus-config, --meter-bus-host, --meter-bus-allow-network and --meter-bus-seconds need --meter-bus-port")
    if args.interval_ms < 0 or args.fault_every < 0 or args.health_every < 0:
        parser.error("--interval-ms, --fault-every and --health-every must not be negative")
    if args.replay and (args.alarm_scenario or args.energy or args.solar or args.electrical or args.count != 1 or args.scenario != "patrol" or args.light != "cycle" or args.node_id != "simulator-1"):
        parser.error("--replay brings its own messages: it cannot be combined with --alarm-scenario, --energy, --solar, --electrical, --count, --scenario, --light or --node-id")
    if args.record and args.replay and args.record.resolve() == args.replay.resolve():
        parser.error("--record and --replay cannot be the same file")
    if args.http_fault != "none" and not args.server_url:
        parser.error("--http-fault spoils the delivery to a server: it needs --server-url")
    if args.http_fault_every < 1 or not 0 <= args.http_latency_ms <= MAX_LATENCY_MS:
        parser.error(f"--http-fault-every must be at least 1 and --http-latency-ms between 0 and {MAX_LATENCY_MS}")
    scenario = None
    if args.alarm_scenario:
        if args.solar or args.electrical or args.energy or args.count != 1 or args.scenario != "patrol" or args.light != "cycle" or args.node_id != "simulator-1":
            parser.error("--alarm-scenario brings its own nodes, light and length: it cannot be combined with --count, --scenario, --light, --node-id, --solar, --electrical or --energy")
        try:
            scenario = load_scenario(args.alarm_scenario)
        except ScenarioError as error:
            print(f"armor-simulator: {args.alarm_scenario.name}: {error}", file=sys.stderr)
            return 2
        if args.check_alarm_scenario:
            print(summary(scenario))
            return 0
        if args.verify_alarms:
            try:
                problems = verify_alarms(scenario, load_observed(args.verify_alarms))
            except ScenarioError as error:
                print(f"armor-simulator: {error}", file=sys.stderr)
                return 2
            for problem in problems:
                print(f"armor-simulator: {problem}", file=sys.stderr)
            print(f"armor-simulator: {scenario.name}: " + ("the system answered as expected" if not problems else f"{len(problems)} difference(s) with what was expected"))
            return 1 if problems else 0
    elif args.check_alarm_scenario or args.verify_alarms or args.drive_server:
        parser.error("--check-alarm-scenario, --verify-alarms and --drive-server need --alarm-scenario")
    energy_config = None
    energy_steps = 0
    if args.energy:
        if args.solar or args.electrical or args.count != 1 or args.alarm_scenario:
            parser.error("--energy replaces --solar and --electrical and sets its own length (--energy-days): it cannot be combined with them, --count or --alarm-scenario")
        if not 0 < args.energy_step_s <= 3600:
            parser.error("--energy-step-s must be between 1 and 3600")
        if not 0 < args.energy_days <= 366:
            parser.error("--energy-days must be more than 0 and at most 366")
        energy_steps = int(args.energy_days * DAY_S // args.energy_step_s)
        if not 1 <= energy_steps <= MAX_STEPS:
            parser.error(f"--energy-days and --energy-step-s give {energy_steps} samples: it must be between 1 and {MAX_STEPS}")
        try:
            energy_config = load_config(args.energy_config)
        except ScenarioError as error:
            print(f"armor-simulator: energy configuration: {error}", file=sys.stderr)
            return 2
    elif args.energy_config:
        parser.error("--energy-config needs --energy")
    if args.verify_panel_sync:
        return _verify_panel_sync(parser, args)
    token = _token(args)
    if bool(args.server_url) != bool(token):
        parser.error("--server-url needs a token (--ingest-token, --ingest-token-file or ARMOR_INGEST_TOKEN), and a token needs --server-url")
    if args.drive_server:
        return _drive(parser, args, scenario, token)
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
    if args.fault != "none" and (args.fault_topic == "solar" and not (args.solar or args.energy or scenario and scenario.power) or args.fault_topic == "electrical" and not (args.electrical or args.energy or scenario and scenario.power)):
        parser.error(f"--fault-topic {args.fault_topic} needs --{args.fault_topic} (there are no such messages to spoil)")
    if args.fault in INVALID_FAULTS and not args.allow_invalid:
        parser.error(f"--fault {args.fault} produces invalid messages on purpose; add --allow-invalid")
    if args.fault in INVALID_FAULTS and args.validate:
        parser.error("--validate and an invalid fault contradict each other")
    server = check_server_url(args.server_url) if args.server_url else None
    validators = _common_validators() if args.validate else None
    sink = None
    if args.mqtt_url:
        try:
            sink = MqttSink(args.mqtt_url, username=args.mqtt_user, password=_first_line(parser, args.mqtt_password_file, "ARMOR_MQTT_PASSWORD") or None, allow_network=args.mqtt_allow_network)
            sink.open()
        except MqttOutError as error:
            print(f"armor-simulator: {error}", file=sys.stderr)
            return 2

    if args.replay:
        try:
            base = iter(load_recording(args.replay))
        except RecordingError as error:
            print(f"armor-simulator: {error}", file=sys.stderr)
            return 2
    elif scenario:
        base = build_stream(scenario, args.health_every)
    elif energy_config:
        base = energy_messages(args.node_id, energy_config, args.seed, energy_steps, args.energy_step_s)
    else:
        base = messages(args.node_id, args.count, args.scenario, args.light, args.seed, args.health_every, args.solar, args.electrical,
                        nodes=radars, info=args.info, alarm_node=args.alarm_node, network_node=args.network_node)
    stream = FAULTS[args.fault](_stamp(base, start_ms), args.fault_every, TOPIC_KINDS[args.fault_topic])
    recording = None
    if args.record:
        try:
            recording = open_for_recording(args.record)
        except RecordingError as error:
            print(f"armor-simulator: {error}", file=sys.stderr)
            if sink:
                sink.close()
            return 2
        stream = tee(stream, recording)
    try:
        return _emit(args, stream, validators, server, token, sink)
    except MqttOutError as error:
        print(f"armor-simulator: {error}", file=sys.stderr)
        return 1
    finally:
        if recording:
            recording.close()
        if sink:
            sink.close()


def _validator_for(topic: str, validators: tuple[Any, ...]) -> Any:
    """The ARMOR-COMMON validator of the topic (node messages, solar, electrical, alarm, network)."""
    node, solar, electrical, alarm, network = validators
    return solar if topic.startswith("armor/solar/") else electrical if topic.startswith("armor/electrical/") else alarm if topic.startswith("armor/alarm/") else network if topic.startswith("armor/network/") else node


def _emit(args: argparse.Namespace, stream: Iterator[Message], validators: tuple[Any, ...] | None, server, token: str, sink: MqttSink | None = None) -> int:
    accepted_invalid = refused = dropped = duplicated = delayed = broker_only = 0
    for number, (topic, payload) in enumerate(stream, start=1):
        if validators:
            try:
                _validator_for(topic, validators)(topic, payload)
            except (ValueError, KeyError, TypeError) as error:
                print(f"armor-simulator: message {number} on {topic} is not valid for ARMOR-COMMON: {error}", file=sys.stderr)
                return 1
        delivery = delivery_plan(args.http_fault, number, args.http_fault_every, args.http_latency_ms)
        if server and delivery.sends == 0:
            dropped += 1
        elif server and kind_of(topic) is None:
            broker_only += 1   # the server takes this message from the broker only
        elif server:
            if delivery.delay_ms:
                delayed += 1
                time.sleep(delivery.delay_ms / 1000)
            duplicated += delivery.sends - 1
            try:
                for _ in range(delivery.sends):
                    post(server, token, kind_of(topic) or "telemetry", payload, per_node=args.per_node_token)
                if args.fault in INVALID_FAULTS and _is_invalid(args.fault, topic, payload):
                    accepted_invalid += 1
            except DeliveryError as error:
                # A deliberately invalid message is expected to be refused: report it and go on.
                if args.fault not in INVALID_FAULTS:
                    print(f"armor-simulator: {error}", file=sys.stderr)
                    return 1
                refused += 1
                print(f"armor-simulator: refused as expected ({error})", file=sys.stderr)
        if sink:
            sink.publish(topic, payload)
        print(json.dumps({"topic": topic, "payload": payload}, separators=(",", ":"), sort_keys=True), flush=True)
        if args.interval_ms:
            time.sleep(args.interval_ms / 1000)
    if broker_only:
        print(f"armor-simulator: {broker_only} message(s) were not delivered over HTTP because the server takes them from the broker only (use --mqtt-url)", file=sys.stderr)
    if sink:
        print(f"armor-simulator: {sink.published} message(s) published on the broker", file=sys.stderr)
    if args.http_fault != "none":
        print(f"armor-simulator: delivery fault {args.http_fault}: {dropped} message(s) not sent, {duplicated} sent twice, {delayed} delayed", file=sys.stderr)
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
