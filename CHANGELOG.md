# Changelog

All notable changes to this project are documented here.

## [0.2.0] - 2026-09-25

- Scenarios (`patrol`, `crossing`, `two-intruders`, `empty`), repeatable faults and `--validate` against ARMOR-COMMON.
- Careful HTTP delivery: plain origins only, 4xx stops, 5xx and network errors retry.
- 24 tests, including a local HTTP server.
