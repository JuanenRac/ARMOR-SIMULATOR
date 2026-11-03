"""The fake IP cameras: the pictures, the logins, the faults, the refusals and the command line."""
import base64
import hashlib
import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from armor_simulator.cli import build_parser, main
from armor_simulator.fake_cameras import Camera, CameraConfig, FakeCameraError, FakeCameras, parse_config, scene_rows, serve, stop

PASSWORD = "test-password-not-real"


def decode_png(data: bytes) -> tuple[int, int, list[bytes]]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, width, height, idat = 8, 0, 0, b""
    while pos < len(data):
        length = int.from_bytes(data[pos:pos + 4], "big")
        kind, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + length]
        assert int.from_bytes(data[pos + 8 + length:pos + 12 + length], "big") == zlib.crc32(kind + body) & 0xFFFFFFFF
        if kind == b"IHDR":
            width, height = int.from_bytes(body[:4], "big"), int.from_bytes(body[4:8], "big")
        elif kind == b"IDAT":
            idat += body
        pos += 12 + length
    raw = zlib.decompress(idat)
    return width, height, [raw[i * (width + 1) + 1:(i + 1) * (width + 1)] for i in range(height)]


def changed(a: list[bytes], b: list[bytes]) -> int:
    return sum(1 for ra, rb in zip(a, b, strict=True) for x, y in zip(ra, rb, strict=True) if abs(x - y) > 20)


class Clock:
    def __init__(self) -> None:
        self.now = 100.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)


def digest_header(challenge: str, user: str, password: str, uri: str, algorithm: str) -> str:
    h = (lambda t: hashlib.sha256(t.encode()).hexdigest()) if algorithm == "SHA-256" else (lambda t: hashlib.md5(t.encode()).hexdigest())
    import re
    realm = re.search(r'realm="([^"]*)"', challenge).group(1)
    nonce = re.search(r'nonce="([^"]*)"', challenge).group(1)
    ha1, ha2 = h(f"{user}:{realm}:{password}"), h(f"GET:{uri}")
    response = h(f"{ha1}:{nonce}:00000001:abcd:auth:{ha2}")
    return f'Digest username="{user}", realm="{realm}", nonce="{nonce}", uri="{uri}", qop=auth, nc=00000001, cnonce="abcd", response="{response}", algorithm={algorithm}'


class SceneTests(unittest.TestCase):
    def test_still_does_not_move_and_walker_does(self):
        a, b = scene_rows("still", 160, 90, 0.0), scene_rows("still", 160, 90, 5.0)
        self.assertEqual(a, b)
        self.assertGreater(changed(scene_rows("walker", 160, 90, 1.0), scene_rows("walker", 160, 90, 3.0)), 100)

    def test_other_scenes_change_and_dark_is_dark(self):
        self.assertGreater(changed(scene_rows("flicker", 160, 90, 0.0), scene_rows("flicker", 160, 90, 0.08)), 1000)
        dark = scene_rows("dark", 160, 90, 0.0)
        self.assertLess(sum(sum(r) for r in dark) / (160 * 90), 40)
        self.assertNotEqual(scene_rows("waving-tree", 160, 90, 0.0), scene_rows("waving-tree", 160, 90, 0.4))

    def test_same_time_same_picture(self):
        self.assertEqual(scene_rows("dark", 64, 36, 2.0), scene_rows("dark", 64, 36, 2.0))


class AnswerTests(unittest.TestCase):
    def cams(self, *cameras: Camera, password: str = PASSWORD) -> tuple[FakeCameras, Clock]:
        clock = Clock()
        return FakeCameras(CameraConfig(width=64, height=36, cameras=cameras), password, clock, clock.sleep), clock

    def test_picture_is_a_valid_png_of_the_size(self):
        cams, clock = self.cams(Camera(id="a"))
        status, headers, body = cams.answer("/snapshot.png", None)
        self.assertEqual((status, headers["Content-Type"]), (200, "image/png"))
        width, height, rows = decode_png(body)
        self.assertEqual((width, height, len(rows)), (64, 36, 36))
        clock.now += 3
        self.assertGreater(changed(rows, decode_png(cams.answer("/snapshot.png", None)[2])[2]), 10)

    def test_unknown_path_is_404_and_counted(self):
        cams, _ = self.cams(Camera(id="a"))
        self.assertEqual(cams.answer("/other", None)[0], 404)
        self.assertEqual(cams.counters.not_found, 1)

    def test_basic_login(self):
        cams, _ = self.cams(Camera(id="a", auth="basic"))
        status, headers, _ = cams.answer("/snapshot.png", None)
        self.assertEqual(status, 401)
        self.assertTrue(headers["WWW-Authenticate"].startswith("Basic"))
        good = "Basic " + base64.b64encode(f"admin:{PASSWORD}".encode()).decode()
        bad = "Basic " + base64.b64encode(b"admin:wrong").decode()
        self.assertEqual(cams.answer("/snapshot.png", good)[0], 200)
        self.assertEqual(cams.answer("/snapshot.png", bad)[0], 401)
        self.assertEqual((cams.counters.challenged, cams.counters.refused_logins), (1, 1))

    def test_digest_logins_md5_and_sha256(self):
        for auth, algorithm in (("digest", "MD5"), ("digest-sha256", "SHA-256")):
            cams, _ = self.cams(Camera(id="a", auth=auth))
            status, headers, _ = cams.answer("/snapshot.png", None)
            self.assertEqual(status, 401)
            challenge = headers["WWW-Authenticate"]
            self.assertIn(f"algorithm={algorithm}", challenge)
            self.assertEqual(cams.answer("/snapshot.png", digest_header(challenge, "admin", PASSWORD, "/snapshot.png", algorithm))[0], 200)
            self.assertEqual(cams.answer("/snapshot.png", digest_header(challenge, "admin", "wrong", "/snapshot.png", algorithm))[0], 401)
            self.assertEqual(cams.answer("/snapshot.png", digest_header(challenge.replace("nonce=\"", "nonce=\"00"), "admin", PASSWORD, "/snapshot.png", algorithm))[0], 401)

    def test_login_needs_a_password(self):
        with self.assertRaises(FakeCameraError):
            self.cams(Camera(id="a", auth="basic"), password="")

    def test_faults(self):
        expected = {"status": (500, None), "not-a-picture": (200, "text/html"), "empty": (200, "image/png")}
        for fault, (code, kind) in expected.items():
            cams, _ = self.cams(Camera(id="a", fault=fault))
            status, headers, body = cams.answer("/snapshot.png", None)
            self.assertEqual(status, code)
            if kind:
                self.assertEqual(headers["Content-Type"], kind)
            self.assertEqual(cams.counters.faulted, 1)
        cams, _ = self.cams(Camera(id="a", fault="oversize"))
        self.assertGreater(len(cams.answer("/snapshot.png", None)[2]), 3 * 1024 * 1024)

    def test_late_fault_waits_and_fault_every_spares_the_others(self):
        cams, clock = self.cams(Camera(id="a", fault="late", late_s=1.5, fault_every=2))
        cams.answer("/snapshot.png", None)
        self.assertEqual(clock.slept, [])
        self.assertEqual(cams.answer("/snapshot.png", None)[0], 200)
        self.assertEqual(clock.slept, [1.5])


