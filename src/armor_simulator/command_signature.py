"""The signature of the critical commands of ARMOR-SERVER (security option `commands.require_sig`), as the nodes check it and as the server makes it.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

A signed command is the JSON of the command with `nonce` as its last field and then, as the very last, `sig`: the payload ends with ``,"sig":"<64 hex digits>"}``. The signature is the
HMAC-SHA256, in hex, of ``armor-command-v2|`` followed by the payload without that ending (a closing brace in its place), with the key of the node; the key of a node is the
HMAC-SHA256 of ``node|`` and its id under a master key that only the server holds. The shared vectors are in ARMOR-COMMON (conformance/signatures/command.json).

This module is both halves, so a bench can make a signed command (`sign_command`, with a master key it is given) and a simulated node can refuse what does not verify (`verify`).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections import deque

PREFIX = "armor-command-v2|"
ENDING = re.compile(r'^(.*),"sig":"([0-9a-f]{64})"\}$', re.S)
NONCE = re.compile(r',"nonce":"([0-9a-f]{16})"\}$')
KEY = re.compile(r"^[0-9a-f]{64}$")
FRESH_MS = 120_000
MEMORY = 32


def node_key(master_hex: str, node_id: str) -> str:
    """The key a node holds: HMAC-SHA256 of the master key over ``node|<id>``."""
    return hmac.new(bytes.fromhex(master_hex), f"node|{node_id}".encode(), hashlib.sha256).hexdigest()


def body_signature(node_key_hex: str, body: str) -> str:
    return hmac.new(bytes.fromhex(node_key_hex), (PREFIX + body).encode(), hashlib.sha256).hexdigest()


def sign_command(master_hex: str, command: dict, nonce: str) -> str:
    """The payload the server publishes for a command: the fields, the nonce, then the signature of those bytes."""
    if not isinstance(command.get("node_id"), str) or not re.fullmatch(r"[0-9a-f]{16}", nonce):
        raise ValueError("a command to sign names its node and has a nonce of sixteen hex digits")
    body = json.dumps({**command, "nonce": nonce}, separators=(",", ":"), ensure_ascii=False)
    return body[:-1] + ',"sig":"' + body_signature(node_key(master_hex, command["node_id"]), body) + '"}'


class NonceMemory:
    """The nonces of the last commands that verified: a repeat is a replay."""

    def __init__(self) -> None:
        self._items: deque[str] = deque(maxlen=MEMORY)

    def seen(self, nonce: str) -> bool:
        return nonce in self._items

    def remember(self, nonce: str) -> None:
        self._items.append(nonce)


def verify(payload: str, node_key_hex: str, memory: NonceMemory, wall_ms: int = 0) -> str:
    """"ok", or why the payload is refused: no_key, no_signature, no_nonce, bad_signature, replay or stale. `wall_ms` is the time of the node in ms (0: no valid clock)."""
    if not KEY.match(node_key_hex or ""):
        return "no_key"
    match = ENDING.match(payload)
    if not match:
        return "no_signature"
    body, sig = match.group(1) + "}", match.group(2)
    nonce = NONCE.search(body)
    if not nonce:
        return "no_nonce"
    if not hmac.compare_digest(body_signature(node_key_hex, body), sig):
        return "bad_signature"
    if memory.seen(nonce.group(1)):
        return "replay"
    if wall_ms > 0:
        stamp = re.search(r'"timestamp_ms":(\d{1,15})', body)
        if not stamp or abs(int(stamp.group(1)) - wall_ms) > FRESH_MS:
            return "stale"
    memory.remember(nonce.group(1))
    return "ok"
