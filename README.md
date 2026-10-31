<p align="center">
  <img src="images/ARMOR_BANNER.svg" alt="ARMOR-SIMULATOR banner" width="100%">
</p>

# 🧪 ARMOR-SIMULATOR

<p align="center">
  🇺🇸 <b>English</b> |
  <a href="README_spa.md">🇪🇸 Español</a> |
  <a href="README_fra.md">🇫🇷 Français</a> |
  <a href="README_ita.md">🇮🇹 Italiano</a> |
  <a href="README_deu.md">🇩🇪 Deutsch</a> |
  <a href="README_zho.md">🇨🇳 简体中文</a> |
  <a href="README_jpn.md">🇯🇵 日本語</a> |
  <a href="README_por.md">🇵🇹 Português</a>
</p>

### Offline telemetry simulator with repeatable faults

<p align="center">
  <img src="https://img.shields.io/badge/License-GPL%203.0--or--later-blue.svg" alt="GPL 3.0 or later">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-3776ab.svg" alt="Language">
  <img src="https://img.shields.io/badge/Dependencies-none-2ea44f.svg" alt="Dependencies">
  <img src="https://img.shields.io/badge/Tests-127%20passing-2ea44f.svg" alt="Tests">
  <img src="https://img.shields.io/badge/Version-0.2.7-0f6cbd.svg" alt="Version">
  <img src="https://img.shields.io/badge/Maturity-established-2EA44F.svg" alt="Maturity">
</p>

---

**Honesty check - what runs today:** Scenarios, faults, delivery to a server and the 127 tests are real, and the simulator is what feeds a server on a computer when no node is plugged in. The geometry is **illustrative**, not a model of the real LD2450 radar, and nothing here has been compared with real hardware.

---

## 📋 At a glance

| | |
|---|---|
| Version | `0.2.7` |
| Maturity | Established |
| Role | Offline telemetry and environment simulator (family: Testing, parent: ARMOR-COMMON) |
| Stack | Python 3.11+, standard library only |
| Tests | 127 (`python -m unittest discover -s tests`) |
| Scenarios and faults | 4 scenarios, 7 faults (3 break the contract on purpose) |
| Runs on | Any computer, or CI |
| On real hardware | Not applicable: it is the stand-in for hardware, used on a computer |
| License | GPL-3.0-or-later |

