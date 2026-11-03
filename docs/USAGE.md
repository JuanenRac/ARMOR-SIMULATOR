# Simulator usage

```powershell
$env:PYTHONPATH="src"
python -m armor_simulator --count 20 --scenario crossing --seed 1 --validate
```

Each output line is an MQTT-ready envelope `{"topic": ..., "payload": ...}` with
stable key order, so the same command always prints the same lines. Nothing is
transmitted unless you ask for it: publishing to a broker is deliberately not
built in, so a test can never reach a production broker by accident.

## Options

| Option | Meaning |
|---|---|
| `--node-id` | Node identifier (lowercase letters, digits, `-`, `_`; up to 64) |
| `--count` | Samples to generate, 1 to 10 000; one sample is one second of simulated time |
| `--scenario` | `patrol`, `crossing`, `two-intruders`, `empty` or `relay` (the walker of `crossing` handed from node to node with `--nodes`) |
| `--light` | `cycle` (the 240-sample day shared with the solar and electrical sources: from 0.3 lux at night to about 50 000 at noon) or `night` (fixed 0.3 lux, for the low-light vision profile) |
| `--start-ms` | Date of the first sample: `0` (default: identical runs, but the server replaces such old dates by its own clock), a number of milliseconds, or `now` (dates the server takes as they are, so an out-of-order message really is late) |
| `--seed` | Same seed, same output |
| `--health-every` | One health message every N samples (0 disables) |
| `--solar` | Also emit an inverter and a two-module battery stack (fifteen cells each, with capacities) over a fast day of 240 samples, with a mains outage late in the day |
| `--electrical` | Also emit the three channels of an electrical node (the grid input, a water heater and a DC bus) over the same fast day, with the mains outage, a spell of high voltage and a meter alarm |
| `--nodes` | Simulate 1 to 8 radar nodes at once (`--nodes north-1,south-1`, instead of `--node-id`); each has its own jitter, and the first also carries `--solar` and `--electrical`. With `--scenario relay` one walker is seen by one node at a time (12 samples each) and then by the next, to try the fusion of the server and the nodes that cover a zone |
| `--info` | Also emit what each radar node says about itself (`armor/node/<id>/info`: a name, a firmware, an address of a private network and the port of its panel), at the start and every 30 samples. The server takes it from the broker only |
| `--alarm-node ID` | Also emit the state of a simulated alarm panel (`armor/alarm/<id>/state`, every sample): disarmed, a delay to leave, armed, a person at the door, the siren and disarmed again, over 120 samples. It walks a fixed timeline and does not answer orders (for that see `--verify-panel-sync`) |
| `--network-node ID` | Also emit the state of a simulated network watcher (`armor/network/<id>/state`, every 5 samples): a router, a laptop that is on and off, a printer that joins half way through, and the internet |
| `--mqtt-url`, `--mqtt-user`, `--mqtt-password-file`, `--mqtt-allow-network` | Also publish every message on an MQTT broker with its topic, the way the nodes do (QoS 1); it needs `pip install paho-mqtt`. The broker must be this machine or a private network address unless you add `--mqtt-allow-network`; the password comes from `ARMOR_MQTT_PASSWORD` or a file, never from the command line. With `--verify-panel-sync` the same option names the broker of the server instead |
| `--camera-port`, `--camera-config`, `--camera-host`, `--camera-allow-network`, `--camera-password-file`, `--camera-seconds` | Instead of emitting messages, play fake IP cameras over HTTP: each answers its snapshot address with a grey PNG that changes like a scene, with an optional Basic or Digest login and faults on purpose ([FAKE_CAMERAS.md](FAKE_CAMERAS.md)); the password only from `ARMOR_FAKE_CAMERA_PASSWORD` or a file |
| `--fault`, `--fault-every` | Inject a repeatable fault (below) |
| `--record` | Also write every emitted message to a JSON-lines file, to play it again later; an existing file is never overwritten, so a recording is not lost by mistake |
| `--replay` | Emit the messages of a recording made with `--record` instead of generating them. It cannot be combined with `--alarm-scenario`, `--energy`, `--solar`, `--electrical`, `--count`, `--scenario`, `--light` or `--node-id`; `--fault`, `--validate` and `--server-url` still apply. A bad recording is refused whole |
| `--http-fault`, `--http-fault-every`, `--http-latency-ms` | Spoil the delivery to `--server-url`, not the messages: `latency` (every Nth message waits `--http-latency-ms`, up to 60 000), `drop` (every Nth message is not sent) or `duplicate` (every Nth message is sent twice). Default `none`, every `3`, `1500` ms; it needs `--server-url` |
| `--fault-topic` | Limit the fault to one kind of message: `telemetry`, `health`, `solar` or `electrical` (default `all`). The count of `--fault-every` is of that kind, and the other messages go through untouched, so `--fault node-silent --fault-topic telemetry` silences the radar node while the inverter and the electrical node go on talking. A kind with nothing to spoil (`solar` without `--solar`, `health` with `--health-every 0`) is refused |
| `--alarm-scenario FILE` | Play an alarm scenario described in a JSON file instead of `--scenario`/`--count` ([ALARM_SCENARIOS.md](ALARM_SCENARIOS.md)); with `--check-alarm-scenario` it only validates the file, with `--verify-alarms FILE` it compares the alarms a server raised with what the file expects (exit 1 when they differ) |
| `--drive-server`, `--studio-user`, `--studio-password-file`, `--studio-pin-file`, `--apply-modes`, `--settle-s`, `--save-observed` | Play the file of `--alarm-scenario` against a real ARMOR-SERVER in real time, turn its mode events into orders to the server and check the alarms it raised ([ALARM_SCENARIOS.md](ALARM_SCENARIOS.md)); the password only from `ARMOR_STUDIO_PASSWORD` or a file |
| `--energy`, `--energy-config`, `--energy-days`, `--energy-step-s` | Emit realistic solar and electrical data in real time (sun with clouds, house by the hour, tariff, battery, noisy meter) instead of the fast day of `--solar`/`--electrical` ([ENERGY_MODEL.md](ENERGY_MODEL.md)) |
| `--allow-invalid` | Required for faults that break the contract on purpose |
| `--validate` | Check every message against ARMOR-COMMON before it is emitted |
| `--interval-ms` | Real pause between messages |
| `--server-url`, `--ingest-token` | Deliver to an ARMOR-SERVER. The token is better given as `ARMOR_INGEST_TOKEN` or `--ingest-token-file` (a command-line argument shows in the process list); nothing writes it anywhere |
| `--per-node-token` | Send each message with the token derived for its node, the only one a server with `ARMOR_INGEST_STRICT=1` accepts |

