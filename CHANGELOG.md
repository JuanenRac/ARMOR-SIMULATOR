# Changelog

All notable changes to this project are documented here.

## [0.2.3]

- A GitHub Actions CI baseline (`.github/workflows/ci.yml`): validates the manifest, the version, CHANGELOG.md's heading, the seven README translations' structure and its own local Markdown links, then runs this project's real build/test through `tools/armor_project_tool.py build-test .` (vendored from ARMOR-COMMON, alongside `tools/armor_ci_validate.py` and `tools/_armor_readme_parity.py`, which do the manifest/docs checking).

## [0.2.2] - An electrical node

- `--electrical` also emits the three channels of an electrical node (the grid input, a water heater and a DC bus: voltage, current, power, energy, frequency, power factor) over a fast day, with a mains outage, a spell of high voltage and a meter alarm, so that the alarms of the electrical nodes can be seen; `--validate` runs them through ARMOR-COMMON and `--server-url` delivers them to `POST /api/v1/electrical/readings`. 28 tests.

## [0.2.1] - Solar equipment

- `--solar` also emits an inverter and a two-module battery stack (fifteen cells each, with capacities) over a fast day of 240 samples, with a mains outage late in the day; the messages are checked with `--validate` against the solar contract of ARMOR-COMMON and delivered to `/api/v1/solar` with `--server-url`. Tests: 26 (was 24).

## [0.2.0]

- Scenarios (`patrol`, `crossing`, `two-intruders`, `empty`), repeatable faults and `--validate` against ARMOR-COMMON.
- Careful HTTP delivery: plain origins only, 4xx stops, 5xx and network errors retry.
- 24 tests, including a local HTTP server.
