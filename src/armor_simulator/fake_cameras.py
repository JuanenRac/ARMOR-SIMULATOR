"""Fake IP cameras over HTTP: a snapshot address that answers like a cheap camera does, so the code that fetches pictures can be tried without a camera.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

The other generators of this package emit what a NODE publishes. This one plays the CAMERAS: it listens on a TCP port and answers `GET <path>` with a still picture
(a grey PNG, which is what the server and the movement service accept besides JPEG) that changes with the clock the way a scene does: nothing moves (`still`), a person
walks across the picture (`walker`), the light flickers (`flicker`), a night picture with sensor noise (`dark`) or a tree that waves in one corner (`waving-tree`).
A camera can ask for a Basic or a Digest login (MD5 and SHA-256, qop=auth, as the cameras do) and can be made to misbehave on purpose (`fault`: an error status,
a body that is not a picture, an empty body, a late answer), so the server's camera code (the login, the answer types, the size and time limits) is exercised.

It is read only, listens on the loopback unless told otherwise and keeps no state beyond the counters. It speaks no RTSP: the pictures are those of the snapshot address; a
picture from a stream needs a real camera or a stream server. Every setting (the cameras, their paths, scenes, logins and faults) lives in a JSON file (`docs/FAKE_CAMERAS.md`);
the defaults are one camera, `/snapshot.png`, with a walker and no login. The passwords never live in the file: they come from the environment or a file named on the command line.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import struct
import threading
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

SCHEMA = "armor-fake-cameras/1"
SCENES = ("still", "walker", "flicker", "dark", "waving-tree")
AUTHS = ("none", "basic", "digest", "digest-sha256")
PTZ_ROUTE = "/cgi-bin/hi3510/ptzctrl.cgi"
PTZ_ACTIONS = ("left", "right", "up", "down", "zoomin", "zoomout", "stop")
FAULTS = ("none", "status", "not-a-picture", "empty", "late", "oversize")
MAX_FILE_BYTES = 64 * 1024
MAX_CAMERAS = 16
MAX_SIDE = 640
MAX_LATE_S = 30.0
LOOPBACK = ("127.0.0.1", "::1", "localhost")
REALM = "armor-fake-camera"
PATH_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/._-")


class FakeCameraError(ValueError):
    """A camera file that is not understood, or an address that is not allowed."""


@dataclass(frozen=True)
class Camera:
    id: str
    path: str = "/snapshot.png"
    scene: str = "walker"
    auth: str = "none"
    username: str = "admin"
    fault: str = "none"
    fault_every: int = 1            # the fault strikes every Nth request of the camera (1: always)
    late_s: float = 2.0             # the delay of the fault `late`
    seconds_per_pass: float = 10.0  # how long the walker takes to cross the picture
    ptz: bool = False               # the camera answers the Hi3510 move command (the first camera with this flag takes the moves of its port)


@dataclass(frozen=True)
class CameraConfig:
    width: int = 160
    height: int = 90
    cameras: tuple[Camera, ...] = field(default_factory=lambda: (Camera(id="cam-1"),))


def _text(value: object, name: str, limit: int) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise FakeCameraError(f"{name} must be a text of 1 to {limit} characters")
    return value


def _number(value: object, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high or value != value:
        raise FakeCameraError(f"{name} must be a number between {low} and {high}")
    return float(value)


def parse_config(document: object) -> CameraConfig:
    if not isinstance(document, dict):
        raise FakeCameraError("the file must hold a JSON object")
    if document.get("schema") != SCHEMA:
        raise FakeCameraError(f'"schema" must be "{SCHEMA}"')
    width = int(_number(document.get("width", 160), "width", 16, MAX_SIDE))
    height = int(_number(document.get("height", 90), "height", 16, MAX_SIDE))
    raw = document.get("cameras")
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_CAMERAS:
        raise FakeCameraError(f'"cameras" must be a list of 1 to {MAX_CAMERAS} cameras')
    cameras: list[Camera] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise FakeCameraError(f"camera {index + 1} must be an object")
        label = f"camera {index + 1}"
        path = _text(entry.get("path", "/snapshot.png"), f"{label} path", 120)
        if not path.startswith("/") or "//" in path or ".." in path or not set(path) <= PATH_OK:
            raise FakeCameraError(f"{label} path must start with / and use letters, digits and / . _ - only")
        scene, auth, fault = entry.get("scene", "walker"), entry.get("auth", "none"), entry.get("fault", "none")
        if scene not in SCENES:
            raise FakeCameraError(f"{label} scene must be one of {', '.join(SCENES)}")
        if auth not in AUTHS:
            raise FakeCameraError(f"{label} auth must be one of {', '.join(AUTHS)}")
        if fault not in FAULTS:
            raise FakeCameraError(f"{label} fault must be one of {', '.join(FAULTS)}")
        cameras.append(Camera(
            id=_text(entry.get("id", f"cam-{index + 1}"), f"{label} id", 64), path=path, scene=scene, auth=auth,
            username=_text(entry.get("username", "admin"), f"{label} username", 64), fault=fault,
            fault_every=int(_number(entry.get("fault_every", 1), f"{label} fault_every", 1, 1000)),
            late_s=_number(entry.get("late_s", 2.0), f"{label} late_s", 0, MAX_LATE_S),
            seconds_per_pass=_number(entry.get("seconds_per_pass", 10.0), f"{label} seconds_per_pass", 1, 3600), ptz=entry.get("ptz", False) is True))
    if len({camera.path for camera in cameras}) != len(cameras):
        raise FakeCameraError("two cameras share a path")
    if len({camera.id for camera in cameras}) != len(cameras):
        raise FakeCameraError("two cameras share an id")
    return CameraConfig(width=width, height=height, cameras=tuple(cameras))


def _refuse_constant(name: str):
    raise FakeCameraError(f"the value {name} is not JSON")


def load_config(path: Path | None) -> CameraConfig:
    if path is None:
        return CameraConfig()
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            raise FakeCameraError(f"the file is larger than {MAX_FILE_BYTES // 1024} KiB")
        return parse_config(json.loads(path.read_text(encoding="utf-8"), parse_constant=_refuse_constant))
    except OSError as error:
        raise FakeCameraError(f"cannot read {path}: {error.strerror or error}") from None
    except json.JSONDecodeError as error:
        raise FakeCameraError(f"{path} is not JSON: {error}") from None


def png_grey(width: int, height: int, rows: list[bytes]) -> bytes:
    """An 8-bit grey PNG from `height` rows of `width` bytes."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + row for row in rows)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def _noise(x: int, y: int, t: int) -> int:
    """A repeatable value 0..255 for a pixel at a step of time (no random module: the same call gives the same picture)."""
    value = (x * 73856093) ^ (y * 19349663) ^ (t * 83492791)
    return (value * 2654435761 >> 7) & 0xFF


