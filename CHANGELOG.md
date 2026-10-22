# Changelog

All notable changes to this project are documented here.

## [Unreleased]

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
