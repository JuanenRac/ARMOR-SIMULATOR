<p align="center">
  <img src="images/ARMOR_BANNER.svg" alt="ARMOR-SIMULATOR banner" width="100%">
</p>

# 🧪 ARMOR-SIMULATOR

<p align="center">
  <a href="README.md">🇺🇸 English</a> |
  <a href="README_spa.md">🇪🇸 Español</a> |
  <a href="README_fra.md">🇫🇷 Français</a> |
  <a href="README_ita.md">🇮🇹 Italiano</a> |
  <a href="README_deu.md">🇩🇪 Deutsch</a> |
  <a href="README_zho.md">🇨🇳 简体中文</a> |
  <a href="README_jpn.md">🇯🇵 日本語</a> |
  🇵🇹 <b>Português</b>
</p>

### Simulador de telemetria offline com falhas repetíveis

<p align="center">
  <img src="https://img.shields.io/badge/License-GPL%203.0--or--later-blue.svg" alt="GPL 3.0 or later">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-3776ab.svg" alt="Language">
  <img src="https://img.shields.io/badge/Dependencies-none-2ea44f.svg" alt="Dependencies">
  <img src="https://img.shields.io/badge/Tests-127%20passing-2ea44f.svg" alt="Tests">
  <img src="https://img.shields.io/badge/Version-0.2.7-0f6cbd.svg" alt="Version">
  <img src="https://img.shields.io/badge/Maturity-established-2EA44F.svg" alt="Maturity">
</p>

---

**Verificação de honestidade - o que funciona hoje:** Os cenários, as falhas, a entrega a um servidor e os 127 testes são reais, e o simulador é o que alimenta um servidor num computador quando nenhum nó está ligado. A geometria é **ilustrativa**, não um modelo do radar LD2450 real, e nada disto foi comparado com hardware real.

---

## 📋 Num relance

| | |
|---|---|
| Versão | `0.2.7` |
| Maturidade | Estabelecido |
| Função | Simulador offline de telemetria e ambiente (família: Testing, pai: ARMOR-COMMON) |
| Tecnologia | Python 3.11+, só biblioteca padrão |
| Testes | 127 (`python -m unittest discover -s tests`) |
| Cenários e falhas | 4 cenários, 7 falhas (3 violam o contrato de propósito) |
| Funciona em | Qualquer computador, ou CI |
| Em hardware real | Não se aplica: é o substituto do hardware, usado num computador |
| Licença | GPL-3.0-or-later |

