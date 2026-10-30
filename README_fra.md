<p align="center">
  <img src="images/ARMOR_BANNER.svg" alt="Bannière d'ARMOR-SIMULATOR" width="100%">
</p>

# 🧪 ARMOR-SIMULATOR

<p align="center">
  <a href="README.md">🇺🇸 English</a> |
  <a href="README_spa.md">🇪🇸 Español</a> |
  🇫🇷 <b>Français</b> |
  <a href="README_ita.md">🇮🇹 Italiano</a> |
  <a href="README_deu.md">🇩🇪 Deutsch</a> |
  <a href="README_zho.md">🇨🇳 简体中文</a> |
  <a href="README_jpn.md">🇯🇵 日本語</a> |
  <a href="README_por.md">🇵🇹 Português</a>
</p>

### Simulateur de télémétrie hors ligne avec des pannes reproductibles

<p align="center">
  <img src="https://img.shields.io/badge/License-GPL%203.0--or--later-blue.svg" alt="GPL 3.0 ou ultérieure">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-3776ab.svg" alt="Langage">
  <img src="https://img.shields.io/badge/Dependencies-none-2ea44f.svg" alt="Dependencies">
  <img src="https://img.shields.io/badge/Tests-63%20passing-2ea44f.svg" alt="Tests">
  <img src="https://img.shields.io/badge/Version-0.2.7-0f6cbd.svg" alt="Version">
  <img src="https://img.shields.io/badge/Maturity-established-2EA44F.svg" alt="Maturité">
</p>

---

**Vérification d'honnêteté - ce qui fonctionne aujourd'hui :** Les scénarios, les pannes, la livraison à un serveur et les 63 tests sont réels, et le simulateur est ce qui alimente un serveur sur un ordinateur quand aucun nœud n'est branché. La géométrie est **illustrative**, pas un modèle du vrai radar LD2450, et rien de tout cela n'a été comparé à du matériel réel.

---

## 📋 En un coup d'œil

| | |
|---|---|
| Version | `0.2.7` |
| Maturité | Établi |
| Rôle | Simulateur hors ligne de télémétrie et d'environnement (famille : Testing, parent : ARMOR-COMMON) |
| Technologie | Python 3.11+, bibliothèque standard uniquement |
| Tests | 63 (`python -m unittest discover -s tests`) |
| Scénarios et pannes | 4 scénarios, 7 pannes (3 violent le contrat exprès) |
| Fonctionne sur | N'importe quel ordinateur, ou la CI |
| Sur matériel réel | Sans objet : c'est le substitut du matériel, utilisé sur un ordinateur |
| Licence | GPL-3.0-or-later |

**Aller à :** [Présentation](#-présentation) · [Architecture](#-architecture) · [Sécurité](#-sécurité-et-protection) · [Interfaces](#-interfaces) · [Configuration](#-configuration) · [Démarrage rapide](#-démarrage-rapide) · [Tests](#-tests) · [Dépannage](#-dépannage) · [Structure](#-structure-du-dépôt) · [Liés](#-projets-liés)

## 🚦 État du projet

Chaque ligne est une partie de ce dépôt et le feu dit où elle en est aujourd'hui. Elle est écrite d'après ce que le dépôt peut montrer (tests, compilations, exécutions), pas d'après ce qui est prévu.

🟢 Fait et vérifié · 🟡 Fonctionne, avec des limites connues · 🟠 À moitié fait ou pas encore vérifié · 🔴 Pas fait ou ne fonctionne pas

| Domaine | État | Ce que cela veut dire ici |
|---|---|---|
| Logiciel | 🟢 | Les scénarios, les pannes et la remise à un serveur fonctionnent ; c'est ce qui alimente un serveur sur un ordinateur quand aucun nœud n'est branché. |
| Tests | 🟢 | 63 tests réussissent (`python -m unittest discover -s tests`). |
| Protocoles et données | 🟠 | La géométrie est illustrative, pas un modèle du vrai radar LD2450, et rien n'a été comparé à du matériel réel. |
| Intégration | 🟢 | Il remet ses messages à un serveur dans les tests, et le serveur du banc d'essai CM5 peut être alimenté par lui. |
| Documentation | 🟢 | Huit langues et le journal des modifications sont à jour. |

## 🎯 Présentation

* **Scénarios :** `patrol`, `crossing`, `two-intruders` et `empty`, sur une géométrie de 270 degrés à trois capteurs, avec un cycle de lumière jour/nuit ou une nuit fixe.
* **Pannes reproductibles :** un nœud muet, des messages désordonnés ou dupliqués, un nœud instable et des messages volontairement invalides (lux hors limite, champ inconnu, trop de pistes) pour les tests négatifs.
* **Déterministe :** la même graine imprime toujours les mêmes lignes ; rien n'est envoyé sans `--server-url` et `--ingest-token`.
* **Vérifié contre le contrat :** `--validate` fait passer chaque message par ARMOR-COMMON avant de l'émettre.
* **Envoi prudent :** seule une origine http(s) simple est acceptée ; une erreur 4xx arrête l'exécution, une 5xx ou une erreur réseau est retentée.
* **Nœud électrique :** `--electrical` ajoute les trois canaux d'un nœud électrique (l'entrée du réseau, un chauffe-eau et un bus continu) sur une journée accélérée, avec une coupure du secteur, une période de tension élevée et une alarme de compteur.
* **Équipement solaire :** `--solar` ajoute un onduleur et une pile de batteries de deux modules (quinze cellules chacun, capacités comprises) sur une journée accélérée de 240 échantillons, avec une coupure du réseau en fin de journée ; les messages sont vérifiés contre le contrat solaire d'ARMOR-COMMON et envoyés à `/api/v1/solar`.

