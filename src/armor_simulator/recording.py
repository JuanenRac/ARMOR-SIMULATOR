"""Record the messages a run emits and play them again later.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

A recording is a JSON-lines file, one ``{"topic": ..., "payload": {...}}`` per
line: exactly what the simulator prints. It holds only simulated messages, so
there is no secret in it. Reading refuses the whole file on any bad line, a
file that is too big or a value that is not JSON (NaN, Infinity).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import IO

from .faults import Message

MAX_BYTES = 64 * 1024 * 1024
MAX_MESSAGES = 1_000_000


class RecordingError(ValueError):
    """The recording cannot be used: nothing is played from it."""


def _no_constants(name: str):
    raise RecordingError(f"{name} is not allowed in a recording")


def tee(stream: Iterable[Message], out: IO[str]) -> Iterator[Message]:
    """Passes the messages on and writes each one to `out` as it goes by."""
    for topic, payload in stream:
        out.write(json.dumps({"topic": topic, "payload": payload}, separators=(",", ":"), sort_keys=True) + "\n")
        yield topic, payload


def open_for_recording(path: Path) -> IO[str]:
    """Creates the file; an existing file is never overwritten."""
    try:
        return path.open("x", encoding="utf-8", newline="\n")
    except FileExistsError:
        raise RecordingError(f"{path} already exists: give another name, nothing is overwritten") from None
    except OSError as error:
        raise RecordingError(f"cannot write {path}: {error}") from error


def load_recording(path: Path, max_bytes: int = MAX_BYTES) -> list[Message]:
    try:
        if path.stat().st_size > max_bytes:
            raise RecordingError(f"{path.name} is over {max_bytes} bytes")
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise RecordingError(f"cannot read {path}: {error}") from error
    except UnicodeDecodeError:
        raise RecordingError(f"{path.name} is not UTF-8 text") from None
    messages: list[Message] = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line, parse_constant=_no_constants)
        except ValueError as error:
            raise RecordingError(f"line {number}: not JSON ({error})") from error
        if not isinstance(record, dict) or set(record) != {"topic", "payload"}:
            raise RecordingError(f"line {number}: must be an object with topic and payload only")
        topic, payload = record["topic"], record["payload"]
        if not isinstance(topic, str) or not topic.startswith("armor/") or not isinstance(payload, dict):
            raise RecordingError(f"line {number}: topic must be an armor/... string and payload an object")
        messages.append((topic, payload))
        if len(messages) > MAX_MESSAGES:
            raise RecordingError(f"more than {MAX_MESSAGES} messages")
    if not messages:
        raise RecordingError(f"{path.name} has no messages")
    return messages
