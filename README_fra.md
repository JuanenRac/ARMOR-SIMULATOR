<p align="center">
  <img src="images/ARMOR_BANNER.svg" alt="ARMOR-SIMULATOR banner" width="100%">
</p>

# 🧪 ARMOR-SIMULATOR

<p align="center">
  <a href="README.md">🇺🇸 English</a> |
  <a href="README_spa.md">🇪🇸 Español</a> |
  🇫🇷 <b>Français</b> |
  <a href="README_ita.md">🇮🇹 Italiano</a> |
  <a href="README_deu.md">🇩🇪 Deutsch</a> |
  <a href="README_zho.md">🇨🇳 简体中文</a> |
  <a href="README_jpn.md">🇯🇵 日本語</a>
</p>

### Simulateur de télémétrie hors ligne avec des pannes reproductibles

<p align="center">
  <img src="https://img.shields.io/badge/License-GPL%203.0-blue.svg" alt="GPL 3.0">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-3776ab.svg" alt="Language">
  <img src="https://img.shields.io/badge/Dependencies-none-2ea44f.svg" alt="Dependencies">
  <img src="https://img.shields.io/badge/Maturity-functional-00E5FF.svg" alt="Maturity">
</p>

---

**Vérification d'honnêteté - ce qui fonctionne aujourd'hui:** Les scénarios, les pannes, l'envoi vers un serveur et les 28 tests sont réels. La géométrie est **illustrative**, pas un modèle du vrai radar LD2450, et rien n'a été comparé à du matériel réel.

---

## 🎯 Présentation

* **Scénarios :** `patrol`, `crossing`, `two-intruders` et `empty`, sur une géométrie d'angle à trois capteurs, avec un cycle de lumière jour/nuit ou une nuit fixe.
* **Pannes reproductibles :** un nœud muet, des messages désordonnés ou dupliqués, un nœud instable et des messages volontairement invalides (lux hors limite, champ inconnu, trop de pistes) pour les tests négatifs.
* **Déterministe :** la même graine imprime toujours les mêmes lignes ; rien n'est envoyé sans `--server-url` et `--ingest-token`.
* **Vérifié contre le contrat :** `--validate` fait passer chaque message par ARMOR-COMMON avant de l'émettre.
* **Envoi prudent :** seule une origine http(s) simple est acceptée ; une erreur 4xx arrête l'exécution, une 5xx ou une erreur réseau est retentée.
* **Nœud électrique :** `--electrical` ajoute les trois canaux d'un nœud électrique (l'entrée du réseau, un chauffe-eau et un bus continu) sur une journée accélérée, avec une coupure du secteur, une période de tension élevée et une alarme de compteur.
* **Équipement solaire :** `--solar` ajoute un onduleur et une pile de batteries de deux modules (quinze cellules chacun, capacités comprises) sur une journée accélérée de 240 échantillons, avec une coupure du réseau en fin de journée ; les messages sont vérifiés contre le contrat solaire d'ARMOR-COMMON et envoyés à `/api/v1/solar`.

## 📂 Structure du dépôt

```text
ARMOR-SIMULATOR/
├── src/armor_simulator/   scenarios, faults, solar (inverter and battery messages), electrical (an electrical node), publisher, cli
├── tests/                 28 tests, including a local HTTP server
└── docs/USAGE.md
```

## 🛠️ Environnement de développement

```powershell
$env:PYTHONPATH="src"
python -m armor_simulator --count 20 --scenario crossing --seed 1 --validate
python -m unittest discover -s tests   # 28 tests
```

Toutes les options, scénarios et pannes : [utilisation](docs/USAGE.md).

## 🔗 Projets liés

**A.R.M.O.R.** (Autonomous Radar & Multimodal Observation Range) est un système de sécurité périmétrique composé de dépôts indépendants. Chacun a sa propre version, ses propres tests et son propre README ; voici la famille :

* **[ARMOR-COMMON](https://github.com/JuanenRac/ARMOR-COMMON)** - Contrats de messages, validateurs, vecteurs de conformité et types générés
* **[ARMOR-RADAR](https://github.com/JuanenRac/ARMOR-RADAR)** - Firmware du nœud de terrain pour ESP32-S3 avec trois radars et son propre panneau web
* **[ARMOR-SOLAR](https://github.com/JuanenRac/ARMOR-SOLAR)** - Protocoles des onduleurs et batteries solaires et messages d'un nœud passerelle
* **[ARMOR-ELECTRICAL](https://github.com/JuanenRac/ARMOR-ELECTRICAL)** - Nœud électrique : compteurs, le message des mesures du réseau et les règles de commutation
* **[ARMOR-HMI](https://github.com/JuanenRac/ARMOR-HMI)** - Panneau tactile : l'état du système sur un écran mural, armer et acquitter, et la maison de l'assistant vocal
* **[ARMOR-NETWORK](https://github.com/JuanenRac/ARMOR-NETWORK)** - Le réseau local : ses appareils, internet et ce qui change
* **[ARMOR-SERVER](https://github.com/JuanenRac/ARMOR-SERVER)** - Coordinateur central : télémétrie, alarmes, appareils, relevés solaires et caméras
* **[ARMOR-STUDIO](https://github.com/JuanenRac/ARMOR-STUDIO)** - Console web : caméras, radar, alarmes, énergie solaire et concepteur de site 2D/3D
* **[ARMOR-ANDROID-CONTROL](https://github.com/JuanenRac/ARMOR-ANDROID-CONTROL)** - Client Android de l'opérateur avec radar 2D/3D en direct
* **[ARMOR-SERVER-AI](https://github.com/JuanenRac/ARMOR-SERVER-AI)** - Politique d'inférence visuelle qui explique ses décisions et n'agit jamais
* **[ARMOR-VOICE-AI](https://github.com/JuanenRac/ARMOR-VOICE-AI)** - Intentions vocales hors ligne avec une confirmation impossible à falsifier
* **[ARMOR-HARDWARE](https://github.com/JuanenRac/ARMOR-HARDWARE)** - Boîtiers, électronique et matrice d'acceptation sur banc
* **[ARMOR-DEVOPS](https://github.com/JuanenRac/ARMOR-DEVOPS)** - Déploiement, banc d'essai CM5, sauvegarde et TLS
* **ARMOR-SIMULATOR** (ce dépôt) - Simulateur de télémétrie hors ligne avec des pannes reproductibles
* **[ARMOR-UPDATER](https://github.com/JuanenRac/ARMOR-UPDATER)** - Détecte, installe et met à jour les propres dépôts de l'écosystème
* **[ARMOR-DOCS](https://github.com/JuanenRac/ARMOR-DOCS)** - Architecture, base de sécurité et matrice des capacités

## 📚 Documentation et communauté

Pour en savoir plus :

* [Matrice des capacités : ce qui est prouvé et ce qui ne l'est pas](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/CAPABILITY_MATRIX.md)
* [Catalogue des projets : versions et dépendances entre les dépôts](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/PROJECT_CATALOG.md)
* [Historique des modifications de ce dépôt](CHANGELOG.md)
* [Licence (GPL-3.0-or-later)](LICENSE)
* Questions, idées et rapports : electrohobby3d@gmail.com

## 👤 AUTEUR

**JuanenRac (Electro Hobby 3D)** · electrohobby3d@gmail.com

## 📜 LICENCE

GPL-3.0-or-later - voir [LICENSE](LICENSE).
