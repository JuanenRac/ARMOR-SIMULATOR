# Alarm scenarios

An alarm scenario is a JSON file that describes a stretch of time in a house (who walks where, what fails, what the system is set to) and, optionally, **what the system is expected to answer**: which alarms, in which order and within which window of time. The simulator plays the first part as the messages the nodes would publish; the second part is the test case that a server's answer is compared with.

```powershell
$env:PYTHONPATH="src"
python -m armor_simulator --alarm-scenario examples/alarm/sequential-intrusion.json --check-alarm-scenario
python -m armor_simulator --alarm-scenario examples/alarm/sequential-intrusion.json --validate
python -m armor_simulator --alarm-scenario examples/alarm/sequential-intrusion.json --verify-alarms observed.jsonl
```

* `--check-alarm-scenario` only validates the file and prints what it holds.
* Without it the scenario is played: JSON lines `{"topic", "payload"}` like every other run, one second of telemetry per node per second of scenario (a health beat every `--health-every` seconds), so `--validate`, `--server-url`, `--fault`, `--start-ms` and the rest work as usual. The scenario brings its own nodes, light, length and seed (`--seed` is ignored): it cannot be combined with `--count`, `--scenario`, `--light`, `--node-id`, `--solar`, `--electrical` or `--energy`.
* `--verify-alarms FILE` compares the alarms a server raised with the expectation. Exit 0 when the system answered as expected, 1 when not (every difference is listed on stderr), 2 when a file is not valid. Nothing is played.

Nothing is read loosely: the first thing that is not understood (a key that is not in the schema, a number of the wrong type or range, a repeated key, `NaN`, a time outside the scenario, a zone that does not exist, a file larger than 1 MB, an expectation that cannot hold) refuses the whole file with a message that says where.

## The file

```json
{
  "schema": "armor-alarm-scenario/1",
  "name": "Sequential intrusion",
  "description": "optional text",
  "nodes": ["radar-1"],
  "duration_s": 120,
  "seed": 1,
  "light": "night",
  "power": false,
  "start_clock": "21:00",
  "schedule": [{"from": "22:00", "to": "06:00", "mode": "night"}],
  "zones": [{"id": "garden", "sensor_id": 1, "armed_in": ["home", "away", "night"]}],
  "events": [{"type": "mode", "at_s": 5, "mode": "away"}],
  "expect": {"alarms": [{"code": "intrusion", "at_s": [30, 36]}]}
}
```

| Key | Needed | Meaning |
|---|---|---|
| `schema` | yes | Always `armor-alarm-scenario/1` |
| `name`, `description` | name | Text (80 and 400 characters at most) |
| `duration_s` | yes | Length, 1 to 10 000 seconds (one telemetry message per node per second) |
| `nodes` | no | 1 to 8 node ids (default `["simulator-1"]`) |
| `seed` | no | Whole number from 0; the same file always gives the same messages |
| `light` | no | `night` (default, 0.3 lux) or `cycle` (the day of light shared by the simulated sources) |
| `power` | no | `true` also emits the inverter, the battery and the electrical node of the first node (also implied by any `mains_outage`) |
| `start_clock`, `schedule` | no | The time of day of second 0 (`HH:MM`) and up to 16 windows `{from, to, mode}` (a window may cross midnight) that set the mode by the clock |
| `zones` | yes | 1 to 64 places (below) |
| `events` | yes | Up to 2 000 events (below) |
| `expect` | no | What the system must answer (below) |

### Zones

`{"id", "node"?, "sensor_id"?, "x_mm"?, "y_mm"?, "armed_in"?}`. A zone is a place in the field of view of a node (the illustrative geometry of the simulator: three sensors facing -75, 0 and +75 degrees, 6 m, x to the right and y forward). Give `sensor_id` (1 to 3: the zone is 3 m in front of that sensor) or a position `x_mm`, `y_mm` (the sensor that sees it is worked out; a position outside every field of view is refused). `node` defaults to the first node. `armed_in` lists the modes in which the system defends the zone: any of `home`, `away`, `night` (default `["away", "night"]`).

### Events