## 🧩 Rôle dans A.R.M.O.R.

ARMOR-SIMULATOR est la façon d'essayer le reste de la famille sans matériel : il joue le rôle d'un nœud radar, d'une passerelle solaire ou d'un nœud électrique et envoie leurs messages à un [ARMOR-SERVER](https://github.com/JuanenRac/ARMOR-SERVER), avec des pannes répétables, pour que [ARMOR-STUDIO](https://github.com/JuanenRac/ARMOR-STUDIO) et l'application mobile se voient fonctionner avec une maison qui n'existe pas. Chaque message qu'il fait est vérifié contre les contrats d'[ARMOR-COMMON](https://github.com/JuanenRac/ARMOR-COMMON).

| Nom | Comment | À quoi ça sert |
|---|---|---|
| ARMOR-SERVER | `POST /api/v1/telemetry`, `/health`, `/solar`, `/electrical/readings` | Reçoit les messages simulés |
| ARMOR-COMMON | `--validate` | Les contrats contre lesquels chaque message est vérifié |
| ARMOR-STUDIO, ARMOR-ANDROID-CONTROL | via le serveur | Affichent la maison simulée |

## 🏛️ Architecture

<p align="center">
  <img src="images/architecture.svg" alt="Architecture de ARMOR-SIMULATOR : qui l'appelle, ce qu'il contient et de quoi il dépend" width="100%">
</p>

## 🔒 Sécurité et protection

| Menace | Défense |
|---|---|
| Envoi vers une destination étrange | Seule une origine http(s) simple est acceptée (sans chemin ni identifiants) ; un 4xx arrête l'exécution, un 5xx ou une erreur réseau est retenté trois fois |
| Le jeton apparaît dans la liste des processus | `--ingest-token` est déconseillé ; utilisez `ARMOR_INGEST_TOKEN` ou `--ingest-token-file` ; rien n'écrit le jeton nulle part |
| Un test atteint un vrai serveur par erreur | Rien n'est envoyé sans `--server-url` et un jeton ; il n'y a aucun client de broker |
| Messages qui violent le contrat exprès | `corrupt-lux`, `unknown-field` et `oversized-targets` exigent `--allow-invalid` et ne se combinent pas avec `--validate` |
| Entrée hostile en ligne de commande | L'identifiant du nœud doit respecter `^[a-z0-9][a-z0-9_-]{0,63}$` et `--count` va de 1 à 10 000 |

C'est un outil de test : ce n'est pas une fonction de sécurité et sa géométrie n'est pas un modèle du vrai radar.

## 🔌 Interfaces

| Option | Par défaut | Ce qu'elle règle |
|---|---|---|
| `--scenario` | `patrol` | `patrol`, `crossing`, `two-intruders`, `empty` |
| `--count` | `1` | Échantillons (1 à 10 000) ; un échantillon = une seconde |
| `--seed` | `0` | La même graine imprime les mêmes lignes |
| `--light` | `cycle` | `cycle` (jour et nuit) ou `night` (0,3 lux fixe) |
| `--solar`, `--electrical` | off | Émet aussi un onduleur avec batteries / un nœud électrique |
| `--fault`, `--fault-every`, `--fault-topic` | `none`, `3`, `all` | Injecte une panne répétable dans certains messages |
| `--validate`, `--allow-invalid` | off | Vérifie chaque message avec ARMOR-COMMON / autorise les pannes qui le violent |
| `--server-url`, `--ingest-token-file`, `--per-node-token` | - | Livraison à ARMOR-SERVER ; le jeton de chaque nœud si le serveur est strict |

Toutes les options, scénarios et pannes sont dans [docs/USAGE.md](docs/USAGE.md). Messages : `armor/node/<id>/telemetry` et `health`, `armor/solar/<nœud>/<appareil>/state`, `armor/electrical/<nœud>/state` ; la livraison va vers `/api/v1/telemetry`, `/api/v1/health`, `/api/v1/solar` et `/api/v1/electrical/readings`.

## ⚙️ Configuration

| Variable | Requise | Ce qu'elle règle |
|---|---|---|
| `ARMOR_INGEST_TOKEN` | avec `--server-url` | Le jeton d'ingestion du serveur (ou une ligne `ARMOR_INGEST_TOKEN=...` dans le fichier de `--ingest-token-file`) |
| `PYTHONPATH=src` | depuis le dépôt | Où se trouve le paquet |

| Limite | Valeur |
|---|---|
| Échantillons par exécution | 1 - 10 000 |
| Capteurs et champ de vision | 3 (-75, 0, +75°) × ±60°, 6000 mm |
| Un jour de lumière, solaire et électrique | 240 échantillons |
| Tentatives de livraison / délai | 3 / 5 s |

## 🚀 Démarrage rapide

**Prérequis:** Python 3.11+ (bibliothèque standard uniquement).

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

| Fichier de tests | Tests | Ce qu'il couvre |
|---|---|---|
| `test_simulator.py` | 37 | Scénarios, pannes, solaire, électrique, validation, livraison à un serveur HTTP local |
| `test_cli_options.py` | 26 | Les options, leurs limites et les refus |

## 🏗️ Compilation et publication

C'est du Python pur : rien à compiler. La version est dans `pyproject.toml` et `armor.project.json`.

## 🩺 Dépannage

| Vous voyez | Parce que | Faites |
|---|---|---|
| `--server-url needs a token ...` | Une URL sans jeton, ou un jeton sans URL | Donnez les deux |
| HTTP 401 / 403 | Le jeton est faux ; un serveur strict veut un jeton par nœud | `--per-node-token` |
| `--allow-invalid` | La panne viole le contrat exprès | Ajoutez-le et n'utilisez pas `--validate` |
| Le serveur voit les messages comme anciens | La date de départ par défaut est 0 et le serveur la remplace | `--start-ms now` |

## 📂 Structure du dépôt

<p align="center">
  <img src="images/repository-structure.svg" alt="Structure du dépôt de ARMOR-SIMULATOR" width="100%">
</p>

<details>
<summary>Version texte de l'arborescence</summary>

```text
ARMOR-SIMULATOR/
├── src/armor_simulator/
│   ├── cli.py                           les options et l'exécution
│   ├── scenarios.py cycle.py            les quatre scénarios, la géométrie de 270 degrés et le jour de lumière
│   ├── solar.py                         un onduleur et une pile de deux modules
│   ├── electrical.py                    les trois canaux d'un nœud électrique
│   ├── faults.py                        les sept pannes répétables
│   └── publisher.py                     livraison à un serveur avec nouvelles tentatives
├── tests/                               les tests
├── docs/                                les guides de ce dépôt
├── tools/                               les contrôles CI partagés et les outils du projet
├── .github/                             workflow CI et modèles d'issues et de pull requests
├── images/                              bannière, icône et les deux images de ce README
├── build.sh build.bat                   build par le flux de projet partagé
├── test.sh test.bat                     lancer les tests par le flux partagé
├── run.sh run.bat                       démarrer par le flux de projet partagé
├── armor.project.json                   manifeste : version, rôle, maturité, commande de build
├── CHANGELOG.md                         ce qui a changé à chaque version
├── SECURITY.md SUPPORT.md LICENSE       politique de sécurité, support et licence
├── CONTRIBUTING.md CODE_OF_CONDUCT.md   comment contribuer et le code de conduite
├── build-test.sh build-test.bat         lancer les tests par le flux partagé
├── pyproject.toml                       métadonnées du paquet
└── .gitattributes .gitignore            réglages Git
```

</details>

## 🗺️ Feuille de route et limites connues

**Limites connues aujourd'hui**

* La géométrie est illustrative, pas un modèle du vrai radar LD2450, et rien n'a été comparé à du matériel réel.
* Il ne parle que HTTP à un serveur ; la publication vers un broker MQTT n'est volontairement pas incluse.

**Ensuite**

* Comparer les scénarios à des enregistrements du vrai radar une fois des nœuds installés.

## 🌍 Langues

Le README et les textes existent en anglais, espagnol, français, italien, allemand, chinois, japonais et portugais européen.

## 🔗 Projets liés

**A.R.M.O.R.** (Autonomous Radar & Multimodal Observation Range) est un système de sécurité périmétrique composé de dépôts indépendants. Chacun a sa propre version, ses propres tests et son propre README ; voici la famille :

* **[ARMOR-COMMON](https://github.com/JuanenRac/ARMOR-COMMON)** - Contrats de messages, validateurs, vecteurs de conformité et types générés
* **[ARMOR-NODE-RADAR](https://github.com/JuanenRac/ARMOR-NODE-RADAR)** - Firmware du nœud de terrain pour ESP32-S3 avec trois radars et son propre panneau web
* **[ARMOR-NODE-SOLAR](https://github.com/JuanenRac/ARMOR-NODE-SOLAR)** - Protocoles des onduleurs et batteries solaires et messages d'un nœud passerelle
* **[ARMOR-NODE-ELECTRICAL](https://github.com/JuanenRac/ARMOR-NODE-ELECTRICAL)** - Nœud électrique : compteurs, le message des mesures du réseau et les règles de commutation
* **[ARMOR-NODE-ALARM](https://github.com/JuanenRac/ARMOR-NODE-ALARM)** - Nœud et centrale d'alarme : zones, armement, temporisations, sirène et PIN, avec ou sans le serveur
* **[ARMOR-NODE-HMI](https://github.com/JuanenRac/ARMOR-NODE-HMI)** - Panneau tactile : l'état du système sur un écran mural, armer et acquitter, et la maison de l'assistant vocal
* **[ARMOR-NETWORK](https://github.com/JuanenRac/ARMOR-NETWORK)** - Le réseau local : ses appareils, internet et ce qui change
* **[ARMOR-SERVER](https://github.com/JuanenRac/ARMOR-SERVER)** - Coordinateur central : télémétrie, alarmes, appareils, relevés solaires et caméras
* **[ARMOR-STUDIO](https://github.com/JuanenRac/ARMOR-STUDIO)** - Console web : caméras, radar, alarmes, énergie solaire et concepteur de site 2D/3D
* **[ARMOR-ANDROID-CONTROL](https://github.com/JuanenRac/ARMOR-ANDROID-CONTROL)** - Client Android de l'opérateur avec radar 2D/3D en direct
* **[ARMOR-IOS-CONTROL](https://github.com/JuanenRac/ARMOR-IOS-CONTROL)** - Client opérateur iPhone
* **[ARMOR-SERVER-AI](https://github.com/JuanenRac/ARMOR-SERVER-AI)** - Politique d'inférence visuelle qui explique ses décisions et n'agit jamais
* **[ARMOR-VISION](https://github.com/JuanenRac/ARMOR-VISION)** - Zones de caméra, masques et règles de détection pour la Jetson Orin NX
* **[ARMOR-VOICE-AI](https://github.com/JuanenRac/ARMOR-VOICE-AI)** - Intentions vocales hors ligne avec une confirmation impossible à falsifier
* **[ARMOR-HARDWARE](https://github.com/JuanenRac/ARMOR-HARDWARE)** - Boîtiers, électronique et matrice d'acceptation sur banc
* **[ARMOR-DEVOPS](https://github.com/JuanenRac/ARMOR-DEVOPS)** - Déploiement, banc d'essai CM5, sauvegarde et TLS
* **ARMOR-SIMULATOR** (ce dépôt) - Simulateur de télémétrie hors ligne avec des pannes reproductibles
* **[ARMOR-UPDATER](https://github.com/JuanenRac/ARMOR-UPDATER)** - Détecte, installe et met à jour les propres dépôts de l'écosystème
* **[ARMOR-DOCS](https://github.com/JuanenRac/ARMOR-DOCS)** - Architecture, base de sécurité et matrice des capacités

## 📚 Documentation

* [Utilisation](docs/USAGE.md) : toutes les options, scénarios et pannes
* [Matrice des capacités : ce qui est prouvé et ce qui ne l'est pas](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/CAPABILITY_MATRIX.md)
* [Catalogue des projets : versions et dépendances entre les dépôts](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/PROJECT_CATALOG.md)
* [Historique des modifications de ce dépôt](CHANGELOG.md)

## 🤝 Contribuer et communauté

* Avant une pull request, lancez `python -m unittest discover -s tests` and `python -I tools/armor_ci_validate.py` : il doit réussir. Voir [CONTRIBUTING.md](CONTRIBUTING.md) et le [code de conduite](CODE_OF_CONDUCT.md).
* Le README existe en huit langues et est généré à partir des sources d'ARMOR-DOCS : une modification du texte se fait là-bas.
* Une modification d'un message entre composants commence dans ARMOR-COMMON.
* Ne décrivez pas comme fonctionnant sur une carte ce qui a seulement été compilé.
* Signalez une vulnérabilité en privé : [SECURITY.md](SECURITY.md). Questions, idées et rapports : electrohobby3d@gmail.com ([SUPPORT.md](SUPPORT.md)).

## 👤 AUTEUR

**JuanenRac (Electro Hobby 3D)** · electrohobby3d@gmail.com

## 📜 LICENCE

GPL-3.0-or-later - voir [LICENSE](LICENSE).