class ConfigTests(unittest.TestCase):
    def doc(self, **extra):
        return {"schema": "armor-fake-cameras/1", "cameras": [{"id": "gate", "path": "/gate.png", **extra}]}

    def test_good_file(self):
        config = parse_config(self.doc(scene="dark", auth="digest", fault="late", late_s=3))
        self.assertEqual((config.cameras[0].scene, config.cameras[0].auth, config.cameras[0].late_s), ("dark", "digest", 3.0))

    def test_refusals(self):
        for bad in ({"schema": "x"}, [], self.doc(scene="rain"), self.doc(auth="ntlm"), self.doc(fault="boom"), self.doc(path="gate"), self.doc(path="/../x"),
                    self.doc(late_s=99), self.doc(fault_every=0), {"schema": "armor-fake-cameras/1", "cameras": []},
                    {"schema": "armor-fake-cameras/1", "width": 5000, "cameras": [{}]},
                    {"schema": "armor-fake-cameras/1", "cameras": [{"path": "/a"}, {"path": "/a", "id": "b"}]}):
            with self.assertRaises(FakeCameraError, msg=str(bad)):
                parse_config(bad)


class HttpTests(unittest.TestCase):
    def test_served_over_http_read_only_on_the_loopback(self):
        clock = Clock()
        cams = FakeCameras(CameraConfig(width=32, height=18, cameras=(Camera(id="a", auth="basic"),)), PASSWORD, clock, clock.sleep)
        server, _ = serve(cams, "127.0.0.1", 0)
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/snapshot.png"
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(url, timeout=5)
            self.assertEqual(caught.exception.code, 401)
            caught.exception.close()
            request = urllib.request.Request(url, headers={"Authorization": "Basic " + base64.b64encode(f"admin:{PASSWORD}".encode()).decode()})
            with urllib.request.urlopen(request, timeout=5) as response:
                self.assertEqual(response.headers["Content-Type"], "image/png")
                self.assertEqual(decode_png(response.read())[:2], (32, 18))
            with self.assertRaises(urllib.error.HTTPError) as post:
                urllib.request.urlopen(urllib.request.Request(url, data=b"x", method="POST"), timeout=5)
            self.assertEqual(post.exception.code, 405)
            post.exception.close()
        finally:
            stop(server)


class CommandLineTests(unittest.TestCase):
    def run_cli(self, *args: str) -> int:
        try:
            return main(list(args))
        except SystemExit as exit_:
            return int(exit_.code or 0)

    def test_runs_for_a_while_and_stops(self):
        self.assertEqual(self.run_cli("--camera-port", "0", "--camera-seconds", "0.2"), 0)

    def test_refusals(self):
        self.assertEqual(self.run_cli("--camera-port", "0", "--camera-host", "0.0.0.0"), 2)
        self.assertEqual(self.run_cli("--camera-port", "0", "--solar"), 2)
        self.assertEqual(self.run_cli("--camera-port", "0", "--meter-bus-port", "0"), 2)
        self.assertEqual(self.run_cli("--camera-seconds", "3"), 2)
        self.assertEqual(self.run_cli("--camera-port", "70000"), 2)

    def test_bad_file_and_missing_password(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cams.json"
            path.write_text(json.dumps({"schema": "armor-fake-cameras/1", "cameras": [{"scene": "rain"}]}), encoding="utf-8")
            self.assertEqual(self.run_cli("--camera-port", "0", "--camera-config", str(path), "--camera-seconds", "0.1"), 2)
            path.write_text(json.dumps({"schema": "armor-fake-cameras/1", "cameras": [{"auth": "basic"}]}), encoding="utf-8")
            self.assertEqual(self.run_cli("--camera-port", "0", "--camera-config", str(path), "--camera-seconds", "0.1"), 2)

    def test_options_exist(self):
        args = build_parser().parse_args(["--camera-port", "0"])
        self.assertEqual((args.camera_port, args.camera_host), (0, "127.0.0.1"))


if __name__ == "__main__":
    unittest.main()
