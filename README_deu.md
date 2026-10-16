<p align="center">
  <img src="images/ARMOR_BANNER.svg" alt="ARMOR-SIMULATOR banner" width="100%">
</p>

# 🧪 ARMOR-SIMULATOR

<p align="center">
  <a href="README.md">🇺🇸 English</a> |
  <a href="README_spa.md">🇪🇸 Español</a> |
  <a href="README_fra.md">🇫🇷 Français</a> |
  <a href="README_ita.md">🇮🇹 Italiano</a> |
  🇩🇪 <b>Deutsch</b> |
  <a href="README_zho.md">🇨🇳 简体中文</a> |
  <a href="README_jpn.md">🇯🇵 日本語</a> |
  <a href="README_por.md">🇵🇹 Português</a>
</p>

### Offline-Telemetriesimulator mit wiederholbaren Fehlern

<p align="center">
  <img src="https://img.shields.io/badge/License-GPL%203.0-blue.svg" alt="GPL 3.0">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-3776ab.svg" alt="Language">
  <img src="https://img.shields.io/badge/Dependencies-none-2ea44f.svg" alt="Dependencies">
  <img src="https://img.shields.io/badge/Tests-31%20passing-2ea44f.svg" alt="Tests">
  <img src="https://img.shields.io/badge/Version-0.2.4-0f6cbd.svg" alt="Version">
  <img src="https://img.shields.io/badge/Maturity-established-2EA44F.svg" alt="Maturity">
</p>

---

**Ehrlichkeitsprüfung - was heute läuft:** Die Szenarien, die Fehler, die Zustellung an einen Server und die 31 Tests sind real, und der Simulator speist einen Server auf einem Computer, wenn kein Knoten angeschlossen ist. Die Geometrie ist **veranschaulichend**, kein Modell des echten LD2450-Radars, und nichts davon wurde mit echter Hardware verglichen.

---

## 📋 Auf einen Blick

| | |
|---|---|
| Version | `0.2.4` |
| Reifegrad | Etabliert |
| Tests | 31 (`python -m unittest discover -s tests`) |
| Technik | Python 3.11+ |
| Auf echter Hardware | Nicht zutreffend: er ist der Hardware-Ersatz, auf einem Computer benutzt |

## 🎯 Überblick

* **Szenarien:** `patrol`, `crossing`, `two-intruders` und `empty` auf einer Eckgeometrie mit drei Sensoren, dazu ein Tag/Nacht-Lichtzyklus oder eine feste Nacht.
* **Wiederholbare Fehler:** ein stummer Knoten, vertauschte und doppelte Nachrichten, ein flatternder Knoten und absichtlich ungültige Nachrichten (Lux über dem Limit, unbekanntes Feld, zu viele Spuren) für Negativtests.
* **Deterministisch:** derselbe Seed druckt immer dieselben Zeilen; gesendet wird nur mit `--server-url` und `--ingest-token`.
* **Gegen den Vertrag geprüft:** `--validate` schickt jede Nachricht vor dem Ausgeben durch ARMOR-COMMON.
* **Sorgfältige Übermittlung:** nur ein einfacher http(s)-Ursprung wird akzeptiert; ein 4xx stoppt den Lauf, ein 5xx oder ein Netzwerkfehler wird wiederholt.
* **Elektroknoten:** `--electrical` fügt die drei Kanäle eines Elektroknotens hinzu (den Netzanschluss, einen Warmwasserspeicher und einen Gleichstrombus) über einen schnellen Tag, mit einem Netzausfall, einer Phase hoher Spannung und einem Zähleralarm.
* **Solaranlage:** `--solar` fügt einen Wechselrichter und einen Batteriestapel aus zwei Modulen (je fünfzehn Zellen, mit Kapazitäten) über einen Zeitraffer-Tag von 240 Werten hinzu, mit einem Netzausfall am späten Tag; die Nachrichten werden gegen den Solar-Vertrag von ARMOR-COMMON geprüft und an `/api/v1/solar` geliefert.

## 🧩 Rolle in A.R.M.O.R.