def scene_rows(scene: str, width: int, height: int, at: float, seconds_per_pass: float = 10.0) -> list[bytes]:
    """The picture of a scene `at` seconds after the start: a gradient room, and what each scene adds."""
    base = [[40 + (110 * x) // max(1, width - 1) + (30 * y) // max(1, height - 1) for x in range(width)] for y in range(height)]
    if scene == "walker":
        phase = (at % seconds_per_pass) / seconds_per_pass
        centre = int(-0.1 * width + phase * 1.2 * width)
        half = max(2, width // 16)
        top = height // 4
        for y in range(top, min(height, top + height // 2)):
            for x in range(max(0, centre - half), min(width, centre + half)):
                base[y][x] = 235 if y < top + height // 8 else 15      # a bright head, a dark body
    elif scene == "flicker":
        shift = int(40 * math.sin(at * 2 * math.pi * 3))
        base = [[min(255, max(0, v + shift)) for v in row] for row in base]
    elif scene == "dark":
        step = int(at * 10)
        base = [[min(255, max(0, v // 8 + (_noise(x, y, step) % 6))) for x, v in enumerate(row)] for y, row in enumerate(base)]
    elif scene == "waving-tree":
        sway = int(3 * math.sin(at * 2 * math.pi * 0.7))
        for y in range(height // 2, height):
            for x in range(width * 3 // 4, width):
                base[y][x] = 60 + 90 * (((x + sway * (y - height // 2) // 4) // 3) % 2)
    return [bytes(row) for row in base]


def _md5_or_sha(algorithm: str, text: str) -> str:
    return hashlib.new("sha256" if algorithm == "SHA-256" else "md5", text.encode()).hexdigest()


@dataclass
class Counters:
    requests: int = 0
    pictures: int = 0
    challenged: int = 0
    refused_logins: int = 0
    faulted: int = 0
    not_found: int = 0


class FakeCameras:
    """The cameras: what each path answers, the logins and the faults. `clock` gives seconds since the start (the tests give their own)."""

    def __init__(self, config: CameraConfig, password: str = "", clock: Callable[[], float] | None = None, sleep: Callable[[float], None] = time.sleep) -> None:
        self.config = config
        self._password = password
        self._clock = clock or (lambda: time.monotonic())
        self._start = self._clock()
        self._sleep = sleep
        self._by_path = {camera.path: camera for camera in config.cameras}
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}
        self._nonces: dict[str, float] = {}
        self.counters = Counters()
        self.moves: list[tuple[str, str]] = []     # (camera id, action) of every move the fake pan-tilt head was told
        for camera in config.cameras:
            if camera.auth != "none" and not password:
                raise FakeCameraError(f"camera {camera.id} asks for a login: give the password with --camera-password-file or ARMOR_FAKE_CAMERA_PASSWORD")

    def picture(self, camera: Camera) -> bytes:
        rows = scene_rows(camera.scene, self.config.width, self.config.height, self._clock() - self._start, camera.seconds_per_pass)
        return png_grey(self.config.width, self.config.height, rows)

    def _challenge(self, camera: Camera) -> str:
        with self._lock:
            now = self._clock()
            self._nonces = {nonce: born for nonce, born in self._nonces.items() if now - born < 300}
            nonce = secrets.token_hex(16)
            self._nonces[nonce] = now
        if camera.auth == "basic":
            return f'Basic realm="{REALM}"'
        algorithm = "SHA-256" if camera.auth == "digest-sha256" else "MD5"
        return f'Digest realm="{REALM}", qop="auth", nonce="{nonce}", algorithm={algorithm}'

    @staticmethod
    def _parameters(header: str) -> dict[str, str]:
        found: dict[str, str] = {}
        import re
        for match in re.finditer(r'([a-z]+)=(?:"([^"]*)"|([^\s,]+))', header, re.IGNORECASE):
            found[match.group(1).lower()] = match.group(2) if match.group(2) is not None else match.group(3)
        return found

    def login_ok(self, camera: Camera, header: str | None, method: str) -> bool:
        if camera.auth == "none":
            return True
        if not header:
            return False
        if camera.auth == "basic":
            import base64
            if not header.startswith("Basic "):
                return False
            try:
                user, _, password = base64.b64decode(header[6:], validate=True).decode().partition(":")
            except ValueError:
                return False
            return secrets.compare_digest(user, camera.username) and secrets.compare_digest(password, self._password)
        if not header.lower().startswith("digest "):
            return False
        p = self._parameters(header[7:])
        nonce = p.get("nonce", "")
        with self._lock:
            known = nonce in self._nonces
        algorithm = "SHA-256" if camera.auth == "digest-sha256" else "MD5"
        if not known or p.get("username") != camera.username or p.get("realm") != REALM or p.get("qop") != "auth" or (p.get("algorithm") or "MD5").upper() != algorithm:
            return False
        ha1 = _md5_or_sha(algorithm, f"{camera.username}:{REALM}:{self._password}")
        ha2 = _md5_or_sha(algorithm, f"{method}:{p.get('uri', '')}")
        expected = _md5_or_sha(algorithm, f"{ha1}:{nonce}:{p.get('nc', '')}:{p.get('cnonce', '')}:auth:{ha2}")
        return secrets.compare_digest(expected, p.get("response", ""))

    def _move(self, path: str, header: str | None, method: str) -> tuple[int, dict[str, str], bytes]:
        """The move command of a Hi3510 unit: `[Succeed]set ok.` when the login is right and the action is one of the known; the head itself is only a list of what it was told."""
        head = next((camera for camera in self.config.cameras if camera.ptz), None)
        if head is None:
            return 404, {"Content-Type": "text/plain"}, b"not found"
        if not self.login_ok(head, header, method):
            with self._lock:
                self.counters.refused_logins += 1 if header else 0
                self.counters.challenged += 0 if header else 1
            return 401, {"Content-Type": "text/plain", "WWW-Authenticate": self._challenge(head)}, b"login needed"
        action = parse_qs(urlsplit(path).query).get("-act", [""])[0]
        if action not in PTZ_ACTIONS:
            return 400, {"Content-Type": "text/plain"}, b"[Error]unknown action"
        with self._lock:
            self.moves.append((head.id, action))
        return 200, {"Content-Type": "text/plain"}, b"[Succeed]set ok."

    def answer(self, path: str, header: str | None, method: str = "GET") -> tuple[int, dict[str, str], bytes]:
        """The status, headers and body for one request, with the delay of a `late` fault already waited."""
        route = path.split("?", 1)[0]
        with self._lock:
            self.counters.requests += 1
        if route == PTZ_ROUTE:
            return self._move(path, header, method)
        camera = self._by_path.get(route)
        if camera is None:
            with self._lock:
                self.counters.not_found += 1
            return 404, {"Content-Type": "text/plain"}, b"not found"
        if not self.login_ok(camera, header, method):
            with self._lock:
                if header:
                    self.counters.refused_logins += 1
                else:
                    self.counters.challenged += 1
            return 401, {"Content-Type": "text/plain", "WWW-Authenticate": self._challenge(camera)}, b"login needed"
        with self._lock:
            self._counts[camera.id] = self._counts.get(camera.id, 0) + 1
            strikes = camera.fault != "none" and self._counts[camera.id] % camera.fault_every == 0
            if strikes:
                self.counters.faulted += 1
        if strikes:
            if camera.fault == "status":
                return 500, {"Content-Type": "text/plain"}, b"camera error"
            if camera.fault == "not-a-picture":
                return 200, {"Content-Type": "text/html"}, b"<html>camera is busy</html>"
            if camera.fault == "empty":
                return 200, {"Content-Type": "image/png"}, b""
            if camera.fault == "oversize":
                return 200, {"Content-Type": "image/png"}, self.picture(camera) + b"\x00" * (4 * 1024 * 1024)
            self._sleep(camera.late_s)
        with self._lock:
            self.counters.pictures += 1
        return 200, {"Content-Type": "image/png", "Cache-Control": "no-store"}, self.picture(camera)


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args) -> None:       # nothing on the console: a camera does not talk
        pass

    def do_GET(self) -> None:
        cameras: FakeCameras = self.server.cameras          # type: ignore[attr-defined]
        status, headers, body = cameras.answer(self.path, self.headers.get("Authorization"), "GET")
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass

    def _refuse(self) -> None:
        body = b"read only"
        self.send_response(405)
        self.send_header("Allow", "GET")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    do_POST = do_PUT = do_DELETE = do_PATCH = _refuse


class FakeCameraServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(cameras: FakeCameras, host: str = "127.0.0.1", port: int = 0) -> tuple[FakeCameraServer, threading.Thread]:
    """Listens on a port (0: any free one) and answers in a thread; the caller stops it with `stop(server)`."""
    if not 0 <= port <= 65535:
        raise FakeCameraError("the port must be between 0 and 65535")
    server = FakeCameraServer((host, port), _Handler)
    server.cameras = cameras                      # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, name="fake-cameras", daemon=True)
    thread.start()
    return server, thread


def stop(server: FakeCameraServer) -> None:
    server.shutdown()
    server.server_close()


def read_password(file: Path | None) -> str:
    """The camera password: a file (first line) or ARMOR_FAKE_CAMERA_PASSWORD; never a command-line argument."""
    if file is not None:
        try:
            if file.stat().st_size > 4096:
                raise FakeCameraError("the password file is larger than 4 KiB")
            return file.read_text(encoding="utf-8").splitlines()[0].strip() if file.stat().st_size else ""
        except OSError as error:
            raise FakeCameraError(f"cannot read {file}: {error.strerror or error}") from None
    return os.environ.get("ARMOR_FAKE_CAMERA_PASSWORD", "")
