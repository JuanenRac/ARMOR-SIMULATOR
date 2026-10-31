<p align="center">
  <img src="images/ARMOR_BANNER.svg" alt="Banner di ARMOR-SIMULATOR" width="100%">
</p>

# 🧪 ARMOR-SIMULATOR

<p align="center">
  <a href="README.md">🇺🇸 English</a> |
  <a href="README_spa.md">🇪🇸 Español</a> |
  <a href="README_fra.md">🇫🇷 Français</a> |
  🇮🇹 <b>Italiano</b> |
  <a href="README_deu.md">🇩🇪 Deutsch</a> |
  <a href="README_zho.md">🇨🇳 简体中文</a> |
  <a href="README_jpn.md">🇯🇵 日本語</a> |
  <a href="README_por.md">🇵🇹 Português</a>
</p>

### Simulatore di telemetria offline con guasti ripetibili

<p align="center">
  <img src="https://img.shields.io/badge/License-GPL%203.0--or--later-blue.svg" alt="GPL 3.0 o successiva">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-3776ab.svg" alt="Linguaggio">
  <img src="https://img.shields.io/badge/Dependencies-none-2ea44f.svg" alt="Dependencies">
  <img src="https://img.shields.io/badge/Tests-127%20passing-2ea44f.svg" alt="Test">
  <img src="https://img.shields.io/badge/Version-0.2.7-0f6cbd.svg" alt="Versione">
  <img src="https://img.shields.io/badge/Maturity-established-2EA44F.svg" alt="Maturità">
</p>

---

**Controllo di onestà - cosa funziona oggi:** Gli scenari, i guasti, la consegna a un server e i 127 test sono reali, e il simulatore è ciò che alimenta un server su un computer quando nessun nodo è collegato. La geometria è **illustrativa**, non un modello del vero radar LD2450, e nulla di tutto ciò è stato confrontato con hardware reale.

---

## 📋 In breve

| | |
|---|---|
| Versione | `0.2.7` |
| Maturità | Consolidato |
| Ruolo | Simulatore offline di telemetria e ambiente (famiglia: Testing, padre: ARMOR-COMMON) |
| Tecnologia | Python 3.11+, solo libreria standard |
| Test | 127 (`python -m unittest discover -s tests`) |
| Scenari e guasti | 4 scenari, 7 guasti (3 violano il contratto di proposito) |
| Gira su | Qualsiasi computer, o CI |
| Su hardware reale | Non applicabile: è il sostituto dell'hardware, usato su un computer |
| Licenza | GPL-3.0-or-later |