All have `type` and `at_s` (a whole second from 0 to `duration_s`) and must end before the scenario does.

| `type` | Other keys | What it does |
|---|---|---|
| `mode` | `mode`: `disarmed`, `home`, `away` or `night` | Sets the mode of the system from that second on, over the calendar. The mode is `disarmed` until something says otherwise |
| `intrusion` | `path`: 1 to 16 steps `{zone, dwell_s}`; `people`: 1 to 5 (default 1) | People who walk the zones in order, each for `dwell_s` seconds (a sequential intrusion) |
| `pet` | `zone`, `duration_s` | A small, erratic track in the zone |
| `wind` | `zone`, `duration_s`, `intensity` 0.01 to 1 (default 0.3) | Single-second ghost tracks, each second with that probability |
| `sensor_fault` | `zone`, `duration_s`, `fault`, `magnitude`? | The sensor of the zone lies: `stuck` (a phantom still track), `noise` (ghost tracks; `magnitude` 0 to 1 is their probability, default 0.5), `drift` (the reported positions slide by `magnitude` mm per second, default 50, up to 1 000) or `dead` (it reports nothing) |
| `node_comm_loss` | `duration_s`, `node`? | The node says nothing at all (no telemetry, no health) while it lasts |
| `mains_outage` | `duration_s` | The mains fail: the inverter goes on the battery and the electrical node reads no voltage on the grid input |

The tracks of a node never exceed five per sensor and fifteen in all, and keep numbers 1, 2, 3... in a message.

### What is expected

```json
"expect": {
  "alarms": [{"code": "intrusion", "zone": "garden", "node": "radar-1", "severity": "high", "at_s": [30, 36]}],
  "order": "strict",
  "forbidden": [{"code": "intrusion", "zone": "kitchen", "from_s": 0, "to_s": 3599}],
  "allow_extra": false
}
```

* `alarms`: each one must happen once, with that `code` (one of the codes of the alarm table of ARMOR-COMMON that a scenario may name), inside the window `at_s` `[from, to]` in seconds from the start of the scenario; `zone`, `node` and `severity` (`info`, `warning`, `high`, `critical`) are required to match only when given. One raised alarm satisfies only one expectation.
* `order`: `any` (default) or `strict` (the alarms must come in the order listed).
* `forbidden`: an alarm that must **not** happen (a false alarm), optionally within `from_s`..`to_s` and for a `zone`.
* `allow_extra`: `true` (default) lets other alarms happen; `false` makes any alarm that was not expected a difference.

A scenario is also refused when an expectation contradicts it: a code that only matters while the system is armed (`intrusion`, `motion`, `door_open`, `window_open`, `glass_break`, `vibration`, `node_down`, `camera_down`, `camera_motion`) expected in a window in which the system is not defending that zone (mode and `armed_in`).

### The alarms observed

`--verify-alarms` reads a JSON list or JSON lines of the alarms the server raised, with the seconds counted from the start of the scenario: `{"t_s": 31.5, "code": "intrusion", "node": "radar-1", "severity": "high"}` (`zone` too when the server says it). Keys are checked like those of a scenario.

## The examples

`examples/alarm/` has eight files: a sequential intrusion, two people on two nodes, a sensor that is stuck and one that is dead, noise and drift, a node that loses its link, a pet and wind, the night mode of the calendar, and a mains outage.

## What this is and is not

* The expectations of the examples are **reference expectations** written from how ARMOR-SERVER is documented to behave (a track while armed is a high intrusion, a silent node is called down after the stale time, a lost grid is an alarm). They have not been run against a live server here: a difference found with `--verify-alarms` may be a wrong expectation as well as a wrong server, and that is for a person to judge.
* The system modes `home` and `night` are labels of the scenario. The radar side of a server is armed or disarmed; what the other modes change (which zones are defended) is for the server under test to implement, and the scenario only says what is expected of it.
* The false-alarm examples (a pet, the wind) only make sense for a server tuned against them (a minimum number of targets, a dwell time or an ignore zone).
* The geometry is illustrative: nothing says how a real radar sees a person, a pet or the wind.
