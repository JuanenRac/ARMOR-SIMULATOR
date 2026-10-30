<p align="center">
  <img src="images/ARMOR_BANNER.svg" alt="ARMOR-SIMULATOR-Banner" width="100%">
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
  <img src="https://img.shields.io/badge/License-GPL%203.0--or--later-blue.svg" alt="GPL 3.0 oder neuer">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-3776ab.svg" alt="Sprache">
  <img src="https://img.shields.io/badge/Dependencies-none-2ea44f.svg" alt="Dependencies">
  <img src="https://img.shields.io/badge/Tests-63%20passing-2ea44f.svg" alt="Tests">
  <img src="https://img.shields.io/badge/Version-0.2.7-0f6cbd.svg" alt="Version">
  <img src="https://img.shields.io/badge/Maturity-established-2EA44F.svg" alt="Reifegrad">
</p>

---

**Ehrlichkeitsprüfung - was heute läuft:** Die Szenarien, die Fehler, die Zustellung an einen Server und die 63 Tests sind real, und der Simulator speist einen Server auf einem Computer, wenn kein Knoten angeschlossen ist. Die Geometrie ist **veranschaulichend**, kein Modell des echten LD2450-Radars, und nichts davon wurde mit echter Hardware verglichen.

---

## 📋 Auf einen Blick

| | |
|---|---|
| Version | `0.2.7` |
| Reifegrad | Etabliert |
| Rolle | Offline-Simulator für Telemetrie und Umgebung (Familie: Testing, übergeordnet: ARMOR-COMMON) |
| Technik | Python 3.11+, nur Standardbibliothek |
| Tests | 63 (`python -m unittest discover -s tests`) |
| Szenarien und Fehler | 4 Szenarien, 7 Fehler (3 brechen den Vertrag absichtlich) |
| Läuft auf | Jeder Computer oder CI |
| Auf echter Hardware | Nicht zutreffend: er ist der Hardware-Ersatz, auf einem Computer benutzt |
| Lizenz | GPL-3.0-or-later |