**Ir para:** [Visão geral](#-visão-geral) · [Arquitetura](#-arquitetura) · [Segurança](#-segurança-e-proteção) · [Interfaces](#-interfaces) · [Configuração](#-configuração) · [Início rápido](#-início-rápido) · [Testes](#-testes) · [Problemas](#-resolução-de-problemas) · [Estrutura](#-estrutura-do-repositório) · [Relacionados](#-projetos-relacionados)

## 🚦 Estado do projeto

Cada linha é uma parte deste repositório e a luz diz até onde chega hoje. É escrita com o que o repositório consegue demonstrar (testes, compilações, execuções), não com o que está previsto.

🟢 Feito e verificado · 🟡 Funciona, com limites conhecidos · 🟠 Feito a meio ou ainda por verificar · 🔴 Por fazer ou a não funcionar

| Área | Estado | O que significa aqui |
|---|---|---|
| Software | 🟢 | Os cenários, as avarias e a entrega a um servidor funcionam; é o que alimenta um servidor num computador quando nenhum nó está ligado. |
| Testes | 🟢 | Passam 127 testes (`python -m unittest discover -s tests`). |
| Protocolos e dados | 🟠 | A geometria é ilustrativa, não um modelo do radar LD2450 real, e nada foi comparado com hardware real. |
| Integração | 🟢 | Entrega as suas mensagens a um servidor nos testes, e o servidor da bancada de testes CM5 pode ser alimentado por ele. |
| Documentação | 🟢 | Oito idiomas e o registo de alterações estão atualizados. |

## 🎯 Visão geral

* **Cenários:** `patrol`, `crossing`, `two-intruders` e `empty`, numa geometria de 270 graus com três sensores, mais um ciclo de luz dia/noite ou uma noite fixa.
* **Falhas repetíveis:** um nó silencioso, mensagens fora de ordem e duplicadas, um nó que oscila, e mensagens deliberadamente inválidas (lux acima do limite, campo desconhecido, demasiados rastos) para testes negativos.
* **Determinista:** a mesma semente imprime sempre as mesmas linhas; nada se envia a menos que indique `--server-url` e `--ingest-token`.
* **Verificado contra o contrato:** `--validate` passa cada mensagem pelo ARMOR-COMMON antes de a emitir.
* **Envio cuidadoso:** só se aceita uma origem http(s) simples; um 4xx pára a execução, um 5xx ou um erro de rede repete-se.
* **Nó elétrico:** `--electrical` acrescenta os três canais de um nó elétrico (a entrada da rede, um esquentador e um barramento DC) ao longo de um dia rápido, com um corte de energia, um período de tensão alta e um alarme do contador.
* **Equipamento solar:** `--solar` acrescenta um inversor e um conjunto de baterias de dois módulos (quinze células cada, capacidades incluídas) ao longo de um dia rápido de 240 amostras, com um corte de energia ao fim do dia; as mensagens verificam-se contra o contrato solar do ARMOR-COMMON e entregam-se em `/api/v1/solar`.
* **Cenários de alarme em ficheiros:** `--alarm-scenario` reproduz um ficheiro JSON com uma linha de tempo (pessoas que atravessam várias zonas, um animal de estimação, vento, um sensor preso, ruidoso, com deriva ou morto, um nó que perde a ligação, um corte de rede, o modo e o calendário) e pode dizer o que o sistema deve responder; `--verify-alarms` compara os alarmes que um servidor levantou com isso, pelo que os ficheiros são casos de teste para o ARMOR-SERVER. A leitura é estrita: o ficheiro inteiro é recusado à primeira coisa que não se entenda.
* **Dados de energia realistas:** `--energy` emite um inversor, uma pilha de baterias e um nó elétrico a partir de um modelo em tempo real (um sol com nuvens, uma casa hora a hora, uma tarifa, uma bateria do tipo Pylontech com ciclos, um contador com ruído e falhas), determinista para uma semente e ajustável a partir de um ficheiro JSON. Sem as novas opções, a saída é exatamente a de antes.

## 🧩 Papel no A.R.M.O.R.

O ARMOR-SIMULATOR é a forma de experimentar o resto da família sem hardware: faz de nó radar, de porta de ligação solar ou de nó elétrico e envia as suas mensagens para um [ARMOR-SERVER](https://github.com/JuanenRac/ARMOR-SERVER), com falhas repetíveis, para que o [ARMOR-STUDIO](https://github.com/JuanenRac/ARMOR-STUDIO) e a aplicação móvel se vejam a funcionar com uma casa que não existe. Cada mensagem que faz é verificada contra os contratos do [ARMOR-COMMON](https://github.com/JuanenRac/ARMOR-COMMON).

| Nome | Como | Para quê |
|---|---|---|
| ARMOR-SERVER | `POST /api/v1/telemetry`, `/health`, `/solar`, `/electrical/readings` | Recebe as mensagens simuladas |
| ARMOR-COMMON | `--validate` | Os contratos contra os quais cada mensagem é verificada |
| ARMOR-STUDIO, ARMOR-ANDROID-CONTROL | através do servidor | Mostram a casa simulada |

## 🏛️ Arquitetura

<p align="center">
  <img src="images/architecture.svg" alt="Arquitetura de ARMOR-SIMULATOR: quem o chama, o que contém e de que depende" width="100%">
</p>

## 🔒 Segurança e proteção

| Ameaça | Defesa |
|---|---|
| Enviar para um destino estranho | Só se aceita uma origem http(s) simples (sem caminho nem credenciais); um 4xx pára a execução, um 5xx ou um erro de rede é repetido três vezes |
| O token aparece na lista de processos | `--ingest-token` é desaconselhado; use `ARMOR_INGEST_TOKEN` ou `--ingest-token-file`; nada escreve o token em lado nenhum |
| Um teste chega por engano a um servidor real | Nada é enviado sem `--server-url` e um token; não há nenhum cliente de broker |
| Mensagens que violam o contrato de propósito | `corrupt-lux`, `unknown-field` e `oversized-targets` exigem `--allow-invalid` e não se combinam com `--validate` |
| Entrada hostil na linha de comandos | O id do nó tem de cumprir `^[a-z0-9][a-z0-9_-]{0,63}$` e `--count` vai de 1 a 10 000 |

É uma ferramenta de teste: não é uma função de segurança e a sua geometria não é um modelo do radar real.

## 🔌 Interfaces

| Opção | Predefinição | O que define |
|---|---|---|
| `--scenario` | `patrol` | `patrol`, `crossing`, `two-intruders`, `empty` |
| `--count` | `1` | Amostras (1 a 10 000); uma amostra é um segundo |
| `--seed` | `0` | A mesma semente imprime as mesmas linhas |
| `--light` | `cycle` | `cycle` (dia e noite) ou `night` (0,3 lux fixos) |
| `--solar`, `--electrical` | off | Emite também um inversor com baterias / um nó elétrico |
| `--alarm-scenario`, `--check-alarm-scenario`, `--verify-alarms` | - | Reproduzir um cenário de alarme a partir de um ficheiro JSON / só o validar / comparar os alarmes que um servidor levantou com o esperado (sai com 1 se diferirem) |
| `--energy`, `--energy-config`, `--energy-days`, `--energy-step-s` | não, -, `1`, `900` | Dados solares e elétricos realistas em tempo real em vez do dia rápido de `--solar`/`--electrical` |
| `--fault`, `--fault-every`, `--fault-topic` | `none`, `3`, `all` | Injeta uma falha repetível em algumas mensagens |
| `--validate`, `--allow-invalid` | off | Verifica cada mensagem com o ARMOR-COMMON / permite as falhas que o violam |
| `--server-url`, `--ingest-token-file`, `--per-node-token` | - | Entrega ao ARMOR-SERVER; o token de cada nó se o servidor for estrito |

Todas as opções, cenários e falhas estão em [docs/USAGE.md](docs/USAGE.md). Mensagens: `armor/node/<id>/telemetry` e `health`, `armor/solar/<nó>/<dispositivo>/state`, `armor/electrical/<nó>/state`; a entrega vai para `/api/v1/telemetry`, `/api/v1/health`, `/api/v1/solar` e `/api/v1/electrical/readings`.

## ⚙️ Configuração

| Variável | Necessária | O que define |
|---|---|---|
| `ARMOR_INGEST_TOKEN` | com `--server-url` | O token de ingestão do servidor (ou uma linha `ARMOR_INGEST_TOKEN=...` no ficheiro de `--ingest-token-file`) |
| `PYTHONPATH=src` | a partir do repositório | Onde o pacote é encontrado |

| Limite | Valor |
|---|---|
| Amostras por execução | 1 - 10 000 |
| Sensores e campo de visão | 3 (-75, 0, +75°) × ±60°, 6000 mm |
| Um dia de luz, solar e elétrico | 240 amostras |
| Tentativas de entrega / limite de tempo | 3 / 5 s |

## 🚀 Início rápido

**Requisitos:** Python 3.11+ (só biblioteca padrão).

```powershell
$env:PYTHONPATH = "src"
python -m armor_simulator --count 20 --scenario crossing --seed 1 --validate
python -m armor_simulator --count 60 --scenario two-intruders --server-url http://127.0.0.1:8080 --ingest-token-file token.env
```

## 🧪 Testes

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
python -I tools/armor_ci_validate.py
```

| Ficheiro de testes | Testes | O que cobre |
|---|---|---|
| `test_simulator.py` | 37 | Cenários, falhas, solar, elétrico, validação, entrega a um servidor HTTP local |
| `test_cli_options.py` | 26 | As opções, os seus limites e as recusas |
| `test_alarm_scenarios.py` | 32 | Ficheiros de cenários de alarme: leitura estrita, o fluxo, modos e calendário, verificação da resposta, as opções |
| `test_energy.py` | 32 | Modelo de energia: propriedades físicas com muitas sementes, tarifa, contador, definições, contratos, as opções |

## 🏗️ Compilação e publicação

É Python puro: nada a compilar. A versão está em `pyproject.toml` e `armor.project.json`.

## 🩺 Resolução de problemas

| Vê | Porque | Faça |
|---|---|---|
| `--server-url needs a token ...` | Um URL sem token, ou um token sem URL | Indique os dois |
| HTTP 401 / 403 | O token está errado; um servidor estrito quer um token por nó | `--per-node-token` |
| `--allow-invalid` | A falha viola o contrato de propósito | Acrescente-o e não use `--validate` |
| O servidor vê as mensagens como antigas | A data de início predefinida é 0 e o servidor substitui-a | `--start-ms now` |

## 📂 Estrutura do repositório

<p align="center">
  <img src="images/repository-structure.svg" alt="Estrutura do repositório de ARMOR-SIMULATOR" width="100%">
</p>

<details>
<summary>Versão em texto da árvore</summary>

```text
ARMOR-SIMULATOR/
├── src/armor_simulator/
│   ├── cli.py                           as opções e a execução
│   ├── scenarios.py cycle.py            os quatro cenários, a geometria de 270 graus e o dia de luz
│   ├── alarm_scenarios.py               cenários de alarme a partir de ficheiros JSON, as suas mensagens e a verificação da resposta
│   ├── solar.py                         um inversor e uma pilha de dois módulos
│   ├── electrical.py                    os três canais de um nó elétrico
│   ├── energy.py                        dados solares e elétricos realistas: sol com nuvens, casa, tarifa, bateria, contador
│   ├── faults.py                        as sete falhas repetíveis
│   └── publisher.py                     entrega a um servidor com novas tentativas
├── tests/                               os testes
├── docs/                                os guias deste repositório
├── tools/                               as verificações de CI partilhadas e as ferramentas do projeto
├── .github/                             fluxo de CI e modelos de issues e pull requests
├── examples/                            cenários de alarme e definições do modelo de energia para começar
├── images/                              faixa, ícone e as duas imagens deste README
├── build.sh build.bat                   compilar pelo fluxo de projeto partilhado
├── test.sh test.bat                     executar os testes pelo fluxo partilhado
├── run.sh run.bat                       arrancar pelo fluxo de projeto partilhado
├── armor.project.json                   manifesto: versão, função, maturidade, comando de build
├── CHANGELOG.md                         o que mudou em cada versão
├── SECURITY.md SUPPORT.md LICENSE       política de segurança, apoio e licença
├── CONTRIBUTING.md CODE_OF_CONDUCT.md   como contribuir e o código de conduta
├── build-test.sh build-test.bat         executar os testes pelo fluxo partilhado
├── pyproject.toml                       metadados do pacote
└── .gitattributes .gitignore            definições do Git
```

</details>

## 🗺️ Roteiro e limites conhecidos

**Limites conhecidos hoje**

* A geometria é ilustrativa, não um modelo do radar LD2450 real, e nada foi comparado com hardware real.
* Só fala HTTP com um servidor; publicar num broker MQTT não está incluído de propósito.

**A seguir**

* Comparar os cenários com gravações do radar real quando houver nós instalados.

## 🌍 Idiomas

O README e os textos existem em inglês, espanhol, francês, italiano, alemão, chinês, japonês e português europeu.

## 🔗 Projetos relacionados

O **A.R.M.O.R.** (Autonomous Radar & Multimodal Observation Range) é um sistema de segurança perimetral feito de repositórios independentes. Cada um tem a sua própria versão, os seus próprios testes e o seu próprio README; esta é a família:

* **[ARMOR-COMMON](https://github.com/JuanenRac/ARMOR-COMMON)** - Contratos de mensagens, validadores, vetores de conformidade e tipos gerados
* **[ARMOR-NODE-RADAR](https://github.com/JuanenRac/ARMOR-NODE-RADAR)** - Firmware de nó de campo para ESP32-S3 com três radares e o seu próprio painel web
* **[ARMOR-NODE-SOLAR](https://github.com/JuanenRac/ARMOR-NODE-SOLAR)** - Protocolos de inversores e baterias solares e as mensagens de um nó porta de ligação
* **[ARMOR-NODE-ELECTRICAL](https://github.com/JuanenRac/ARMOR-NODE-ELECTRICAL)** - Nó elétrico: contadores, a mensagem das leituras da rede e as regras de comutação
* **[ARMOR-NODE-ALARM](https://github.com/JuanenRac/ARMOR-NODE-ALARM)** - Nó e painel de alarme: zonas, armar, atrasos, sirene e PIN, com o servidor ou sem ele
* **[ARMOR-NODE-HMI](https://github.com/JuanenRac/ARMOR-NODE-HMI)** - Painel tátil: o estado do sistema num ecrã de parede, armar e reconhecer, e a casa do assistente de voz
* **[ARMOR-NETWORK](https://github.com/JuanenRac/ARMOR-NETWORK)** - A rede local: os seus dispositivos, a internet e o que muda
* **[ARMOR-SERVER](https://github.com/JuanenRac/ARMOR-SERVER)** - Coordenador central: telemetria, alarmes, dispositivos, leituras solares e câmaras
* **[ARMOR-STUDIO](https://github.com/JuanenRac/ARMOR-STUDIO)** - Consola web: câmaras, radar, alarmes, energia solar e o desenhador 2D/3D do local
* **[ARMOR-ANDROID-CONTROL](https://github.com/JuanenRac/ARMOR-ANDROID-CONTROL)** - Cliente de operador Android com radar 2D/3D em direto
* **[ARMOR-IOS-CONTROL](https://github.com/JuanenRac/ARMOR-IOS-CONTROL)** - Cliente de operador para iPhone
* **[ARMOR-SERVER-AI](https://github.com/JuanenRac/ARMOR-SERVER-AI)** - Política de inferência visual que explica as suas decisões e nunca atua
* **[ARMOR-VISION](https://github.com/JuanenRac/ARMOR-VISION)** - Zonas de câmara, máscaras e regras de deteção para o Jetson Orin NX
* **[ARMOR-VOICE-AI](https://github.com/JuanenRac/ARMOR-VOICE-AI)** - Intenções de voz offline com uma confirmação que não pode ser falsificada
* **[ARMOR-HARDWARE](https://github.com/JuanenRac/ARMOR-HARDWARE)** - Caixas, eletrónica e a matriz de aceitação em bancada
* **[ARMOR-DEVOPS](https://github.com/JuanenRac/ARMOR-DEVOPS)** - Implantação, a bancada de testes do CM5, cópias de segurança e TLS
* **ARMOR-SIMULATOR** (este repositório) - Simulador de telemetria offline com falhas repetíveis
* **[ARMOR-UPDATER](https://github.com/JuanenRac/ARMOR-UPDATER)** - Deteta, instala e atualiza os repositórios do próprio ecossistema
* **[ARMOR-DOCS](https://github.com/JuanenRac/ARMOR-DOCS)** - Arquitetura, base de segurança e a matriz de capacidades

## 📚 Documentação

* [Utilização](docs/USAGE.md): todas as opções, cenários e falhas
* [Cenários de alarme](docs/ALARM_SCENARIOS.md): o formato do ficheiro e como verificar a resposta de um servidor
* [Modelo de energia](docs/ENERGY_MODEL.md): os dados solares e elétricos realistas e as suas definições
* [Matriz de capacidades: o que está demonstrado e o que não está](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/CAPABILITY_MATRIX.md)
* [Catálogo de projetos: versões e como os repositórios dependem uns dos outros](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/PROJECT_CATALOG.md)
* [Registo de alterações deste repositório](CHANGELOG.md)

## 🤝 Contribuir e comunidade

* Antes de um pull request, execute `python -m unittest discover -s tests` and `python -I tools/armor_ci_validate.py`: tem de passar. Consulte [CONTRIBUTING.md](CONTRIBUTING.md) e o [código de conduta](CODE_OF_CONDUCT.md).
* O README existe em oito idiomas e é gerado a partir das fontes do ARMOR-DOCS: uma alteração ao texto faz-se lá.
* Uma alteração a uma mensagem entre componentes começa no ARMOR-COMMON.
* Não descreva como a funcionar numa placa aquilo que só foi compilado.
* Comunique uma vulnerabilidade em privado: [SECURITY.md](SECURITY.md). Perguntas, ideias e relatórios: electrohobby3d@gmail.com ([SUPPORT.md](SUPPORT.md)).

## 👤 AUTOR

**JuanenRac (Electro Hobby 3D)** · electrohobby3d@gmail.com

## 📜 LICENÇA

GPL-3.0-or-later - consulte [LICENSE](LICENSE).
