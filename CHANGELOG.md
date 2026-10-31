# Changelog

All notable changes to this project are documented here.

## [Unreleased]

- **Alarm scenarios in files:** `--alarm-scenario FILE` plays a JSON file (schema `armor-alarm-scenario/1`, documented in `docs/ALARM_SCENARIOS.md`) with a timeline of events: people who cross several zones one after another, a pet, wind, a sensor that is stuck, noisy, drifting or dead, a node that loses its link, a mains outage and the mode of the system, also by the calendar (home, away, night). The file may say what the system is expected to answer (which alarms, in which order, in which window of time, which ones must not happen); `--verify-alarms` compares the alarms a server raised with it and exits 1 when they differ, so the files serve as test cases for the server. `--check-alarm-scenario` only validates. The reading is strict and refuses the whole file at the first thing that is not understood. Eight examples are in `examples/alarm/`.
- **Realistic solar and electrical data:** `--energy` (with `--energy-config`, `--energy-days`, `--energy-step-s`) emits an inverter, a battery stack and an electrical node from a real-time model: a sun with clouds, a house that eats by the hour, a tariff, a Pylontech-style battery with cycles and a meter with noise and holes. Deterministic for a seed; every setting lives in a JSON file (`docs/ENERGY_MODEL.md`). Tests check that there is no production at night, the state of charge stays between its limits, the energy balances at every step and the counters never go down.
- Both are opt-in: without the new options the output is byte for byte what it was. Tests: 127 (before 63).

## [0.2.7] - The lights of Project status follow the evidence of the manifest and the pictures of the README from shared tools

- **The lights of Project status follow the evidence of the manifest:** the manifest says how far the repository has been shown to work (`evidence`: `host-test`, `simulator`, `bench` or `field`) and the validator fails when a light is above what that evidence and the maturity allow (`tools/status_lights.py`), so a green that never ran on real hardware cannot come back.
- **The layout of the README is checked in the CI:** the validator runs the shared `tools/universal_readme_check.py` and fails when the README differs from the universal layout.
- **The pictures of the README come from shared tools:** `tools/make_architecture.py` draws `images/architecture.svg` from `docs/architecture.json` and `tools/make_structure.py` draws the Repository Structure (the text tree and the animated picture) from `docs/structure.json`; both measure every text, and `--check` fails when a picture, its description or the code it points to disagree. They are vendored from ARMOR-COMMON like the shared CI checks.

## [0.2.6] - A node of 270 degrees and `--fault-topic`

- **A node of 270 degrees:** the three sensors face -75, 0 and +75 degrees (neighbours overlap by 45 degrees; only the 90 degrees behind the node are blind), like the radar node, instead of a 90 degree corner. `speed_mm_s` is now the radial speed seen by the sensor, negative when the object comes closer, instead of a constant per scenario.
- The repository has a security policy, a code of conduct, a contributing guide and a support file.
- The banner follows the animated style of the ecosystem banners, with the name, the kind and the technologies of the project.
- **`--fault-topic`** limits a fault to the radar node's telemetry, its health, the solar readings or the electrical node's, so one node can fall silent while the others go on talking; the count of `--fault-every` is of that kind, and a kind with nothing to spoil is refused.

## [0.2.5] - A night that is dark, dates the server believes, and tracks like the firmware sends them

- **`--light cycle` has a real night** and the same day as the solar and electrical sources (240 samples), from 0.3 lux to about 50 000 at noon; before the "night" was 4 000 lux and the sun rose ten times a day, so the day/night profile was never exercised.
- **`--start-ms`** dates the samples (`now` or a number); with the default `0` runs stay identical, but the server replaces such dates by its own clock, so `out-of-order` only means something with a real date. `--per-node-token` sends the token the strict server derives for each node; `--ingest-token-file` and `ARMOR_INGEST_TOKEN` keep the token out of the process list.
- **Tracks as the firmware sends them:** positions and speed are whole numbers, and a track keeps its id for as long as its object is in the scene (it was renumbered when another one left). The docstring says the angles are -45, 0 and +45 and that the real node is a 270 degree one.
- **One battery voltage:** the inverter and the battery stack agree (the inverter used to read up to 3 V above the sum of the cells).
- After delivering invalid messages the simulator says how many the server refused and how many it accepted; a URL with a hidden password or a fragment is refused; the 401 message names the right option; `--validate` says which message failed instead of a traceback; combinations that do nothing (`flapping` with no health messages, a fault every 0) are refused.
- Tests: 36 (before 31).

## [0.2.4] - Publisher fix

- Fix in the publisher, with a test.

## [0.2.3]

- A GitHub Actions CI baseline (`.github/workflows/ci.yml`): validates the manifest, the version, CHANGELOG.md's heading, the seven README translations' structure and its own local Markdown links, then runs this project's real build/test through `tools/armor_project_tool.py build-test .` (vendored from ARMOR-COMMON, alongside `tools/armor_ci_validate.py` and `tools/_armor_readme_parity.py`, which do the manifest/docs checking).
- **One day for every simulated source** (`cycle.py`): the solar and the electrical readings take the phase of a sample and the window of the mains outage from the same place, so they can never disagree about when the mains fail; a test compares them over three days.
- **A refusal says what to check:** a 401 or 403 names the ingest token, a 404 the server address, a 422 the contract, a 429 the rate limit; a 4xx is a settings problem and is still final, never retried.

## [0.2.2] - An electrical node

- `--electrical` also emits the three channels of an electrical node (the grid input, a water heater and a DC bus: voltage, current, power, energy, frequency, power factor) over a fast day, with a mains outage, a spell of high voltage and a meter alarm, so that the alarms of the electrical nodes can be seen; `--validate` runs them through ARMOR-COMMON and `--server-url` delivers them to `POST /api/v1/electrical/readings`. 28 tests.

## [0.2.1] - Solar equipment

- `--solar` also emits an inverter and a two-module battery stack (fifteen cells each, with capacities) over a fast day of 240 samples, with a mains outage late in the day; the messages are checked with `--validate` against the solar contract of ARMOR-COMMON and delivered to `/api/v1/solar` with `--server-url`. Tests: 26 (was 24).

## [0.2.0]

- Scenarios (`patrol`, `crossing`, `two-intruders`, `empty`), repeatable faults and `--validate` against ARMOR-COMMON.
- Careful HTTP delivery: plain origins only, 4xx stops, 5xx and network errors retry.
- 24 tests, including a local HTTP server.