**Springe zu:** [Überblick](#-überblick) · [Architektur](#-architektur) · [Sicherheit](#-sicherheit-und-schutz) · [Schnittstellen](#-schnittstellen) · [Konfiguration](#-konfiguration) · [Schnellstart](#-schnellstart) · [Tests](#-tests) · [Probleme](#-fehlerbehebung) · [Struktur](#-struktur-des-repositorys) · [Verwandte](#-verwandte-projekte)

## 🚦 Projektstatus

Jede Zeile ist ein Teil dieses Repositorys, und die Ampel sagt, wie weit er heute ist. Sie beruht auf dem, was das Repository zeigen kann (Tests, Builds, Läufe), nicht auf dem, was geplant ist.

🟢 Fertig und überprüft · 🟡 Funktioniert, mit bekannten Grenzen · 🟠 Teilweise fertig oder noch nicht überprüft · 🔴 Nicht gemacht oder funktioniert nicht

| Bereich | Stand | Was das hier bedeutet |
|---|---|---|
| Software | 🟢 | Die Szenarien, die Störungen und die Übergabe an einen Server funktionieren; er speist einen Server auf einem Rechner, wenn kein Knoten angeschlossen ist. |
| Tests | 🟢 | 63 Tests bestehen (`python -m unittest discover -s tests`). |
| Protokolle und Daten | 🟠 | Die Geometrie ist anschaulich und kein Modell des echten LD2450-Radars, und nichts wurde mit echter Hardware verglichen. |
| Integration | 🟢 | Er übergibt seine Nachrichten in den Tests an einen Server, und der Server des CM5-Prüfstands kann damit gespeist werden. |
| Dokumentation | 🟢 | Acht Sprachen und das Änderungsprotokoll sind aktuell. |

## 🎯 Überblick

* **Szenarien:** `patrol`, `crossing`, `two-intruders` und `empty` auf einer 270-Grad-Geometrie mit drei Sensoren, dazu ein Tag/Nacht-Lichtzyklus oder eine feste Nacht.
* **Wiederholbare Fehler:** ein stummer Knoten, vertauschte und doppelte Nachrichten, ein flatternder Knoten und absichtlich ungültige Nachrichten (Lux über dem Limit, unbekanntes Feld, zu viele Spuren) für Negativtests.
* **Deterministisch:** derselbe Seed druckt immer dieselben Zeilen; gesendet wird nur mit `--server-url` und `--ingest-token`.
* **Gegen den Vertrag geprüft:** `--validate` schickt jede Nachricht vor dem Ausgeben durch ARMOR-COMMON.
* **Sorgfältige Übermittlung:** nur ein einfacher http(s)-Ursprung wird akzeptiert; ein 4xx stoppt den Lauf, ein 5xx oder ein Netzwerkfehler wird wiederholt.
* **Elektroknoten:** `--electrical` fügt die drei Kanäle eines Elektroknotens hinzu (den Netzanschluss, einen Warmwasserspeicher und einen Gleichstrombus) über einen schnellen Tag, mit einem Netzausfall, einer Phase hoher Spannung und einem Zähleralarm.
* **Solaranlage:** `--solar` fügt einen Wechselrichter und einen Batteriestapel aus zwei Modulen (je fünfzehn Zellen, mit Kapazitäten) über einen Zeitraffer-Tag von 240 Werten hinzu, mit einem Netzausfall am späten Tag; die Nachrichten werden gegen den Solar-Vertrag von ARMOR-COMMON geprüft und an `/api/v1/solar` geliefert.

## 🧩 Rolle in A.R.M.O.R.

ARMOR-SIMULATOR ist die Art, den Rest der Familie ohne Hardware auszuprobieren: Er spielt die Rolle eines Radarknotens, eines Solar-Gateways oder eines Elektroknotens und sendet deren Nachrichten an einen [ARMOR-SERVER](https://github.com/JuanenRac/ARMOR-SERVER), mit wiederholbaren Fehlern, sodass [ARMOR-STUDIO](https://github.com/JuanenRac/ARMOR-STUDIO) und die Handy-App mit einem Haus, das es nicht gibt, arbeiten. Jede erzeugte Nachricht wird gegen die Verträge von [ARMOR-COMMON](https://github.com/JuanenRac/ARMOR-COMMON) geprüft.

| Name | Wie | Wozu |
|---|---|---|
| ARMOR-SERVER | `POST /api/v1/telemetry`, `/health`, `/solar`, `/electrical/readings` | Empfängt die simulierten Nachrichten |
| ARMOR-COMMON | `--validate` | Die Verträge, gegen die jede Nachricht geprüft wird |
| ARMOR-STUDIO, ARMOR-ANDROID-CONTROL | über den Server | Zeigen das simulierte Haus |

## 🏛️ Architektur

<p align="center">
  <img src="images/architecture.svg" alt="Architektur von ARMOR-SIMULATOR: wer es aufruft, was es enthält und wovon es abhängt" width="100%">
</p>

## 🔒 Sicherheit und Schutz

| Bedrohung | Abwehr |
|---|---|
| Senden an ein fremdes Ziel | Nur ein einfacher http(s)-Ursprung wird akzeptiert (ohne Pfad und Zugangsdaten); ein 4xx stoppt den Lauf, ein 5xx oder Netzfehler wird dreimal wiederholt |
| Das Token erscheint in der Prozessliste | `--ingest-token` wird nicht empfohlen; nutze `ARMOR_INGEST_TOKEN` oder `--ingest-token-file`; nichts schreibt das Token irgendwohin |
| Ein Test erreicht versehentlich einen echten Server | Es wird nichts gesendet, außer du gibst `--server-url` und ein Token an; es gibt gar keinen Broker-Client |
| Absichtlich vertragsbrechende Nachrichten | `corrupt-lux`, `unknown-field` und `oversized-targets` brauchen `--allow-invalid` und sind nicht mit `--validate` kombinierbar |
| Feindliche Eingabe auf der Kommandozeile | Die Knoten-ID muss `^[a-z0-9][a-z0-9_-]{0,63}$` erfüllen und `--count` liegt zwischen 1 und 10 000 |

Dies ist ein Testwerkzeug: keine Sicherheitsfunktion, und seine Geometrie ist kein Modell des echten Radars.

## 🔌 Schnittstellen

| Option | Standard | Was sie festlegt |
|---|---|---|
| `--scenario` | `patrol` | `patrol`, `crossing`, `two-intruders`, `empty` |
| `--count` | `1` | Messwerte (1 bis 10 000); einer ist eine Sekunde |
| `--seed` | `0` | Gleicher Seed, gleiche Zeilen |
| `--light` | `cycle` | `cycle` (Tag und Nacht) oder `night` (fest 0,3 lx) |
| `--solar`, `--electrical` | off | Sendet zusätzlich Wechselrichter mit Batterien / einen Elektroknoten |
| `--fault`, `--fault-every`, `--fault-topic` | `none`, `3`, `all` | Spielt in einige Nachrichten einen wiederholbaren Fehler ein |
| `--validate`, `--allow-invalid` | off | Prüft jede Nachricht gegen ARMOR-COMMON / erlaubt Fehler, die ihn brechen |
| `--server-url`, `--ingest-token-file`, `--per-node-token` | - | Zustellung an ARMOR-SERVER; das Token jedes Knotens bei striktem Server |

Alle Optionen, Szenarien und Fehler stehen in [docs/USAGE.md](docs/USAGE.md). Nachrichten: `armor/node/<id>/telemetry` und `health`, `armor/solar/<Knoten>/<Gerät>/state`, `armor/electrical/<Knoten>/state`; zugestellt wird an `/api/v1/telemetry`, `/api/v1/health`, `/api/v1/solar` und `/api/v1/electrical/readings`.

## ⚙️ Konfiguration

| Variable | Nötig | Was sie festlegt |
|---|---|---|
| `ARMOR_INGEST_TOKEN` | mit `--server-url` | Das Ingest-Token des Servers (oder eine Zeile `ARMOR_INGEST_TOKEN=...` in der Datei von `--ingest-token-file`) |
| `PYTHONPATH=src` | aus dem Checkout | Wo das Paket gefunden wird |

| Grenze | Wert |
|---|---|
| Messwerte pro Lauf | 1 - 10 000 |
| Sensoren und Sichtfeld | 3 (-75, 0, +75°) × ±60°, 6000 mm |
| Ein Tag Licht, Solar und Elektro | 240 Messwerte |
| Zustellversuche / Zeitlimit | 3 / 5 s |

## 🚀 Schnellstart

**Voraussetzungen:** Python 3.11+ (nur Standardbibliothek).

```powershell
$env:PYTHONPATH = "src"
python -m armor_simulator --count 20 --scenario crossing --seed 1 --validate
python -m armor_simulator --count 60 --scenario two-intruders --server-url http://127.0.0.1:8080 --ingest-token-file token.env
```

## 🧪 Tests

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
python -I tools/armor_ci_validate.py
```

| Testdatei | Tests | Was sie abdeckt |
|---|---|---|
| `test_simulator.py` | 37 | Szenarien, Fehler, Solar, Elektro, Validierung, Zustellung an einen lokalen HTTP-Server |
| `test_cli_options.py` | 26 | Die Optionen, ihre Grenzen und die Ablehnungen |

## 🏗️ Build und Veröffentlichung

Es ist reines Python: nichts zu kompilieren. Die Version steht in `pyproject.toml` und `armor.project.json`.

## 🩺 Fehlerbehebung

| Sie sehen | Weil | Tun Sie |
|---|---|---|
| `--server-url needs a token ...` | Eine URL ohne Token oder ein Token ohne URL | Gib beide an |
| HTTP 401 / 403 | Das Ingest-Token ist falsch; ein strikter Server will ein Token je Knoten | `--per-node-token` |
| `--allow-invalid` | Der Fehler bricht den Vertrag absichtlich | Füge es hinzu und nutze nicht `--validate` |
| Der Server hält die Nachrichten für alt | Das Standard-Startdatum ist 0 und der Server ersetzt es | `--start-ms now` |

## 📂 Struktur des Repositorys

<p align="center">
  <img src="images/repository-structure.svg" alt="Repository-Struktur von ARMOR-SIMULATOR" width="100%">
</p>

<details>
<summary>Textversion des Baums</summary>

```text
ARMOR-SIMULATOR/
├── src/armor_simulator/
│   ├── cli.py                           die Optionen und der Ablauf
│   ├── scenarios.py cycle.py            die vier Szenarien, die 270-Grad-Geometrie und der Lichttag
│   ├── solar.py                         ein Wechselrichter und ein Batteriestapel aus zwei Modulen
│   ├── electrical.py                    die drei Kanäle eines Elektroknotens
│   ├── faults.py                        die sieben wiederholbaren Fehler
│   └── publisher.py                     Zustellung an einen Server mit Wiederholungen
├── tests/                               die Tests
├── docs/                                die Anleitungen dieses Repositorys
├── tools/                               die gemeinsamen CI-Prüfungen und Projektwerkzeuge
├── .github/                             CI-Workflow sowie Vorlagen für Issues und Pull Requests
├── images/                              Banner, Symbol und die zwei Bilder dieses READMEs
├── build.sh build.bat                   Build über den gemeinsamen Projekt-Workflow
├── test.sh test.bat                     Tests über den gemeinsamen Workflow ausführen
├── run.sh run.bat                       Start über den gemeinsamen Projekt-Workflow
├── armor.project.json                   Manifest: Version, Rolle, Reifegrad, Build-Befehl
├── CHANGELOG.md                         was sich in jeder Version geändert hat
├── SECURITY.md SUPPORT.md LICENSE       Sicherheitsrichtlinie, Support und Lizenz
├── CONTRIBUTING.md CODE_OF_CONDUCT.md   Mitwirkung und Verhaltenskodex
├── build-test.sh build-test.bat         Tests über den gemeinsamen Workflow ausführen
├── pyproject.toml                       Paketmetadaten
└── .gitattributes .gitignore            Git-Einstellungen
```

</details>

## 🗺️ Roadmap und bekannte Grenzen

**Bekannte Grenzen heute**

* Die Geometrie ist illustrativ, kein Modell des echten LD2450-Radars, und nichts wurde mit echter Hardware verglichen.
* Er spricht nur HTTP mit einem Server; das Veröffentlichen an einen MQTT-Broker ist absichtlich nicht eingebaut.

**Als Nächstes**

* Die Szenarien mit Aufzeichnungen des echten Radars vergleichen, sobald Knoten installiert sind.

## 🌍 Sprachen

README und Texte gibt es auf Englisch, Spanisch, Französisch, Italienisch, Deutsch, Chinesisch, Japanisch und europäischem Portugiesisch.

## 🔗 Verwandte Projekte

**A.R.M.O.R.** (Autonomous Radar & Multimodal Observation Range) ist ein Perimeter-Sicherheitssystem aus unabhängigen Repositorys. Jedes hat eine eigene Version, eigene Tests und ein eigenes README; hier ist die Familie:

* **[ARMOR-COMMON](https://github.com/JuanenRac/ARMOR-COMMON)** - Nachrichtenverträge, Validierer, Konformitätsvektoren und generierte Typen
* **[ARMOR-NODE-RADAR](https://github.com/JuanenRac/ARMOR-NODE-RADAR)** - Feldknoten-Firmware für ESP32-S3 mit drei Radaren und eigenem Web-Panel
* **[ARMOR-NODE-SOLAR](https://github.com/JuanenRac/ARMOR-NODE-SOLAR)** - Protokolle für Solar-Wechselrichter und -Batterien und die Nachrichten eines Gateway-Knotens
* **[ARMOR-NODE-ELECTRICAL](https://github.com/JuanenRac/ARMOR-NODE-ELECTRICAL)** - Elektroknoten: Zähler, die Nachricht der Netzmesswerte und die Regeln fürs Schalten
* **[ARMOR-NODE-ALARM](https://github.com/JuanenRac/ARMOR-NODE-ALARM)** - Alarmknoten und Alarmzentrale: Zonen, Scharfschalten, Verzögerungen, Sirene und PIN, mit dem Server oder ohne ihn
* **[ARMOR-NODE-HMI](https://github.com/JuanenRac/ARMOR-NODE-HMI)** - Touch-Panel: der Systemzustand auf einem Wandbildschirm, Scharf- und Quittieren sowie das Zuhause des Sprachassistenten
* **[ARMOR-NETWORK](https://github.com/JuanenRac/ARMOR-NETWORK)** - Das lokale Netzwerk: seine Geräte, das Internet und was sich ändert
* **[ARMOR-SERVER](https://github.com/JuanenRac/ARMOR-SERVER)** - Zentraler Koordinator: Telemetrie, Alarme, Geräte, Solarmesswerte und Kameras
* **[ARMOR-STUDIO](https://github.com/JuanenRac/ARMOR-STUDIO)** - Web-Konsole: Kameras, Radar, Alarme, Solarenergie und 2D/3D-Standortdesigner
* **[ARMOR-ANDROID-CONTROL](https://github.com/JuanenRac/ARMOR-ANDROID-CONTROL)** - Android-Bedienclient mit Live-Radar in 2D/3D
* **[ARMOR-IOS-CONTROL](https://github.com/JuanenRac/ARMOR-IOS-CONTROL)** - iPhone-Bedienclient
* **[ARMOR-SERVER-AI](https://github.com/JuanenRac/ARMOR-SERVER-AI)** - Visuelle Inferenzrichtlinie, die ihre Entscheidungen erklärt und nie handelt
* **[ARMOR-VISION](https://github.com/JuanenRac/ARMOR-VISION)** - Kamerazonen, Masken und Erkennungsregeln für den Jetson Orin NX
* **[ARMOR-VOICE-AI](https://github.com/JuanenRac/ARMOR-VOICE-AI)** - Offline-Sprachabsichten mit einer nicht fälschbaren Bestätigung
* **[ARMOR-HARDWARE](https://github.com/JuanenRac/ARMOR-HARDWARE)** - Gehäuse, Elektronik und die Abnahmematrix am Prüfstand
* **[ARMOR-DEVOPS](https://github.com/JuanenRac/ARMOR-DEVOPS)** - Bereitstellung, CM5-Prüfstand, Backup und TLS
* **ARMOR-SIMULATOR** (dieses Repository) - Offline-Telemetriesimulator mit wiederholbaren Fehlern
* **[ARMOR-UPDATER](https://github.com/JuanenRac/ARMOR-UPDATER)** - Erkennt, installiert und aktualisiert die eigenen Repositorys des Ökosystems
* **[ARMOR-DOCS](https://github.com/JuanenRac/ARMOR-DOCS)** - Architektur, Sicherheitsgrundlage und die Fähigkeitsmatrix

## 📚 Dokumentation

* [Verwendung](docs/USAGE.md): alle Optionen, Szenarien und Fehler
* [Fähigkeitsmatrix: was belegt ist und was nicht](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/CAPABILITY_MATRIX.md)
* [Projektkatalog: Versionen und wie die Repositorys voneinander abhängen](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/PROJECT_CATALOG.md)
* [Änderungsverlauf dieses Repositorys](CHANGELOG.md)

## 🤝 Mitwirken und Community

* Führe vor einem Pull Request `python -m unittest discover -s tests` and `python -I tools/armor_ci_validate.py` aus: Es muss bestehen. Siehe [CONTRIBUTING.md](CONTRIBUTING.md) und den [Verhaltenskodex](CODE_OF_CONDUCT.md).
* Das README gibt es in acht Sprachen, und es wird aus den Quellen in ARMOR-DOCS erzeugt: Eine Textänderung erfolgt dort.
* Eine Änderung an einer Nachricht zwischen Komponenten beginnt in ARMOR-COMMON.
* Beschreibe nichts als auf einer Platine funktionierend, was nur gebaut wurde.
* Melde eine Schwachstelle privat: [SECURITY.md](SECURITY.md). Fragen, Ideen und Meldungen: electrohobby3d@gmail.com ([SUPPORT.md](SUPPORT.md)).

## 👤 AUTOR

**JuanenRac (Electro Hobby 3D)** · electrohobby3d@gmail.com

## 📜 LIZENZ

GPL-3.0-or-later - siehe [LICENSE](LICENSE).
