# Changelog

All notable changes to this project are documented here.

## [0.2.1] - Solar equipment

- `--solar` also emits an inverter and a two-module battery stack (fifteen cells each, with capacities) over a fast day of 240 samples, with a mains outage late in the day; the messages are checked with `--validate` against the solar contract of ARMOR-COMMON and delivered to `/api/v1/solar` with `--server-url`. Tests: 26 (was 24).

## [0.2.0]

- Scenarios (`patrol`, `crossing`, `two-intruders`, `empty`), repeatable faults and `--validate` against ARMOR-COMMON.
- Careful HTTP delivery: plain origins only, 4xx stops, 5xx and network errors retry.
- 24 tests, including a local HTTP server.