**Jump to:** [Overview](#-overview) · [Architecture](#-architecture) · [Security](#-security--safety) · [Interfaces](#-interfaces) · [Configuration](#-configuration) · [Quick start](#-quick-start) · [Testing](#-testing) · [Troubleshooting](#-troubleshooting) · [Structure](#-repository-structure) · [Related](#-related-projects)

## 🚦 Project status

Each line is one part of this repository and the light says how far it is today. It is written from what the repository can show (tests, builds, runs), not from what is planned.

🟢 Done and verified · 🟡 Works, with known limits · 🟠 Partly done or not verified yet · 🔴 Not done or not working

| Area | State | What it means here |
|---|---|---|
| Software | 🟢 | The scenarios, the faults and the delivery to a server work; it is what feeds a server on a computer when no node is plugged in. |
| Tests | 🟢 | 127 tests pass (`python -m unittest discover -s tests`). |
| Protocols and data | 🟠 | The geometry is illustrative, not a model of the real LD2450 radar, and nothing has been compared with real hardware. |
| Integration | 🟢 | It delivers its messages to a server in the tests, and the server of the CM5 test bench can be fed by it. |
| Documentation | 🟢 | Eight languages and the changelog are up to date. |

## 🎯 Overview

* **Scenarios:** `patrol`, `crossing`, `two-intruders` and `empty`, on a 270 degree geometry with three sensors, plus a day/night light cycle or a fixed night.
* **Repeatable faults:** a silent node, out-of-order and duplicated messages, a flapping node, and deliberately invalid messages (lux over the limit, unknown field, too many tracks) for negative tests.
* **Deterministic:** the same seed always prints the same lines; nothing is sent unless you give `--server-url` and `--ingest-token`.
* **Checked against the contract:** `--validate` runs every message through ARMOR-COMMON before it is emitted.
* **Careful delivery:** only a plain http(s) origin is accepted; a 4xx stops the run, a 5xx or a network error is retried.
* **Electrical node:** `--electrical` adds the three channels of an electrical node (the grid input, a water heater and a DC bus) over a fast day, with a mains outage, a spell of high voltage and a meter alarm.
* **Solar equipment:** `--solar` adds an inverter and a two-module battery stack (fifteen cells each, capacities included) over a fast day of 240 samples, with a mains outage late in the day; the messages are checked against the solar contract of ARMOR-COMMON and delivered to `/api/v1/solar`.
* **Alarm scenarios in files:** `--alarm-scenario` plays a JSON file with a timeline (people crossing several zones, a pet, wind, a sensor that is stuck, noisy, drifting or dead, a node that loses its link, a mains outage, the mode and the calendar) and may say what the system is expected to answer; `--verify-alarms` compares the alarms a server raised with it, so the files are test cases for ARMOR-SERVER. The reading is strict: the whole file is refused at the first thing that is not understood.
* **Realistic energy data:** `--energy` emits an inverter, a battery stack and an electrical node from a real-time model (a sun with clouds, a house by the hour, a tariff, a Pylontech-style battery with cycles, a noisy meter with holes), deterministic for a seed and tuned from a JSON file. Without the new options the output is exactly what it was.

## 🧩 Role in A.R.M.O.R.

ARMOR-SIMULATOR is how the rest of the family is tried without hardware: it plays the part of a radar node, a solar gateway or an electrical node and sends their messages to an [ARMOR-SERVER](https://github.com/JuanenRac/ARMOR-SERVER), with faults you can repeat, so [ARMOR-STUDIO](https://github.com/JuanenRac/ARMOR-STUDIO) and the phone app can be seen working with a house that does not exist. Every message it makes is checked against the contracts of [ARMOR-COMMON](https://github.com/JuanenRac/ARMOR-COMMON).

| Name | How | What for |
|---|---|---|
| ARMOR-SERVER | `POST /api/v1/telemetry`, `/health`, `/solar`, `/electrical/readings` | Receives the simulated messages |
| ARMOR-COMMON | `--validate` | The contracts every message is checked against |
| ARMOR-STUDIO, ARMOR-ANDROID-CONTROL | through the server | Show the simulated house |

## 🏛️ Architecture

<p align="center">
  <img src="images/architecture.svg" alt="ARMOR-SIMULATOR architecture: who calls it, what it holds and what it depends on" width="100%">
</p>

## 🔒 Security & Safety

| Threat | Defence |
|---|---|
| Sending to a strange destination | Only a plain http(s) origin is accepted (no path, no credentials); a 4xx stops the run, a 5xx or a network error is retried three times |
| The token shows in the process list | `--ingest-token` is discouraged; use `ARMOR_INGEST_TOKEN` or `--ingest-token-file`; nothing writes the token anywhere |
| A test reaches a real server by accident | Nothing is sent unless you give `--server-url` and a token; there is no broker client at all |
| Messages that break the contract on purpose | `corrupt-lux`, `unknown-field` and `oversized-targets` need `--allow-invalid` and cannot be combined with `--validate` |
| Hostile input on the command line | The node id must match `^[a-z0-9][a-z0-9_-]{0,63}$` and `--count` is 1 to 10 000 |

This is a test tool: it is not a safety function and its geometry is not a model of the real radar.

## 🔌 Interfaces

| Option | Default | What it sets |
|---|---|---|
| `--scenario` | `patrol` | `patrol`, `crossing`, `two-intruders`, `empty` |
| `--count` | `1` | Samples (1 to 10 000); one sample is one second |
| `--seed` | `0` | The same seed prints the same lines |
| `--light` | `cycle` | `cycle` (day and night) or `night` (fixed 0.3 lux) |
| `--solar`, `--electrical` | off | Also emit an inverter with batteries / an electrical node |
| `--alarm-scenario`, `--check-alarm-scenario`, `--verify-alarms` | - | Play an alarm scenario from a JSON file / only validate it / compare the alarms a server raised with what it expects (exit 1 when they differ) |
| `--energy`, `--energy-config`, `--energy-days`, `--energy-step-s` | off, -, `1`, `900` | Realistic solar and electrical data in real time instead of the fast day of `--solar`/`--electrical` |
| `--fault`, `--fault-every`, `--fault-topic` | `none`, `3`, `all` | Inject a repeatable fault into some messages |
| `--validate`, `--allow-invalid` | off | Check each message against ARMOR-COMMON / allow the faults that break it |
| `--server-url`, `--ingest-token-file`, `--per-node-token` | - | Deliver to ARMOR-SERVER; the token of each node when the server is strict |

Every option, scenario and fault is in [docs/USAGE.md](docs/USAGE.md). Messages: `armor/node/<id>/telemetry` and `health`, `armor/solar/<node>/<device>/state`, `armor/electrical/<node>/state`; delivery goes to `/api/v1/telemetry`, `/api/v1/health`, `/api/v1/solar` and `/api/v1/electrical/readings`.

## ⚙️ Configuration

| Variable | Needed | What it sets |
|---|---|---|
| `ARMOR_INGEST_TOKEN` | with `--server-url` | The ingest token of the server (or a line `ARMOR_INGEST_TOKEN=...` in the file of `--ingest-token-file`) |
| `PYTHONPATH=src` | from a checkout | Where the package is found |

| Limit | Value |
|---|---|
| Samples per run | 1 - 10 000 |
| Sensors and field of view | 3 (-75, 0, +75°) × ±60°, 6000 mm |
| A day of light, solar and electrical | 240 samples |
| Delivery attempts / timeout | 3 / 5 s |

## 🚀 Quick start

**Requirements:** Python 3.11+ (standard library only).

```powershell
$env:PYTHONPATH = "src"
python -m armor_simulator --count 20 --scenario crossing --seed 1 --validate
python -m armor_simulator --count 60 --scenario two-intruders --server-url http://127.0.0.1:8080 --ingest-token-file token.env
```

## 🧪 Testing

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
python -I tools/armor_ci_validate.py
```

| Test file | Tests | What it covers |
|---|---|---|
| `test_simulator.py` | 37 | Scenarios, faults, solar, electrical, validation, delivery to a local HTTP server |
| `test_cli_options.py` | 26 | The options, their limits and the refusals |
| `test_alarm_scenarios.py` | 32 | Alarm scenario files: strict reading, the stream, modes and calendar, verification of the answer, the options |
| `test_energy.py` | 32 | Energy model: physical properties for many seeds, tariff, meter, settings, contracts, the options |

## 🏗️ Build & Release

It is plain Python: nothing to compile. The version lives in `pyproject.toml` and `armor.project.json`.

## 🩺 Troubleshooting

| You see | Because | Do |
|---|---|---|
| `--server-url needs a token ...` | A URL without a token, or a token without a URL | Give both |
| HTTP 401 / 403 | The ingest token is wrong; a strict server wants one token per node | `--per-node-token` |
| `--allow-invalid` | The fault breaks the contract on purpose | Add it, and do not use `--validate` |
| The server shows the messages as old | The default start date is 0 and the server replaces it | `--start-ms now` |

## 📂 Repository Structure

<p align="center">
  <img src="images/repository-structure.svg" alt="Repository structure of ARMOR-SIMULATOR" width="100%">
</p>

<details>
<summary>Text version of the tree</summary>

```text
ARMOR-SIMULATOR/
├── src/armor_simulator/
│   ├── cli.py                           the options and the run
│   ├── scenarios.py cycle.py            the four scenarios, the 270 degree geometry and the day of light
│   ├── alarm_scenarios.py               alarm scenarios from JSON files, their messages and the check of the answer
│   ├── solar.py                         an inverter and a two-module battery stack
│   ├── electrical.py                    the three channels of an electrical node
│   ├── energy.py                        realistic solar and electrical data: sun with clouds, house, tariff, battery, meter
│   ├── faults.py                        the seven repeatable faults
│   └── publisher.py                     delivery to a server with retries
├── tests/                               the tests
├── docs/                                the guides of this repository
├── tools/                               the shared CI checks and project tooling
├── .github/                             CI workflow, issue and pull-request templates
├── examples/                            alarm scenarios and settings of the energy model to start from
├── images/                              banner, icon and the two pictures of this README
├── build.sh build.bat                   build through the shared project workflow
├── test.sh test.bat                     run the tests through the shared workflow
├── run.sh run.bat                       start through the shared project workflow
├── armor.project.json                   manifest: version, role, maturity, build command
├── CHANGELOG.md                         what changed in each version
├── SECURITY.md SUPPORT.md LICENSE       security policy, support and license
├── CONTRIBUTING.md CODE_OF_CONDUCT.md   how to contribute and the code of conduct
├── build-test.sh build-test.bat         run the tests through the shared workflow
├── pyproject.toml                       package metadata
└── .gitattributes .gitignore            Git settings
```

</details>

## 🗺️ Roadmap & Known limits

**Known limits today**

* The geometry is illustrative, not a model of the real LD2450 radar, and nothing has been compared with real hardware.
* It speaks HTTP to a server only; publishing to an MQTT broker is deliberately not built in.

**Next**

* Compare the scenarios with recordings of the real radar once nodes are installed.

## 🌍 Languages

README and texts exist in English, Spanish, French, Italian, German, Chinese, Japanese and European Portuguese.

## 🔗 Related Projects

**A.R.M.O.R.** (Autonomous Radar & Multimodal Observation Range) is a perimeter-security system made of independent repositories. Each one has its own version, its own tests and its own README; this is the family:

* **[ARMOR-COMMON](https://github.com/JuanenRac/ARMOR-COMMON)** - Message contracts, validators, conformance vectors and generated types
* **[ARMOR-NODE-RADAR](https://github.com/JuanenRac/ARMOR-NODE-RADAR)** - Field-node firmware for ESP32-S3 with three radars and its own web panel
* **[ARMOR-NODE-SOLAR](https://github.com/JuanenRac/ARMOR-NODE-SOLAR)** - Solar inverter and battery protocols and the messages of a gateway node
* **[ARMOR-NODE-ELECTRICAL](https://github.com/JuanenRac/ARMOR-NODE-ELECTRICAL)** - Electrical node: meters, the message of the network's readings and the rules for switching
* **[ARMOR-NODE-ALARM](https://github.com/JuanenRac/ARMOR-NODE-ALARM)** - Alarm node and panel: zones, arming, delays, siren and PIN, with the server or without it
* **[ARMOR-NODE-HMI](https://github.com/JuanenRac/ARMOR-NODE-HMI)** - Touch panel: the state of the system on a wall screen, arming and acknowledging, and the home of the voice assistant
* **[ARMOR-NETWORK](https://github.com/JuanenRac/ARMOR-NETWORK)** - The local network: its devices, the internet and what changes
* **[ARMOR-SERVER](https://github.com/JuanenRac/ARMOR-SERVER)** - Central coordinator: telemetry, alarms, devices, solar readings and cameras
* **[ARMOR-STUDIO](https://github.com/JuanenRac/ARMOR-STUDIO)** - Web console: cameras, radar, alarms, solar energy and the 2D/3D site designer
* **[ARMOR-ANDROID-CONTROL](https://github.com/JuanenRac/ARMOR-ANDROID-CONTROL)** - Android operator client with a live 2D/3D radar
* **[ARMOR-IOS-CONTROL](https://github.com/JuanenRac/ARMOR-IOS-CONTROL)** - iPhone operator client
* **[ARMOR-SERVER-AI](https://github.com/JuanenRac/ARMOR-SERVER-AI)** - Visual inference policy that explains its decisions and never actuates
* **[ARMOR-VISION](https://github.com/JuanenRac/ARMOR-VISION)** - Camera zones, masks and detection rules for the Jetson Orin NX
* **[ARMOR-VOICE-AI](https://github.com/JuanenRac/ARMOR-VOICE-AI)** - Offline voice intents with a confirmation that cannot be forged
* **[ARMOR-HARDWARE](https://github.com/JuanenRac/ARMOR-HARDWARE)** - Enclosures, electronics and the bench acceptance matrix
* **[ARMOR-DEVOPS](https://github.com/JuanenRac/ARMOR-DEVOPS)** - Deployment, the CM5 test bench, backup and TLS
* **ARMOR-SIMULATOR** (this repository) - Offline telemetry simulator with repeatable faults
* **[ARMOR-UPDATER](https://github.com/JuanenRac/ARMOR-UPDATER)** - Detects, installs and updates the ecosystem's own repositories
* **[ARMOR-DOCS](https://github.com/JuanenRac/ARMOR-DOCS)** - Architecture, security baseline and the capability matrix

## 📚 Documentation

* [Usage](docs/USAGE.md): every option, scenario and fault
* [Alarm scenarios](docs/ALARM_SCENARIOS.md): the file format and how to verify a server's answer
* [Energy model](docs/ENERGY_MODEL.md): the realistic solar and electrical data and its settings
* [Capability matrix: what is proven and what is not](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/CAPABILITY_MATRIX.md)
* [Project catalogue: versions and how the repositories depend on each other](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/PROJECT_CATALOG.md)
* [Changelog of this repository](CHANGELOG.md)

## 🤝 Contributing & Community

* Before a pull request run `python -m unittest discover -s tests` and `python -I tools/armor_ci_validate.py`: it must pass. See [CONTRIBUTING.md](CONTRIBUTING.md) and the [code of conduct](CODE_OF_CONDUCT.md).
* The README exists in eight languages and is generated from the sources in ARMOR-DOCS: a change to the text is made there.
* A change to a message between components starts in ARMOR-COMMON.
* Do not describe as working on a board what has only been built.
* Report a vulnerability privately: [SECURITY.md](SECURITY.md). Questions, ideas and reports: electrohobby3d@gmail.com ([SUPPORT.md](SUPPORT.md)).

## 👤 AUTHOR

**JuanenRac (Electro Hobby 3D)** · electrohobby3d@gmail.com

## 📜 LICENSE

GPL-3.0-or-later - see [LICENSE](LICENSE).
