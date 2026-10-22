"""Repeatable faults, so consumers and clients can be tested against a misbehaving field.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

A fault turns the stream of ``(topic, payload)`` messages into a different
stream. Every fault is deterministic: the same inputs give the same output.
Faults that produce *invalid* messages are only meant for negative testing and
are marked so a caller never publishes them by accident.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from copy import deepcopy

Message = tuple[str, dict]
# Which messages a fault looks at (by topic); the others go through untouched. The count `every` is of the messages it looks at.
Match = Callable[[str], bool]
Fault = Callable[[Iterable[Message], int, Match], Iterator[Message]]


def every_topic(_topic: str) -> bool:
    return True


TOPIC_KINDS: dict[str, Match] = {
    "all": every_topic,
    "telemetry": lambda topic: topic.endswith("/telemetry"),
    "health": lambda topic: topic.endswith("/health"),
    "solar": lambda topic: topic.startswith("armor/solar/"),
    "electrical": lambda topic: topic.startswith("armor/electrical/"),
}

# Faults whose output violates the contract on purpose.
INVALID_FAULTS = {"corrupt-lux", "unknown-field", "oversized-targets"}


def none(messages: Iterable[Message], _every: int, _match: Match = every_topic) -> Iterator[Message]:
    yield from messages


def node_silent(messages: Iterable[Message], every: int, match: Match = every_topic) -> Iterator[Message]:
    """The node stops talking after `every` messages (of the kind looked at): it must go stale, then offline. The other kinds go on."""
    seen = 0
    for message in messages:
        if match(message[0]):
            if seen >= every:
                continue
            seen += 1
        yield message


def out_of_order(messages: Iterable[Message], every: int, match: Match = every_topic) -> Iterator[Message]:
    """Every `every`th message carries an older timestamp: the server must ignore it."""
    index = -1
    for topic, payload in messages:
        if match(topic):
            index += 1
            if every and index and index % every == 0:
                payload = deepcopy(payload)
                payload["timestamp_ms"] = max(0, payload["timestamp_ms"] - 60_000)
        yield topic, payload


def duplicates(messages: Iterable[Message], every: int, match: Match = every_topic) -> Iterator[Message]:
    """Every `every`th message is delivered twice (MQTT QoS 1 does this)."""
    index = -1
    for message in messages:
        yield message
        if match(message[0]):
            index += 1
            if every and index % every == 0:
                yield message


def flapping(messages: Iterable[Message], every: int, match: Match = every_topic) -> Iterator[Message]:
    """The node reports itself offline for one health message in every `every`."""
    seen = 0
    for topic, payload in messages:
        if topic.endswith("/health") and match(topic):
            seen += 1
            if every and seen % every == 0:
                payload = {**payload, "online": False}
        yield topic, payload


def corrupt_lux(messages: Iterable[Message], every: int, match: Match = every_topic) -> Iterator[Message]:
    """Invalid: lux above the sensor limit."""
    index = -1
    for topic, payload in messages:
        if match(topic):
            index += 1
            if every and topic.endswith("/telemetry") and index % every == 0:
                payload = {**payload, "lux": 1e9}
        yield topic, payload


def unknown_field(messages: Iterable[Message], every: int, match: Match = every_topic) -> Iterator[Message]:
    """Invalid: a field the contract does not define."""
    index = -1
    for topic, payload in messages:
        if match(topic):
            index += 1
            if every and index % every == 0:
                payload = {**payload, "firmware_debug": True}
        yield topic, payload


def oversized_targets(messages: Iterable[Message], every: int, match: Match = every_topic) -> Iterator[Message]:
    """Invalid: more than the 15 tracks three radars can report."""
    filler = {"sensor_id": 1, "track_id": 1, "x_mm": 0, "y_mm": 1000, "speed_mm_s": 0}
    index = -1
    for topic, payload in messages:
        if match(topic):
            index += 1
            if every and topic.endswith("/telemetry") and index % every == 0:
                payload = {**payload, "targets": [dict(filler, track_id=n + 1) for n in range(16)]}
        yield topic, payload


FAULTS: dict[str, Fault] = {
    "none": none, "node-silent": node_silent, "out-of-order": out_of_order, "duplicates": duplicates, "flapping": flapping,
    "corrupt-lux": corrupt_lux, "unknown-field": unknown_field, "oversized-targets": oversized_targets,
}
