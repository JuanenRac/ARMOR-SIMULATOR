"""Faults of the delivery to a server, not of the messages.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

``faults.py`` spoils what is said; these spoil how it reaches the server: a
slow link, a message that never arrives, the same message sent twice. They are
deterministic (every Nth message) and only apply with ``--server-url``.
"""

from __future__ import annotations

from dataclasses import dataclass

HTTP_FAULTS = ("none", "latency", "drop", "duplicate")
MAX_LATENCY_MS = 60_000


@dataclass(frozen=True)
class Delivery:
    sends: int          # how many times the message is posted (0 = never)
    delay_ms: int       # pause before posting


def plan(fault: str, number: int, every: int, latency_ms: int) -> Delivery:
    """What happens to the `number`th message (counted from 1)."""
    if fault == "none" or every < 1 or number % every != 0:
        return Delivery(1, 0)
    if fault == "latency":
        return Delivery(1, latency_ms)
    if fault == "drop":
        return Delivery(0, 0)
    if fault == "duplicate":
        return Delivery(2, 0)
    raise ValueError(f"unknown delivery fault {fault!r}")
