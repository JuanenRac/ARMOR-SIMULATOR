"""Delivery of simulated messages to an explicitly chosen ARMOR-SERVER.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

ROUTES = {"telemetry": "/api/v1/telemetry", "health": "/api/v1/health", "solar": "/api/v1/solar", "electrical": "/api/v1/electrical/readings"}


class DeliveryError(RuntimeError):
    """The server refused or could not be reached."""


def check_server_url(server_url: str) -> str:
    """Only a plain http(s) origin is accepted: no credentials, path or query in the URL."""
    parsed = urlparse(server_url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.path not in ("", "/") or parsed.query:
        raise ValueError("--server-url must be a plain http(s) origin such as http://127.0.0.1:8080")
    return f"{parsed.scheme}://{parsed.netloc}"


def post(server_url: str, token: str, kind: str, payload: dict, timeout: float = 5.0, attempts: int = 3, pause_s: float = 0.5) -> int:
    """POST one message with the ingest token. Returns the HTTP status.

    A 4xx answer is final (the message or token is wrong, retrying cannot help).
    A network error or 5xx is retried a few times with a short pause.
    """
    if kind not in ROUTES:
        raise ValueError(f"unknown message kind {kind!r}")
    request = Request(
        f"{server_url.rstrip('/')}{ROUTES[kind]}", data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    last = "no attempt was made"
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - the scheme is checked by check_server_url
                if response.status != 202:
                    raise DeliveryError(f"server returned {response.status}")
                return response.status
        except HTTPError as error:
            error.close()
            if error.code < 500:
                raise DeliveryError(f"server rejected the {kind}: HTTP {error.code}") from error
            last = f"HTTP {error.code}"
        except URLError:
            last = "server is unreachable"
        if attempt + 1 < attempts:
            time.sleep(pause_s)
    raise DeliveryError(f"{last} after {attempts} attempts")