## Scenarios

The geometry is illustrative, not a model of the real hardware: a node covers
270 degrees with three sensors facing -75, 0 and +75 degrees, each seeing
about ±60 degrees out to 6 m (neighbours overlap by 45 degrees, the 90 degrees behind the
node are blind), and at most five targets per sensor. A person outside every field of view
is simply not reported. `speed_mm_s` is the speed along the line from the sensor: negative
when the object comes closer, positive when it goes away.

* `patrol`: one target circling at 3 m; it leaves and re-enters the field of view.
* `crossing`: a person crossing left to right at about 1.2 m/s, handed from sensor 1 to sensor 3.
* `two-intruders`: two people approaching; two tracks raise a **high** alert while the system is armed.
* `empty`: a quiet perimeter.
* `relay`: the walker of `crossing`; with `--nodes` a different node sees it every 12 samples (the others see nothing).

The tracks follow the real node's format: whole numbers, one id per slot while the object is in the scene, a radial speed with a sign. The tests compare the fields and types of every message (telemetry, health, info, alarm, network) with the conformance vectors of ARMOR-COMMON, the same ones the firmware serialisers are held to, and the contract validators accept them. A walk with a speed along a polyline is written in an alarm scenario file (the `walk` event, see [ALARM_SCENARIOS.md](ALARM_SCENARIOS.md)).

## Faults

| Fault | Effect | Valid messages? |
|---|---|---|
| `node-silent` | The node stops after N messages: the server must show it stale, then offline | yes |
| `out-of-order` | Every Nth message carries a timestamp 60 s older (use `--start-ms now` with a server: it replaces dates before 2020 by its own clock) | yes |
| `duplicates` | Every Nth message is delivered twice (what MQTT QoS 1 does) | yes |
| `flapping` | Some health messages report the node offline | yes |
| `corrupt-lux` | Lux above the sensor limit | **no** |
| `unknown-field` | A field the contract does not define | **no** |
| `oversized-targets` | More than 15 tracks | **no** |

Faults that produce invalid messages need `--allow-invalid` and cannot be combined
with `--validate`. When delivering to a server, a refusal of such a message is
expected and is reported without stopping the run, and at the end the simulator says how many were refused and how many were accepted: the server accepts unknown fields in solar, electrical and MQTT messages on purpose, so `unknown-field` is not always refused.

## Playing the energy meters

`--meter-bus-port PORT` stops emitting messages and plays the serial line of the energy meters over TCP: Modbus-RTU requests are answered like a PZEM-004T v3 and a PZEM-017 answer them (read only, a bad CRC gets no answer, a write is refused), with the readings of `--electrical`. `--meter-bus-config FILE` holds the meters, thresholds and faults, `--meter-bus-seconds` stops it after a time, and it listens on the loopback unless `--meter-bus-host` and `--meter-bus-allow-network` say otherwise. See [METER_BUS.md](METER_BUS.md).