ARMOR-SIMULATOR ist die Art, den Rest der Familie ohne Hardware auszuprobieren: Er spielt die Rolle eines Radarknotens, eines Solar-Gateways oder eines Elektroknotens und sendet deren Nachrichten an einen [ARMOR-SERVER](https://github.com/JuanenRac/ARMOR-SERVER), mit wiederholbaren Fehlern, sodass [ARMOR-STUDIO](https://github.com/JuanenRac/ARMOR-STUDIO) und die Handy-App mit einem Haus, das es nicht gibt, arbeiten. Jede erzeugte Nachricht wird gegen die Verträge von [ARMOR-COMMON](https://github.com/JuanenRac/ARMOR-COMMON) geprüft.

## 📂 Struktur des Repositorys

```text
ARMOR-SIMULATOR/
├── src/armor_simulator/   scenarios, faults, solar (inverter and battery messages), electrical (an electrical node), publisher, cli
├── tests/                 31 tests, including a local HTTP server
└── docs/USAGE.md
```

## 🛠️ Entwicklungsumgebung

**Voraussetzungen:** Python 3.11+ (standard library only)

```powershell
$env:PYTHONPATH="src"
python -m armor_simulator --count 20 --scenario crossing --seed 1 --validate
python -m unittest discover -s tests   # 31 tests
```

Alle Optionen, Szenarien und Fehler: [Verwendung](docs/USAGE.md).

## 🔗 Verwandte Projekte

**A.R.M.O.R.** (Autonomous Radar & Multimodal Observation Range) ist ein Perimeter-Sicherheitssystem aus unabhängigen Repositorys. Jedes hat eine eigene Version, eigene Tests und ein eigenes README; hier ist die Familie:

* **[ARMOR-COMMON](https://github.com/JuanenRac/ARMOR-COMMON)** - Nachrichtenverträge, Validierer, Konformitätsvektoren und generierte Typen
* **[ARMOR-RADAR](https://github.com/JuanenRac/ARMOR-RADAR)** - Feldknoten-Firmware für ESP32-S3 mit drei Radaren und eigenem Web-Panel
* **[ARMOR-SOLAR](https://github.com/JuanenRac/ARMOR-SOLAR)** - Protokolle für Solar-Wechselrichter und -Batterien und die Nachrichten eines Gateway-Knotens
* **[ARMOR-ELECTRICAL](https://github.com/JuanenRac/ARMOR-ELECTRICAL)** - Elektroknoten: Zähler, die Nachricht der Netzmesswerte und die Regeln fürs Schalten
* **[ARMOR-ALARM](https://github.com/JuanenRac/ARMOR-ALARM)** - Alarmknoten und Alarmzentrale: Zonen, Scharfschalten, Verzögerungen, Sirene und PIN, mit dem Server oder ohne ihn
* **[ARMOR-HMI](https://github.com/JuanenRac/ARMOR-HMI)** - Touch-Panel: der Systemzustand auf einem Wandbildschirm, Scharf- und Quittieren sowie das Zuhause des Sprachassistenten
* **[ARMOR-NETWORK](https://github.com/JuanenRac/ARMOR-NETWORK)** - Das lokale Netzwerk: seine Geräte, das Internet und was sich ändert
* **[ARMOR-SERVER](https://github.com/JuanenRac/ARMOR-SERVER)** - Zentraler Koordinator: Telemetrie, Alarme, Geräte, Solarmesswerte und Kameras
* **[ARMOR-STUDIO](https://github.com/JuanenRac/ARMOR-STUDIO)** - Web-Konsole: Kameras, Radar, Alarme, Solarenergie und 2D/3D-Standortdesigner
* **[ARMOR-ANDROID-CONTROL](https://github.com/JuanenRac/ARMOR-ANDROID-CONTROL)** - Android-Bedienclient mit Live-Radar in 2D/3D
* **[ARMOR-SERVER-AI](https://github.com/JuanenRac/ARMOR-SERVER-AI)** - Visuelle Inferenzrichtlinie, die ihre Entscheidungen erklärt und nie handelt
* **[ARMOR-VISION](https://github.com/JuanenRac/ARMOR-VISION)** - Kamerazonen, Masken und Erkennungsregeln für den Jetson Orin NX
* **[ARMOR-VOICE-AI](https://github.com/JuanenRac/ARMOR-VOICE-AI)** - Offline-Sprachabsichten mit einer nicht fälschbaren Bestätigung
* **[ARMOR-HARDWARE](https://github.com/JuanenRac/ARMOR-HARDWARE)** - Gehäuse, Elektronik und die Abnahmematrix am Prüfstand
* **[ARMOR-DEVOPS](https://github.com/JuanenRac/ARMOR-DEVOPS)** - Bereitstellung, CM5-Prüfstand, Backup und TLS
* **ARMOR-SIMULATOR** (dieses Repository) - Offline-Telemetriesimulator mit wiederholbaren Fehlern
* **[ARMOR-UPDATER](https://github.com/JuanenRac/ARMOR-UPDATER)** - Erkennt, installiert und aktualisiert die eigenen Repositories des Ökosystems
* **[ARMOR-DOCS](https://github.com/JuanenRac/ARMOR-DOCS)** - Architektur, Sicherheitsgrundlage und die Fähigkeitsmatrix

## 📚 Dokumentation und Community

Hier gibt es mehr zu lesen:

* [Fähigkeitsmatrix: was belegt ist und was nicht](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/CAPABILITY_MATRIX.md)
* [Projektkatalog: Versionen und wie die Repositorys voneinander abhängen](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/PROJECT_CATALOG.md)
* [Änderungsverlauf dieses Repositorys](CHANGELOG.md)
* [Lizenz (GPL-3.0-or-later)](LICENSE)
* Fragen, Ideen und Meldungen: electrohobby3d@gmail.com

## 👤 AUTOR

**JuanenRac (Electro Hobby 3D)** · electrohobby3d@gmail.com

## 📜 LIZENZ

GPL-3.0-or-later - siehe [LICENSE](LICENSE).
