# Fake IP cameras

`--camera-port PORT` plays IP cameras over HTTP instead of emitting messages, so the code that fetches a camera's still picture (the server's camera preview, the snapshot of an event, the movement service that asks the server for a frame) can be tried without a camera.

```powershell
$env:PYTHONPATH = "src"
python -m armor_simulator --camera-port 18999 --camera-seconds 60
# armor-simulator: camera cam-1 at http://127.0.0.1:18999/snapshot.png (scene walker, login none, fault none)
```

Each camera answers `GET <path>` with an 8-bit grey PNG (the server accepts JPEG and PNG) that changes with the clock the way a scene does. Nothing is stored; the pictures are worked out for each request. It is read only (anything but `GET` gets 405), it listens on the loopback unless you add `--camera-allow-network`, and it speaks **no RTSP**: the live stream of a camera needs a real camera or a stream server. Nothing here has been compared with a real camera's firmware.

## Options

| Option | Meaning |
|---|---|
| `--camera-port PORT` | Listen on this port (0: any free one); the addresses are printed on the error output |
| `--camera-config FILE` | The settings file below (default: one camera at `/snapshot.png` with a walker, no login) |
| `--camera-host HOST` | The address to listen on (default `127.0.0.1`) |
| `--camera-allow-network` | Required for an address that is not the loopback |
| `--camera-password-file FILE` | First line = the password of the cameras that ask for a login; or `ARMOR_FAKE_CAMERA_PASSWORD`; never a command-line argument |
| `--camera-seconds N` | Stop after N seconds (0: until interrupted); the end prints how many requests, pictures, logins and faults there were |

It cannot be combined with the options that emit messages (`--alarm-scenario`, `--replay`, `--record`, `--server-url`, `--solar`, `--electrical`, `--energy`, `--fault`, `--verify-panel-sync`, `--meter-bus-port`).

## The settings file

```json
{
  "schema": "armor-fake-cameras/1",
  "width": 160,
  "height": 90,
  "cameras": [
    { "id": "gate", "path": "/gate.png", "scene": "walker", "seconds_per_pass": 10 },
    { "id": "yard", "path": "/yard.png", "scene": "dark", "auth": "digest", "username": "admin" },
    { "id": "shed", "path": "/shed.png", "scene": "waving-tree", "fault": "late", "late_s": 3, "fault_every": 2 }
  ]
}
```

| Field | Values |
|---|---|
| `width`, `height` | 16 to 640 pixels (default 160 x 90) |
| `cameras` | 1 to 16; each has its own `path` (letters, digits and `/ . _ -`, starting with `/`) and `id` |
| `scene` | `still` (nothing moves), `walker` (a person crosses the picture in `seconds_per_pass`), `flicker` (the light pulses), `dark` (a night picture with sensor noise), `waving-tree` (a patch that moves in one corner, for the zones to ignore) |
| `auth` | `none`, `basic`, `digest` (MD5, qop=auth) or `digest-sha256`; the user is `username` (default `admin`) and the password is never in the file |
| `fault` | `none`, `status` (HTTP 500), `not-a-picture` (a 200 with `text/html`), `empty` (an empty body), `late` (waits `late_s` seconds, up to 30), `oversize` (a body over 4 MiB, to meet the size limit) |
| `fault_every` | The fault strikes every Nth request of that camera (default 1: always); a request that fails its login does not count |

A file with an unknown scene, login or fault, two cameras with the same path or id, a path with `..` or `//`, a value out of range, a constant that is not JSON (`NaN`) or more than 64 KiB is refused whole, and so is a camera that asks for a login when no password was given.

## Pointing a server at it

In the server (or its Studio), give a camera the host `127.0.0.1` and the snapshot address `http://127.0.0.1:18999/gate.png`; the server asks for it with the camera's login (Basic or Digest) and checks the answer type and size. The movement service gets its 64 x 36 grey frames from the camera's RTSP stream, which this does not play; the snapshot serves the preview and the pictures kept as evidence.

Tests: 17 in `tests/test_fake_cameras.py` (the scenes move or stay still, the PNG decodes with valid checksums, Basic and both Digest logins accept and refuse, the faults, the file refusals, the HTTP road and the command line).