## Delivering to a server

```powershell
python -m armor_simulator --count 60 --scenario two-intruders --server-url http://127.0.0.1:18080 --ingest-token <ingest token>
```

The alarm and network messages go to `/api/v1/alarm/state` and `/api/v1/network/state`; the `info` of a node has no HTTP route (use `--mqtt-url`) and the run says how many messages were left out.

Only a plain `http(s)://host[:port]` origin is accepted. A 4xx answer stops the
run at once (the message or the token is wrong); a network error or a 5xx is
retried three times.

## Checking the panel sync of a server

With the server settings `alarm.arming_modes` and `alarm.mode_panel_sync` on and `ARMOR_ALARM_COMMANDS=1`, choosing a mode on the server also asks the alarm panels to arm with the profile of the mode (away arms `away`, home arms `stay`, night arms `night`) and the server reports what they answered (`panel_sync`). A simulated panel checks that without a real one:

```powershell
$env:ARMOR_STUDIO_PASSWORD = "<password>"
python -m armor_simulator --verify-panel-sync --server-url http://127.0.0.1:18080 --studio-user ana --mqtt-url mqtt://127.0.0.1:18883 --mqtt-user armor --mqtt-password-file broker.txt
```

With `--verify-panel-map` (an administrator account) the check also plays the choices of the owner about how the modes reach the panels: home arming the profile `away`, the list of panels with only this one, an empty list (nobody is asked) and a list naming a panel that does not exist (a failed panel, and the others are not asked); it puts the document of the modes back as it was.

The panel (`--panel-id`, default `sim-panel`) connects to the same broker as the server (needs `pip install paho-mqtt`), publishes its state and answers each command as it is told to: accepts, refuses with `zones_open`, or stays silent (`--panel-behavior` plays only some of them). For every behaviour and every mode the check disarms, chooses the mode and waits for the report, then compares: the server defends the mode whatever the panel did, exactly one arm command with the right profile reached the panel and no other command (a disarm never travels), no PIN reaches the panel, and the report says `confirmed` only when the panel accepted and `failed` for a refusal or silence. It changes no security setting and leaves the system disarmed; it needs an account that may arm and disarm (the PIN with `--studio-pin-file`). A silent panel makes the run last about five seconds per mode. The check is a model of the panel's answer, not its firmware: what a real panel does with the command is still to be seen on hardware.

### In the continuous integration

The workflow `panel-sync.yml` runs the check on every push to the main branch, with a real Mosquitto and the ARMOR-SERVER of the main branch built next to this repository: `tools/ci_panel_sync.py` starts the broker (on a free loopback port, no persistence) and the server (a throw-away data folder, an administrator made for the run, `ARMOR_ALARM_COMMANDS=1`), turns on `alarm.arming_modes` and `alarm.mode_panel_sync`, and runs `--verify-panel-sync --verify-panel-map`. It needs `mosquitto`, `node`, the server built and `paho-mqtt`; it is the same script to run on a workstation with those installed. A workflow of its own so that it can be turned off alone: set the repository variable `ARMOR_PANEL_SYNC` to `off`, or disable the workflow.


## The virtual bench (several nodes, in real time, in a container)

`docker/bench.sh` is the entry point of the `Dockerfile`: it runs `ARMOR_SIM_NODES` (1 to 8) simulated nodes (`bench-1`, `bench-2`...) side by side, each delivering `ARMOR_SIM_ROUND_SAMPLES` samples to the server one every `ARMOR_SIM_INTERVAL_MS` milliseconds, round after round until it is stopped (`ARMOR_SIM_ROUNDS` limits the rounds; if the server is restarting a failed round is retried after `ARMOR_SIM_RETRY_S` seconds). The ingest token comes from `ARMOR_INGEST_TOKEN` or from the file of `ARMOR_SIM_TOKEN_FILE`, never from a command line; `ARMOR_INGEST_STRICT=1` makes every node use its own derived token. The other settings are `ARMOR_SIM_SCENARIO`, `ARMOR_SIM_LIGHT`, `ARMOR_SIM_SEED`, `ARMOR_SIM_SOLAR=1`, `ARMOR_SIM_ELECTRICAL=1`, `ARMOR_SIM_FAULT` (with `ARMOR_SIM_ALLOW_INVALID=1` for a fault that breaks the contract on purpose) and `ARMOR_SIM_SERVER_URL`. `ARMOR_SIM_DRY_RUN=1` prints the commands and runs none. ARMOR-DEVOPS starts it with `docker compose --profile bench up -d --build`.
