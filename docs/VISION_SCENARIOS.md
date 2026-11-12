# Vision scenarios

A vision scenario is a JSON file that describes cameras with their **detection zones and mode profiles** (the same shape the server keeps and hands to the observation service under `cameras[].detection`) and a timeline of the arming mode and of objects walking across the picture. The simulator plays the rules of the vision service on the host and prints the vision events they would raise; the optional `expect` part is the test case that those events are compared with.

```powershell
$env:PYTHONPATH="src"
python -m armor_simulator --vision-scenario examples/vision/porch-by-mode.json --check-vision-scenario
python -m armor_simulator --vision-scenario examples/vision/porch-by-mode.json
python -m armor_simulator --vision-scenario examples/vision/porch-by-mode.json --verify-vision
```

* `--check-vision-scenario` only validates the file and prints what it holds.
* Without it the scenario is played and the output is **one vision event per line** (`armor.vision.event/v1`, the contract `vision_event` of ARMOR-COMMON), in order of time. A summary goes to the error output. Nothing else is emitted: it cannot be combined with the options that publish messages (`--alarm-scenario`, `--replay`, `--record`, `--server-url`, `--solar`, `--electrical`, `--energy`, `--fault`, `--verify-panel-sync`, `--camera-port`, `--meter-bus-port`).
* `--verify-vision` compares the events with `expect`. Exit 0 when the rules answered as expected, 1 when not (every difference is listed on the error output), 2 when the file is not valid.

Nothing is read loosely: the first thing that is not understood (an unknown key, a number of the wrong type or range, a repeated key, `NaN`, a corner outside the picture, a zone that encloses no area, a profile that watches a zone the camera does not have, a mode at a time outside the scenario, a file larger than 1 MB) refuses the whole file with a message that says where.

## The rules

They follow the ones of the vision service:

* An object counts in a zone when its **feet** are inside the polygon, its label is accepted by the zone (a zone with no labels accepts all), it has been there for `min_frames` steps **and** `min_seconds`, and the zone is **watched** in the current mode.
* Each (object, zone) pair raises **one event per visit**; leaving the zone and coming back is a new visit.
* A mode with **no profile watches every zone**: an unknown mode never watches less than the owner drew. A profile with an empty `watch` list watches nothing.
* The type of the event is the kind of the zone (`alert` or `detection`).
* `sensitivity` and `notify` of a profile are read and checked, and they do not change the events (the host twin has no detector whose sensitivity could be turned).

It is a twin of the **rules**, not of a detector: it sees no picture, and it says nothing about how well a real detector finds a person at night or in rain. Nothing has been compared with a real camera.

## The file

```json
{
  "schema": "armor-vision-scenario/1",
  "name": "Porch by mode",
  "description": "Optional text, up to 600 characters.",
  "duration_s": 120,
  "step_s": 0.5,
  "cameras": [
    { "id": "front", "detection": {
        "zones": [ { "id": "porch", "name": "Porch", "points": [[0.55, 0.5], [0.95, 0.5], [0.95, 0.95]], "kind": "alert", "labels": ["person"], "min_frames": 2, "min_seconds": 1 } ],
        "profiles": { "away": { "watch": ["porch"], "sensitivity": "high", "notify": true } } } }
  ],
  "events": [
    { "type": "mode", "at_s": 0, "mode": "home" },
    { "type": "walk", "at_s": 5, "camera": "front", "label": "person", "speed": 0.1, "path": [[0.5, 0.3], [0.8, 0.8]] }
  ],
  "expect": {
    "events": [ { "camera": "front", "zone": "porch", "label": "person", "between_s": [5, 38] } ],
    "forbidden": [ { "camera": "front", "zone": "porch", "label": "cat" } ]
  }
}
```

| Field | Values |
|---|---|
| `duration_s`, `step_s` | 1 to 3600 seconds; the step from 0.05 to 5 seconds (default 0.5); at most 50 000 steps |
| `cameras` | 1 to 8; each has an `id` and a `detection` with 1 to 16 `zones` and the `profiles` by mode |
| zone | `id`, `name`, 3 to 12 `points` as `[x, y]` fractions of the picture from the top left, `kind` (`alert` or `detection`, default `alert`), up to 8 `labels`, `min_frames` (1 to 300), `min_seconds` (0 to 3600) |
| profile | by mode (`disarmed`, `home`, `away`, `night`): `watch` (ids of zones of the same camera), `sensitivity` (`low`, `normal`, `high`), `notify` (true or false) |
| `mode` event | `at_s`, `mode`; the first one must be at 0 and no two at the same time |
| `walk` event | `at_s`, `camera`, `label`, `speed` (picture widths per second, 0.001 to 2, default 0.1) and a `path` of 2 to 32 points the feet go through in a straight line |
| `expect.events` | rows `camera`, `zone`, optional `label` and `between_s` ([from, to] inside the scenario): each needs an event |
| `expect.forbidden` | rows `camera`, `zone`, optional `label`: no such event may appear |

The event carries the box of a walker of fixed size (8 % x 25 % of the picture) with its feet at the point of the path, a fixed confidence of 0.9 and the track number of the walk.

Examples to start from: `examples/vision/porch-by-mode.json` (the same walk at home, away and disarmed, and a cat that the zone ignores) and `examples/vision/unknown-mode-watches-all.json` (a mode without a profile).

Tests: 22 in `tests/test_vision_scenarios.py` (the strict reading with one case per refusal, the rules for visits, labels, profiles, unknown modes, a change of mode during a walk, `min_frames` and `min_seconds`, determinism, boxes inside the picture, the events against the contract when ARMOR-COMMON is next to this repository, the verification and the command line).