**Vai a:** [Panoramica](#-panoramica) · [Architettura](#-architettura) · [Sicurezza](#-sicurezza-e-protezione) · [Interfacce](#-interfacce) · [Configurazione](#-configurazione) · [Avvio rapido](#-avvio-rapido) · [Test](#-test) · [Problemi](#-risoluzione-dei-problemi) · [Struttura](#-struttura-del-repository) · [Correlati](#-progetti-correlati)

## 🚦 Stato del progetto

Ogni riga è una parte di questo repository e il semaforo dice a che punto è oggi. È scritta in base a ciò che il repository può mostrare (test, compilazioni, esecuzioni), non a ciò che è previsto.

🟢 Fatto e verificato · 🟡 Funziona, con limiti noti · 🟠 Fatto a metà o non ancora verificato · 🔴 Non fatto o non funzionante

| Area | Stato | Cosa significa qui |
|---|---|---|
| Software | 🟢 | Gli scenari, i guasti e la consegna a un server funzionano; è ciò che alimenta un server su un computer quando nessun nodo è collegato. |
| Test | 🟢 | Superano 127 test (`python -m unittest discover -s tests`). |
| Protocolli e dati | 🟠 | La geometria è illustrativa, non un modello del vero radar LD2450, e nulla è stato confrontato con hardware reale. |
| Integrazione | 🟢 | Consegna i suoi messaggi a un server nei test e il server del banco di prova CM5 può essere alimentato da esso. |
| Documentazione | 🟢 | Otto lingue e il registro delle modifiche sono aggiornati. |

## 🎯 Panoramica

* **Scenari:** `patrol`, `crossing`, `two-intruders` ed `empty`, su una geometria di 270 gradi a tre sensori, con un ciclo di luce giorno/notte o una notte fissa.
* **Guasti ripetibili:** un nodo muto, messaggi fuori ordine o duplicati, un nodo instabile e messaggi volutamente non validi (lux oltre il limite, campo sconosciuto, troppe tracce) per i test negativi.
* **Deterministico:** lo stesso seme stampa sempre le stesse righe; non viene inviato nulla senza `--server-url` e `--ingest-token`.
* **Verificato contro il contratto:** `--validate` fa passare ogni messaggio per ARMOR-COMMON prima di emetterlo.
* **Invio prudente:** si accetta solo un'origine http(s) semplice; un 4xx ferma l'esecuzione, un 5xx o un errore di rete viene ritentato.
* **Nodo elettrico:** `--electrical` aggiunge i tre canali di un nodo elettrico (l'ingresso di rete, uno scaldabagno e un bus in continua) su una giornata accelerata, con un'interruzione di rete, un periodo di tensione alta e un allarme di contatore.
* **Impianto solare:** `--solar` aggiunge un inverter e un pacco batterie da due moduli (quindici celle ciascuno, con le capacità) su un giorno accelerato di 240 campioni, con un'interruzione di rete a fine giornata; i messaggi sono verificati contro il contratto solare di ARMOR-COMMON e consegnati a `/api/v1/solar`.
* **Scenari d'allarme in file:** `--alarm-scenario` riproduce un file JSON con una cronologia (persone che attraversano più zone, un animale, il vento, un sensore bloccato, rumoroso, che deriva o morto, un nodo che perde il collegamento, un'interruzione di rete, la modalità e il calendario) e può dire cosa deve rispondere il sistema; `--verify-alarms` confronta gli allarmi sollevati da un server con quel file, che quindi serve da caso di prova per ARMOR-SERVER. La lettura è rigorosa: l'intero file viene rifiutato alla prima cosa non compresa.
* **Dati energetici realistici:** `--energy` emette un inverter, una pila di batterie e un nodo elettrico da un modello in tempo reale (un sole con nuvole, una casa ora per ora, una tariffa, una batteria tipo Pylontech con cicli, un contatore rumoroso con buchi), deterministico per un seed e regolabile da un file JSON. Senza le nuove opzioni l'output è esattamente quello di prima.

## 🧩 Ruolo in A.R.M.O.R.

ARMOR-SIMULATOR è il modo per provare il resto della famiglia senza hardware: fa la parte di un nodo radar, di un gateway solare o di un nodo elettrico e invia i loro messaggi a un [ARMOR-SERVER](https://github.com/JuanenRac/ARMOR-SERVER), con guasti ripetibili, così [ARMOR-STUDIO](https://github.com/JuanenRac/ARMOR-STUDIO) e l'app mobile si vedono funzionare con una casa che non esiste. Ogni messaggio che produce è controllato contro i contratti di [ARMOR-COMMON](https://github.com/JuanenRac/ARMOR-COMMON).

| Nome | Come | A cosa serve |
|---|---|---|
| ARMOR-SERVER | `POST /api/v1/telemetry`, `/health`, `/solar`, `/electrical/readings` | Riceve i messaggi simulati |
| ARMOR-COMMON | `--validate` | I contratti con cui si verifica ogni messaggio |
| ARMOR-STUDIO, ARMOR-ANDROID-CONTROL | tramite il server | Mostrano la casa simulata |

## 🏛️ Architettura

<p align="center">
  <img src="images/architecture.svg" alt="Architettura di ARMOR-SIMULATOR: chi lo chiama, cosa contiene e da cosa dipende" width="100%">
</p>

## 🔒 Sicurezza e protezione

| Minaccia | Difesa |
|---|---|
| Invio a una destinazione strana | Si accetta solo un'origine http(s) semplice (senza percorso né credenziali); un 4xx ferma l'esecuzione, un 5xx o un errore di rete viene ritentato tre volte |
| Il token compare nell'elenco dei processi | `--ingest-token` è sconsigliato; usa `ARMOR_INGEST_TOKEN` o `--ingest-token-file`; nulla scrive il token da nessuna parte |
| Un test raggiunge per errore un server reale | Non si invia nulla senza `--server-url` e un token; non c'è alcun client di broker |
| Messaggi che violano il contratto di proposito | `corrupt-lux`, `unknown-field` e `oversized-targets` richiedono `--allow-invalid` e non si combinano con `--validate` |
| Input ostile sulla riga di comando | L'id del nodo deve rispettare `^[a-z0-9][a-z0-9_-]{0,63}$` e `--count` va da 1 a 10 000 |

È uno strumento di prova: non è una funzione di sicurezza e la sua geometria non è un modello del radar reale.

## 🔌 Interfacce

| Opzione | Predefinito | Cosa imposta |
|---|---|---|
| `--scenario` | `patrol` | `patrol`, `crossing`, `two-intruders`, `empty` |
| `--count` | `1` | Campioni (da 1 a 10 000); un campione è un secondo |
| `--seed` | `0` | Lo stesso seed stampa le stesse righe |
| `--light` | `cycle` | `cycle` (giorno e notte) o `night` (0,3 lux fissi) |
| `--solar`, `--electrical` | off | Emette anche un inverter con batterie / un nodo elettrico |
| `--alarm-scenario`, `--check-alarm-scenario`, `--verify-alarms` | - | Riprodurre uno scenario d'allarme da un file JSON / solo validarlo / confrontare gli allarmi sollevati da un server con quanto atteso (codice 1 se differiscono) |
| `--energy`, `--energy-config`, `--energy-days`, `--energy-step-s` | no, -, `1`, `900` | Dati solari ed elettrici realistici in tempo reale invece del giorno rapido di `--solar`/`--electrical` |
| `--fault`, `--fault-every`, `--fault-topic` | `none`, `3`, `all` | Inietta un guasto ripetibile in alcuni messaggi |
| `--validate`, `--allow-invalid` | off | Verifica ogni messaggio con ARMOR-COMMON / consente i guasti che lo violano |
| `--server-url`, `--ingest-token-file`, `--per-node-token` | - | Consegna a ARMOR-SERVER; il token di ogni nodo se il server è rigoroso |

Tutte le opzioni, gli scenari e i guasti sono in [docs/USAGE.md](docs/USAGE.md). Messaggi: `armor/node/<id>/telemetry` e `health`, `armor/solar/<nodo>/<dispositivo>/state`, `armor/electrical/<nodo>/state`; la consegna va a `/api/v1/telemetry`, `/api/v1/health`, `/api/v1/solar` e `/api/v1/electrical/readings`.

## ⚙️ Configurazione

| Variabile | Necessaria | Cosa imposta |
|---|---|---|
| `ARMOR_INGEST_TOKEN` | con `--server-url` | Il token di ingestione del server (o una riga `ARMOR_INGEST_TOKEN=...` nel file di `--ingest-token-file`) |
| `PYTHONPATH=src` | dal repository | Dove si trova il pacchetto |

| Limite | Valore |
|---|---|
| Campioni per esecuzione | 1 - 10 000 |
| Sensori e campo visivo | 3 (-75, 0, +75°) × ±60°, 6000 mm |
| Un giorno di luce, solare ed elettrico | 240 campioni |
| Tentativi di consegna / timeout | 3 / 5 s |

## 🚀 Avvio rapido

**Requisiti:** Python 3.11+ (solo libreria standard).

```powershell
$env:PYTHONPATH = "src"
python -m armor_simulator --count 20 --scenario crossing --seed 1 --validate
python -m armor_simulator --count 60 --scenario two-intruders --server-url http://127.0.0.1:8080 --ingest-token-file token.env
```

## 🧪 Test

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
python -I tools/armor_ci_validate.py
```

| File di test | Test | Cosa copre |
|---|---|---|
| `test_simulator.py` | 37 | Scenari, guasti, solare, elettrico, validazione, consegna a un server HTTP locale |
| `test_cli_options.py` | 26 | Le opzioni, i loro limiti e i rifiuti |
| `test_alarm_scenarios.py` | 32 | File di scenari d'allarme: lettura rigorosa, il flusso, modalità e calendario, verifica della risposta, le opzioni |
| `test_energy.py` | 32 | Modello energetico: proprietà fisiche con molti seed, tariffa, contatore, impostazioni, contratti, le opzioni |

## 🏗️ Compilazione e rilascio

È Python puro: nulla da compilare. La versione sta in `pyproject.toml` e `armor.project.json`.

## 🩺 Risoluzione dei problemi

| Vedi | Perché | Fai |
|---|---|---|
| `--server-url needs a token ...` | Un URL senza token, o un token senza URL | Dai entrambi |
| HTTP 401 / 403 | Il token è errato; un server rigoroso vuole un token per nodo | `--per-node-token` |
| `--allow-invalid` | Il guasto viola il contratto di proposito | Aggiungilo e non usare `--validate` |
| Il server vede i messaggi come vecchi | La data di inizio predefinita è 0 e il server la sostituisce | `--start-ms now` |

## 📂 Struttura del repository

<p align="center">
  <img src="images/repository-structure.svg" alt="Struttura del repository di ARMOR-SIMULATOR" width="100%">
</p>

<details>
<summary>Versione testuale dell'albero</summary>

```text
ARMOR-SIMULATOR/
├── src/armor_simulator/
│   ├── cli.py                           le opzioni e l'esecuzione
│   ├── scenarios.py cycle.py            i quattro scenari, la geometria a 270 gradi e il giorno di luce
│   ├── alarm_scenarios.py               scenari d'allarme da file JSON, i loro messaggi e la verifica della risposta
│   ├── solar.py                         un inverter e una pila di due moduli
│   ├── electrical.py                    i tre canali di un nodo elettrico
│   ├── energy.py                        dati solari ed elettrici realistici: sole con nuvole, casa, tariffa, batteria, contatore
│   ├── faults.py                        i sette guasti ripetibili
│   └── publisher.py                     consegna a un server con nuovi tentativi
├── tests/                               i test
├── docs/                                le guide di questo repository
├── tools/                               i controlli CI condivisi e gli strumenti del progetto
├── .github/                             workflow CI e modelli per issue e pull request
├── examples/                            scenari d'allarme e impostazioni del modello energetico da cui partire
├── images/                              banner, icona e le due immagini di questo README
├── build.sh build.bat                   build tramite il flusso di progetto condiviso
├── test.sh test.bat                     eseguire i test tramite il flusso condiviso
├── run.sh run.bat                       avvio tramite il flusso di progetto condiviso
├── armor.project.json                   manifesto: versione, ruolo, maturità, comando di build
├── CHANGELOG.md                         cosa è cambiato in ogni versione
├── SECURITY.md SUPPORT.md LICENSE       politica di sicurezza, supporto e licenza
├── CONTRIBUTING.md CODE_OF_CONDUCT.md   come contribuire e il codice di condotta
├── build-test.sh build-test.bat         eseguire i test tramite il flusso condiviso
├── pyproject.toml                       metadati del pacchetto
└── .gitattributes .gitignore            impostazioni di Git
```

</details>

## 🗺️ Roadmap e limiti noti

**Limiti noti oggi**

* La geometria è illustrativa, non un modello del radar LD2450 reale, e nulla è stato confrontato con hardware reale.
* Parla solo HTTP con un server; la pubblicazione su un broker MQTT non è inclusa di proposito.

**Prossimi passi**

* Confrontare gli scenari con registrazioni del radar reale quando i nodi saranno installati.

## 🌍 Lingue

Il README e i testi esistono in inglese, spagnolo, francese, italiano, tedesco, cinese, giapponese e portoghese europeo.

## 🔗 Progetti correlati

**A.R.M.O.R.** (Autonomous Radar & Multimodal Observation Range) è un sistema di sicurezza perimetrale fatto di repository indipendenti. Ognuno ha la propria versione, i propri test e il proprio README; ecco la famiglia:

* **[ARMOR-COMMON](https://github.com/JuanenRac/ARMOR-COMMON)** - Contratti dei messaggi, validatori, vettori di conformità e tipi generati
* **[ARMOR-NODE-RADAR](https://github.com/JuanenRac/ARMOR-NODE-RADAR)** - Firmware del nodo di campo per ESP32-S3 con tre radar e un proprio pannello web
* **[ARMOR-NODE-SOLAR](https://github.com/JuanenRac/ARMOR-NODE-SOLAR)** - Protocolli di inverter e batterie solari e messaggi di un nodo gateway
* **[ARMOR-NODE-ELECTRICAL](https://github.com/JuanenRac/ARMOR-NODE-ELECTRICAL)** - Nodo elettrico: contatori, il messaggio delle letture della rete e le regole di manovra
* **[ARMOR-NODE-ALARM](https://github.com/JuanenRac/ARMOR-NODE-ALARM)** - Nodo e centrale d'allarme: zone, inserimento, ritardi, sirena e PIN, con il server o senza
* **[ARMOR-NODE-HMI](https://github.com/JuanenRac/ARMOR-NODE-HMI)** - Pannello touch: lo stato del sistema su uno schermo a parete, attivare e riconoscere gli allarmi, e la casa dell'assistente vocale
* **[ARMOR-NETWORK](https://github.com/JuanenRac/ARMOR-NETWORK)** - La rete locale: i suoi dispositivi, internet e ciò che cambia
* **[ARMOR-SERVER](https://github.com/JuanenRac/ARMOR-SERVER)** - Coordinatore centrale: telemetria, allarmi, dispositivi, letture solari e telecamere
* **[ARMOR-STUDIO](https://github.com/JuanenRac/ARMOR-STUDIO)** - Console web: telecamere, radar, allarmi, energia solare e progettista del sito 2D/3D
* **[ARMOR-ANDROID-CONTROL](https://github.com/JuanenRac/ARMOR-ANDROID-CONTROL)** - Client Android dell'operatore con radar 2D/3D in tempo reale
* **[ARMOR-IOS-CONTROL](https://github.com/JuanenRac/ARMOR-IOS-CONTROL)** - Client operatore per iPhone
* **[ARMOR-SERVER-AI](https://github.com/JuanenRac/ARMOR-SERVER-AI)** - Politica di inferenza visiva che spiega le sue decisioni e non agisce mai
* **[ARMOR-VISION](https://github.com/JuanenRac/ARMOR-VISION)** - Zone delle telecamere, maschere e regole di rilevamento per la Jetson Orin NX
* **[ARMOR-VOICE-AI](https://github.com/JuanenRac/ARMOR-VOICE-AI)** - Intenti vocali offline con una conferma impossibile da falsificare
* **[ARMOR-HARDWARE](https://github.com/JuanenRac/ARMOR-HARDWARE)** - Contenitori, elettronica e matrice di accettazione da banco
* **[ARMOR-DEVOPS](https://github.com/JuanenRac/ARMOR-DEVOPS)** - Distribuzione, banco di prova CM5, backup e TLS
* **ARMOR-SIMULATOR** (questo repository) - Simulatore di telemetria offline con guasti ripetibili
* **[ARMOR-UPDATER](https://github.com/JuanenRac/ARMOR-UPDATER)** - Rileva, installa e aggiorna i repository stessi dell'ecosistema
* **[ARMOR-DOCS](https://github.com/JuanenRac/ARMOR-DOCS)** - Architettura, base di sicurezza e matrice delle capacità

## 📚 Documentazione

* [Uso](docs/USAGE.md): tutte le opzioni, gli scenari e i guasti
* [Scenari d'allarme](docs/ALARM_SCENARIOS.md): il formato del file e come verificare la risposta di un server
* [Modello energetico](docs/ENERGY_MODEL.md): i dati solari ed elettrici realistici e le loro impostazioni
* [Matrice delle capacità: cosa è provato e cosa no](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/CAPABILITY_MATRIX.md)
* [Catalogo dei progetti: versioni e dipendenze tra i repository](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/PROJECT_CATALOG.md)
* [Cronologia delle modifiche di questo repository](CHANGELOG.md)

## 🤝 Contribuire e comunità

* Prima di una pull request esegui `python -m unittest discover -s tests` and `python -I tools/armor_ci_validate.py`: deve passare. Vedi [CONTRIBUTING.md](CONTRIBUTING.md) e il [codice di condotta](CODE_OF_CONDUCT.md).
* Il README esiste in otto lingue ed è generato dalle sorgenti in ARMOR-DOCS: una modifica al testo si fa lì.
* Una modifica a un messaggio tra componenti parte da ARMOR-COMMON.
* Non descrivere come funzionante su una scheda ciò che è stato solo compilato.
* Segnala una vulnerabilità in privato: [SECURITY.md](SECURITY.md). Domande, idee e segnalazioni: electrohobby3d@gmail.com ([SUPPORT.md](SUPPORT.md)).

## 👤 AUTORE

**JuanenRac (Electro Hobby 3D)** · electrohobby3d@gmail.com

## 📜 LICENZA

GPL-3.0-or-later - vedi [LICENSE](LICENSE).
