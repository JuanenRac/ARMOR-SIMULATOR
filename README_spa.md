<p align="center">
  <img src="images/ARMOR_BANNER.svg" alt="ARMOR-SIMULATOR banner" width="100%">
</p>

# 🧪 ARMOR-SIMULATOR

<p align="center">
  <a href="README.md">🇺🇸 English</a> |
  🇪🇸 <b>Español</b> |
  <a href="README_fra.md">🇫🇷 Français</a> |
  <a href="README_ita.md">🇮🇹 Italiano</a> |
  <a href="README_deu.md">🇩🇪 Deutsch</a> |
  <a href="README_zho.md">🇨🇳 简体中文</a> |
  <a href="README_jpn.md">🇯🇵 日本語</a> |
  <a href="README_por.md">🇵🇹 Português</a>
</p>

### Simulador de telemetría sin conexión con fallos repetibles

<p align="center">
  <img src="https://img.shields.io/badge/License-GPL%203.0-blue.svg" alt="GPL 3.0">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-3776ab.svg" alt="Language">
  <img src="https://img.shields.io/badge/Dependencies-none-2ea44f.svg" alt="Dependencies">
  <img src="https://img.shields.io/badge/Tests-57%20passing-2ea44f.svg" alt="Tests">
  <img src="https://img.shields.io/badge/Version-0.2.5-0f6cbd.svg" alt="Version">
  <img src="https://img.shields.io/badge/Maturity-established-2EA44F.svg" alt="Maturity">
</p>

---

**Comprobación de honestidad - qué funciona hoy:** Los escenarios, los fallos, la entrega a un servidor y los 57 tests son reales, y el simulador es lo que alimenta a un servidor en un ordenador cuando no hay ningún nodo conectado. La geometría es **ilustrativa**, no un modelo del radar LD2450 real, y nada de esto se ha comparado con hardware real.

---

## 📋 De un vistazo

| | |
|---|---|
| Versión | `0.2.5` |
| Madurez | Establecido |
| Tests | 57 (`python -m unittest discover -s tests`) |
| Tecnología | Python 3.11+ |
| En hardware real | No aplica: es el sustituto del hardware, usado en un ordenador |

## 🎯 Descripción general

* **Escenarios:** `patrol`, `crossing`, `two-intruders` y `empty`, con una geometría de 270 grados de tres sensores, más un ciclo de luz día/noche o una noche fija.
* **Fallos repetibles:** nodo en silencio, mensajes desordenados y duplicados, nodo intermitente y mensajes inválidos a propósito (lux por encima del límite, campo desconocido, demasiadas pistas) para pruebas negativas.
* **Determinista:** la misma semilla imprime siempre las mismas líneas; no se envía nada salvo que indiques `--server-url` y `--ingest-token`.
* **Comprobado contra el contrato:** `--validate` pasa cada mensaje por ARMOR-COMMON antes de emitirlo.
* **Entrega cuidadosa:** solo se acepta un origen http(s) simple; un 4xx detiene la ejecución, un 5xx o un error de red se reintenta.
* **Nodo eléctrico:** `--electrical` añade los tres canales de un nodo eléctrico (la entrada de red, un termo y un bus de continua) durante un día rápido, con un corte de red, un periodo de tensión alta y una alarma de contador.
* **Equipo solar:** `--solar` añade un inversor y una pila de baterías de dos módulos (quince celdas cada uno, con capacidades) durante un día rápido de 240 muestras, con un corte de red al final de la tarde; los mensajes se comprueban contra el contrato solar de ARMOR-COMMON y se entregan a `/api/v1/solar`.

## 🧩 Papel en A.R.M.O.R.

