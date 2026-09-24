<p align="center">
  <img src="images/ARMOR_BANNER.svg" alt="ARMOR-SIMULATOR banner" width="100%">
</p>

# 🧪 ARMOR-SIMULATOR

<p align="center">🇺🇸 <b>English</b> | <a href="README_spa.md">🇪🇸 Español</a></p>

### Offline telemetry simulator with repeatable faults

<p align="center">
  <img src="https://img.shields.io/badge/License-GPL%203.0-blue.svg" alt="GPL 3.0">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-3776ab.svg" alt="Language">
  <img src="https://img.shields.io/badge/Dependencies-none-2ea44f.svg" alt="Dependencies">
  <img src="https://img.shields.io/badge/Maturity-functional-00E5FF.svg" alt="Maturity">
</p>

---

**Honesty check - what runs today:** Scenarios, faults, delivery to a server and the 24 tests are real. The geometry is **illustrative**, not a model of the real LD2450 radar, and nothing here has been compared with real hardware.

---

## 1. 🛠️ OVERVIEW

* **Scenarios:** `patrol`, `crossing`, `two-intruders` and `empty`, on a three-sensor corner geometry, plus a day/night light cycle or a fixed night.
* **Repeatable faults:** a silent node, out-of-order and duplicated messages, a flapping node, and deliberately invalid messages (lux over the limit, unknown field, too many tracks) for negative tests.
* **Deterministic:** the same seed always prints the same lines; nothing is sent unless you give `--server-url` and `--ingest-token`.
* **Checked against the contract:** `--validate` runs every message through ARMOR-COMMON before it is emitted.
* **Careful delivery:** only a plain http(s) origin is accepted; a 4xx stops the run, a 5xx or a network error is retried.

---

## 2. 🔧 BUILD & RUN

```powershell
$env:PYTHONPATH="src"
python -m armor_simulator --count 20 --scenario crossing --seed 1 --validate
python -m unittest discover -s tests   # 24 tests
```

Full options, scenarios and faults: [usage](docs/USAGE.md).

---

## 📂 DIRECTORY STRUCTURE

```text
ARMOR-SIMULATOR/
├── src/armor_simulator/   scenarios, faults, publisher, cli
├── tests/                 24 tests, including a local HTTP server
└── docs/USAGE.md
```

---

## 👤 AUTHOR

**JuanenRac (Electro Hobby 3D)** · electrohobby3d@gmail.com

## 📜 LICENSE

GPL-3.0-or-later - see [LICENSE](LICENSE).
