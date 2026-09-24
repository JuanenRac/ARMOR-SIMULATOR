<p align="center">
  <img src="images/ARMOR_BANNER.svg" alt="ARMOR-SIMULATOR banner" width="100%">
</p>

# 🧪 ARMOR-SIMULATOR

<p align="center"><a href="README.md">🇺🇸 English</a> | 🇪🇸 <b>Español</b></p>

### Simulador de telemetría sin conexión con fallos repetibles

<p align="center">
  <img src="https://img.shields.io/badge/License-GPL%203.0-blue.svg" alt="GPL 3.0">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-3776ab.svg" alt="Language">
  <img src="https://img.shields.io/badge/Dependencies-none-2ea44f.svg" alt="Dependencies">
  <img src="https://img.shields.io/badge/Maturity-functional-00E5FF.svg" alt="Maturity">
</p>

---

**Comprobación de honestidad - qué funciona hoy:** Los escenarios, los fallos, la entrega a un servidor y los 24 tests son reales. La geometría es **ilustrativa**, no un modelo del radar LD2450 real, y nada de esto se ha comparado con hardware real.

---

## 1. 🛠️ DESCRIPCIÓN

* **Escenarios:** `patrol`, `crossing`, `two-intruders` y `empty`, con una geometría de esquina de tres sensores, más un ciclo de luz día/noche o una noche fija.
* **Fallos repetibles:** nodo en silencio, mensajes desordenados y duplicados, nodo intermitente y mensajes inválidos a propósito (lux por encima del límite, campo desconocido, demasiadas pistas) para pruebas negativas.
* **Determinista:** la misma semilla imprime siempre las mismas líneas; no se envía nada salvo que indiques `--server-url` y `--ingest-token`.
* **Comprobado contra el contrato:** `--validate` pasa cada mensaje por ARMOR-COMMON antes de emitirlo.
* **Entrega cuidadosa:** solo se acepta un origen http(s) simple; un 4xx detiene la ejecución, un 5xx o un error de red se reintenta.

---

## 2. 🔧 COMPILAR Y EJECUTAR

```powershell
$env:PYTHONPATH="src"
python -m armor_simulator --count 20 --scenario crossing --seed 1 --validate
python -m unittest discover -s tests   # 24 tests
```

Opciones, escenarios y fallos completos: [uso](docs/USAGE.md).

---

## 📂 ESTRUCTURA DE DIRECTORIOS

```text
ARMOR-SIMULATOR/
├── src/armor_simulator/   scenarios, faults, publisher, cli
├── tests/                 24 tests, con un servidor HTTP local
└── docs/USAGE.md
```

---

## 👤 AUTOR

**JuanenRac (Electro Hobby 3D)** · electrohobby3d@gmail.com

## 📜 LICENCIA

GPL-3.0-or-later - véase [LICENSE](LICENSE).