ARMOR-SIMULATOR es cómo se prueba el resto de la familia sin hardware: hace de nodo radar, de pasarela solar o de nodo eléctrico y envía sus mensajes a un [ARMOR-SERVER](https://github.com/JuanenRac/ARMOR-SERVER), con fallos que se pueden repetir, de modo que [ARMOR-STUDIO](https://github.com/JuanenRac/ARMOR-STUDIO) y la app móvil se vean funcionando con una casa que no existe. Cada mensaje que hace se comprueba contra los contratos de [ARMOR-COMMON](https://github.com/JuanenRac/ARMOR-COMMON).

## 📂 Estructura del repositorio

```text
ARMOR-SIMULATOR/
├── src/armor_simulator/   scenarios, faults, solar (inverter and battery messages), electrical (an electrical node), publisher, cli
├── tests/                 57 tests, including a local HTTP server
└── docs/USAGE.md
```

## 🛠️ Entorno de desarrollo

**Requisitos:** Python 3.11+ (standard library only)

```powershell
$env:PYTHONPATH="src"
python -m armor_simulator --count 20 --scenario crossing --seed 1 --validate
python -m unittest discover -s tests   # 57 tests
```

Opciones, escenarios y fallos completos: [uso](docs/USAGE.md).

## 🔗 Proyectos relacionados

**A.R.M.O.R.** (Autonomous Radar & Multimodal Observation Range) es un sistema de seguridad perimetral hecho de repositorios independientes. Cada uno tiene su propia versión, sus propias pruebas y su propio README; esta es la familia:

* **[ARMOR-COMMON](https://github.com/JuanenRac/ARMOR-COMMON)** - Contratos de mensajes, validadores, vectores de conformidad y tipos generados
* **[ARMOR-NODE-RADAR](https://github.com/JuanenRac/ARMOR-NODE-RADAR)** - Firmware del nodo de campo para ESP32-S3 con tres radares y su propio panel web
* **[ARMOR-NODE-SOLAR](https://github.com/JuanenRac/ARMOR-NODE-SOLAR)** - Protocolos de inversores y baterías solares y los mensajes de un nodo pasarela
* **[ARMOR-NODE-ELECTRICAL](https://github.com/JuanenRac/ARMOR-NODE-ELECTRICAL)** - Nodo eléctrico: contadores, el mensaje de las lecturas de la red y las reglas para maniobrar
* **[ARMOR-NODE-ALARM](https://github.com/JuanenRac/ARMOR-NODE-ALARM)** - Nodo y central de alarma: zonas, armado, retardos, sirena y PIN, con el servidor o sin él
* **[ARMOR-NODE-HMI](https://github.com/JuanenRac/ARMOR-NODE-HMI)** - Panel táctil: el estado del sistema en una pantalla de pared, armar y reconocer alarmas, y el hogar del asistente de voz
* **[ARMOR-NETWORK](https://github.com/JuanenRac/ARMOR-NETWORK)** - La red local: sus dispositivos, internet y lo que cambia
* **[ARMOR-SERVER](https://github.com/JuanenRac/ARMOR-SERVER)** - Coordinador central: telemetría, alarmas, dispositivos, lecturas solares y cámaras
* **[ARMOR-STUDIO](https://github.com/JuanenRac/ARMOR-STUDIO)** - Consola web: cámaras, radar, alarmas, energía solar y el diseñador de sitio 2D/3D
* **[ARMOR-ANDROID-CONTROL](https://github.com/JuanenRac/ARMOR-ANDROID-CONTROL)** - Cliente Android del operador con radar 2D/3D en vivo
* **[ARMOR-SERVER-AI](https://github.com/JuanenRac/ARMOR-SERVER-AI)** - Política de inferencia visual que explica sus decisiones y nunca actúa
* **[ARMOR-VISION](https://github.com/JuanenRac/ARMOR-VISION)** - Zonas de cámara, máscaras y reglas de detección para la Jetson Orin NX
* **[ARMOR-VOICE-AI](https://github.com/JuanenRac/ARMOR-VOICE-AI)** - Intenciones de voz sin conexión con una confirmación imposible de falsificar
* **[ARMOR-HARDWARE](https://github.com/JuanenRac/ARMOR-HARDWARE)** - Cajas, electrónica y la matriz de aceptación en banco
* **[ARMOR-DEVOPS](https://github.com/JuanenRac/ARMOR-DEVOPS)** - Despliegue, el banco de pruebas de la CM5, copias de seguridad y TLS
* **ARMOR-SIMULATOR** (este repositorio) - Simulador de telemetría sin conexión con fallos repetibles
* **[ARMOR-UPDATER](https://github.com/JuanenRac/ARMOR-UPDATER)** - Detecta, instala y actualiza los propios repositorios del ecosistema
* **[ARMOR-DOCS](https://github.com/JuanenRac/ARMOR-DOCS)** - Arquitectura, base de seguridad y la matriz de capacidades

## 📚 Documentación y comunidad

Dónde leer más:

* [Matriz de capacidades: qué está probado y qué no](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/CAPABILITY_MATRIX.md)
* [Catálogo de proyectos: versiones y cómo dependen unos de otros](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/PROJECT_CATALOG.md)
* [Historial de cambios de este repositorio](CHANGELOG.md)
* [Licencia (GPL-3.0-or-later)](LICENSE)
* Preguntas, ideas e informes: electrohobby3d@gmail.com

## 👤 AUTOR

**JuanenRac (Electro Hobby 3D)** · electrohobby3d@gmail.com

## 📜 LICENCIA

GPL-3.0-or-later - véase [LICENSE](LICENSE).
