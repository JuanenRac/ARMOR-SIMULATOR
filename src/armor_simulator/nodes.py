"""The other nodes of the system, simulated: the information a field node sends about itself, an alarm panel and a network watcher.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

With them a console (Studio, the app) can be tried whole without hardware: the radar node of `scenarios.py`, plus a panel that arms, counts down, sounds and is disarmed again
and a watcher of the local network whose devices come and go. Everything is a function of the sample number and the node id, so two runs are identical. The panel here walks a
fixed timeline (it does not answer commands; for that see `panel_sim.py`) and the dates inside the network message are counted from the start of the run, like the sample number.
Nothing here says how a real panel or watcher will behave.
"""

from __future__ import annotations

import zlib

ALARM_PERIOD = 120
# (second of the cycle, event, zone): the timeline the panel walks, every ALARM_PERIOD samples
_ALARM_TIMELINE = (
    (20, "exit_delay_started", None), (25, "armed", None), (70, "entry_delay_started", "front-door"), (75, "alarm", "window"), (83, "siren_timed_out", None), (85, "disarmed", None),
)
NETWORK_PERIOD = 60


def _octet(node_id: str, low: int = 20, high: int = 200) -> int:
    return low + zlib.crc32(node_id.encode()) % (high - low)


def info(node_id: str, sample: int, firmware: str = "0.0.0") -> dict:
    """What a field node says about itself (armor/node/<id>/info): a name, the firmware, an address on a private network and the port of its web panel."""
    return {"node_id": node_id, "timestamp_ms": sample * 1000, "name": f"Simulated {node_id}"[:48], "firmware": firmware, "ip": f"192.168.0.{_octet(node_id)}", "port": 80}


def alarm_state(node_id: str, sample: int) -> dict:
    """The state of a simulated alarm panel (armor/alarm/<id>/state): disarmed, a delay to leave, armed, a person at the door, the siren, and disarmed again - 120 samples in all."""
    at = sample % ALARM_PERIOD
    if at < 20 or at >= 85:
        phase, mode = "disarmed", "disarmed"
    elif at < 25:
        phase, mode = "exit_delay", "away"
    elif at < 70:
        phase, mode = "armed", "away"
    elif at < 75:
        phase, mode = "entry_delay", "away"
    else:
        phase, mode = "alarm", "away"
    siren = phase == "alarm" and at < 83
    triggered = {"front-door"} if phase == "entry_delay" else {"window"} if phase == "alarm" else set()
    zones = [
        {"id": "front-door", "name": "Front door", "kind": "entry", "state": "triggered" if "front-door" in triggered else "normal", "bypassed": False},
        {"id": "window", "name": "Living room window", "kind": "instant", "state": "triggered" if "window" in triggered else "normal", "bypassed": False},
    ]
    events = [{"ago_s": at - when, "kind": kind, **({"zone": zone} if zone else {})} for when, kind, zone in _ALARM_TIMELINE if when <= at]
    return {
        "kind": "alarm", "node_id": node_id, "timestamp_ms": sample * 1000, "phase": phase, "mode": mode, "siren": siren, "locked_out": False, "commands_enabled": True,
        "zones": zones, "open_zones": [zone["id"] for zone in zones if zone["state"] != "normal"], "events": events, "arm_profiles": True,
    }


def network_state(node_id: str, sample: int) -> dict:
    """The state of a simulated network watcher (armor/network/<id>/state): the router, a laptop that is on and off, a printer that joins half way through and the internet."""
    now = sample * 1000
    at = sample % NETWORK_PERIOD
    laptop_on = at < 40
    devices = [
        {"id": "02:00:00:00:00:01", "ip": "192.168.0.1", "mac": "02:00:00:00:00:01", "vendor": "Simulated router", "hostname": "router", "kind": "router", "online": True,
         "first_seen_ms": 0, "last_seen_ms": now, "latency_ms": 1.4, "ports": [{"port": 80, "proto": "tcp", "service": "http"}]},
        {"id": "02:00:00:00:00:02", "ip": "192.168.0.23", "mac": "02:00:00:00:00:02", "hostname": "laptop", "kind": "computer", "online": laptop_on,
         "first_seen_ms": 0, "last_seen_ms": now - (0 if laptop_on else (at - 39) * 1000)},
    ]
    events = []
    if at >= 30:
        devices.append({"id": "02:00:00:00:00:03", "ip": "192.168.0.31", "mac": "02:00:00:00:00:03", "hostname": "printer", "kind": "printer", "online": True,
                        "first_seen_ms": now - (at - 30) * 1000, "last_seen_ms": now})
        events.append({"id": f"new-{sample - at + 30}", "kind": "new_device", "at_ms": now - (at - 30) * 1000, "device_id": "02:00:00:00:00:03", "detail": "A device that was never seen has joined the network"})
    return {
        "kind": "network", "node_id": node_id, "timestamp_ms": now,
        "interface": {"name": "Ethernet", "ip": "192.168.0.10", "cidr": "192.168.0.0/24", "gateway": "192.168.0.1", "rx_bps": 1_000_000 + at * 10_000, "tx_bps": 300_000 + at * 2_000},
        "internet": {"state": "up", "since_ms": 0, "gateway_ok": True, "latency_ms": 12.5, "loss_percent": 0.0,
                     "probes": [{"target": "1.1.1.1", "kind": "tcp", "ok": True, "latency_ms": 11.2}], "outages_24h": 0, "downtime_24h_s": 0},
        "devices": devices, "events": events, "scan": {"last_ms": now, "hosts": 254, "duration_ms": 9000},
    }
