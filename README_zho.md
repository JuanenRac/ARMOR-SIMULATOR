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
  🇨🇳 <b>简体中文</b> |
  <a href="README_jpn.md">🇯🇵 日本語</a> |
  <a href="README_por.md">🇵🇹 Português</a>
</p>

### 带可重复故障的离线遥测模拟器

<p align="center">
  <img src="https://img.shields.io/badge/License-GPL%203.0--or--later-blue.svg" alt="GPL 3.0 or later">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-3776ab.svg" alt="Language">
  <img src="https://img.shields.io/badge/Dependencies-none-2ea44f.svg" alt="Dependencies">
  <img src="https://img.shields.io/badge/Tests-127%20passing-2ea44f.svg" alt="Tests">
  <img src="https://img.shields.io/badge/Version-0.2.7-0f6cbd.svg" alt="Version">
  <img src="https://img.shields.io/badge/Maturity-established-2EA44F.svg" alt="Maturity">
</p>

---

**诚实性检查 - 今天真正能运行的部分：** 场景、故障、向服务器的投递和 127 个测试都是真实的，没有节点接入时，模拟器用来给计算机上的服务器供数据。几何是**示意性的**，不是真实 LD2450 雷达的模型，这里的一切都没有与真实硬件对比过。

---

## 📋 速览

| | |
|---|---|
| 版本 | `0.2.7` |
| 成熟度 | 成熟 |
| 角色 | 离线遥测与环境模拟器（家族：Testing，上级：ARMOR-COMMON） |
| 技术栈 | Python 3.11+，仅标准库 |
| 测试 | 127 (`python -m unittest discover -s tests`) |
| 场景与故障 | 4 个场景、7 种故障（其中 3 种故意违反合约） |
| 运行位置 | 任何计算机或 CI |
| 真实硬件 | 不适用：它是硬件的替身，在计算机上使用 |
| 许可证 | GPL-3.0-or-later |

**跳转到：** [概述](#-概述) · [架构](#-架构) · [安全](#-安全与防护) · [接口](#-接口) · [配置](#-配置) · [快速开始](#-快速开始) · [测试](#-测试) · [故障排除](#-故障排除) · [结构](#-仓库结构) · [相关项目](#-相关项目)

## 🚦 项目状态

每一行是本仓库的一个部分，灯号表示它今天做到了哪一步。内容依据仓库能够展示的证据（测试、构建、运行），而不是计划。

🟢 已完成并验证 · 🟡 可用，有已知限制 · 🟠 部分完成或尚未验证 · 🔴 未完成或不可用

| 领域 | 状态 | 在这里的含义 |
|---|---|---|
| 软件 | 🟢 | 场景、故障和向服务器的投递都能工作；没有接入节点时，它为电脑上的服务器提供数据。 |
| 测试 | 🟢 | 127 项测试通过（`python -m unittest discover -s tests`）。 |
| 协议与数据 | 🟠 | 几何模型仅作示意，并不是真实 LD2450 雷达的模型，也没有与真实硬件对比过。 |
| 集成 | 🟢 | 测试中它会把消息投递到服务器，CM5 测试台的服务器也可以由它提供数据。 |
| 文档 | 🟢 | 八种语言和更新日志均为最新。 |

## 🎯 概述

* **场景：** `patrol`、`crossing`、`two-intruders` 和 `empty`，基于三传感器的 270 度几何，另有昼夜光照周期或固定夜晚。
* **可重复的故障：** 静默节点、乱序和重复的消息、抖动的节点，以及为负面测试特意构造的无效消息（lux 超限、未知字段、轨迹过多）。
* **确定性：** 相同的种子总是打印相同的行；除非提供 `--server-url` 和 `--ingest-token`，否则不会发送任何内容。
* **对照契约检查：** `--validate` 在发出每条消息之前先让它通过 ARMOR-COMMON。
* **谨慎投递：** 只接受简单的 http(s) 源；4xx 会终止运行，5xx 或网络错误会重试。
* **电气节点：** `--electrical` 会在加速的一天里加入电气节点的三个通道（电网入口、热水器和直流母线），其中包含一次停电、一段高电压和一次电表告警。
* **太阳能设备：** `--solar` 会在 240 个样本的快进一天中加入一台逆变器和一个两模块的电池组（每个模块十五个电芯，含容量），并在傍晚出现一次市电中断；消息会对照 ARMOR-COMMON 的太阳能契约检查，并投递到 `/api/v1/solar`。
* **用文件描述的报警场景：** `--alarm-scenario` 播放一个带时间线的 JSON 文件（人依次穿过多个区域、宠物、风、卡死/噪声/漂移/失效的传感器、失去链路的节点、市电中断、模式与日历），还可以写明系统应当如何响应；`--verify-alarms` 把服务器实际发出的报警与之比较，因此这些文件就是 ARMOR-SERVER 的测试用例。读取很严格：遇到第一处无法理解的内容就拒绝整个文件。
* **真实的能源数据：** `--energy` 根据实时模型（带云的日照、按小时变化的住宅用电、电价、带循环的 Pylontech 式电池、有噪声和缺失的电表）输出逆变器、电池组和电气节点的消息；对同一种子结果确定，并可通过 JSON 文件调整。不使用新选项时，输出与之前完全一致。

## 🧩 在 A.R.M.O.R. 中的角色

ARMOR-SIMULATOR 让家族的其他部分无需硬件就能试用：它扮演雷达节点、太阳能网关或电气节点，把它们的消息发给 [ARMOR-SERVER](https://github.com/JuanenRac/ARMOR-SERVER)，故障可重复，这样就能看到 [ARMOR-STUDIO](https://github.com/JuanenRac/ARMOR-STUDIO) 和手机应用在一个并不存在的住宅上运行。它生成的每条消息都对照 [ARMOR-COMMON](https://github.com/JuanenRac/ARMOR-COMMON) 的契约检查。

| 名称 | 方式 | 用途 |
|---|---|---|
| ARMOR-SERVER | `POST /api/v1/telemetry`, `/health`, `/solar`, `/electrical/readings` | 接收模拟消息 |
| ARMOR-COMMON | `--validate` | 每条消息所校验的合约 |
| ARMOR-STUDIO, ARMOR-ANDROID-CONTROL | 通过服务器 | 显示模拟的住宅 |

## 🏛️ 架构

<p align="center">
  <img src="images/architecture.svg" alt="ARMOR-SIMULATOR 的架构：谁调用它、它包含什么、它依赖什么" width="100%">
</p>

## 🔒 安全与防护

| 威胁 | 防御 |
|---|---|
| 发送到可疑目标 | 只接受不带路径和凭据的普通 http(s) 源；4xx 会停止运行，5xx 或网络错误会重试三次 |
| 令牌出现在进程列表中 | 不建议使用 `--ingest-token`；请使用 `ARMOR_INGEST_TOKEN` 或 `--ingest-token-file`；令牌不会被写到任何地方 |
| 测试意外连到真实服务器 | 除非提供 `--server-url` 和令牌，否则不会发送任何内容；根本没有代理客户端 |
| 故意违反合约的消息 | `corrupt-lux`、`unknown-field` 和 `oversized-targets` 需要 `--allow-invalid`，且不能与 `--validate` 同用 |
| 命令行上的恶意输入 | 节点 ID 必须匹配 `^[a-z0-9][a-z0-9_-]{0,63}$`，`--count` 范围为 1 到 10 000 |

这是测试工具：不是安全功能，其几何也不是真实雷达的模型。

## 🔌 接口

| 选项 | 默认值 | 作用 |
|---|---|---|
| `--scenario` | `patrol` | `patrol`, `crossing`, `two-intruders`, `empty` |
| `--count` | `1` | 采样数（1 到 10 000）；一个采样为一秒 |
| `--seed` | `0` | 相同种子输出相同的行 |
| `--light` | `cycle` | `cycle`（昼夜）或 `night`（固定 0.3 lux） |
| `--solar`, `--electrical` | off | 同时输出带电池的逆变器／电气节点 |
| `--alarm-scenario`, `--check-alarm-scenario`, `--verify-alarms` | - | 播放 JSON 文件中的报警场景 / 仅校验 / 把服务器发出的报警与期望比较（不一致时退出码为 1） |
| `--energy`, `--energy-config`, `--energy-days`, `--energy-step-s` | 关, -, `1`, `900` | 用实时的真实太阳能与电力数据取代 `--solar`/`--electrical` 的快速一天 |
| `--fault`, `--fault-every`, `--fault-topic` | `none`, `3`, `all` | 向部分消息注入可重复的故障 |
| `--validate`, `--allow-invalid` | off | 用 ARMOR-COMMON 校验每条消息／允许违反合约的故障 |
| `--server-url`, `--ingest-token-file`, `--per-node-token` | - | 投递到 ARMOR-SERVER；服务器严格时使用每个节点的令牌 |

所有选项、场景和故障见 [docs/USAGE.md](docs/USAGE.md)。消息：`armor/node/<id>/telemetry` 和 `health`、`armor/solar/<节点>/<设备>/state`、`armor/electrical/<节点>/state`；投递到 `/api/v1/telemetry`、`/api/v1/health`、`/api/v1/solar` 和 `/api/v1/electrical/readings`。

## ⚙️ 配置

| 变量 | 必需 | 作用 |
|---|---|---|
| `ARMOR_INGEST_TOKEN` | 配合 `--server-url` | 服务器的摄取令牌（或 `--ingest-token-file` 文件中的 `ARMOR_INGEST_TOKEN=...` 行） |
| `PYTHONPATH=src` | 从源码目录 | 包所在位置 |

| 限制 | 值 |
|---|---|
| 每次运行的采样数 | 1 - 10 000 |
| 传感器与视场 | 3 (-75, 0, +75°) × ±60°, 6000 mm |
| 光照、太阳能和电气的一天 | 240 个采样 |
| 投递尝试次数／超时 | 3 / 5 s |

## 🚀 快速开始

**要求:** Python 3.11+ (仅标准库).

```powershell
$env:PYTHONPATH = "src"
python -m armor_simulator --count 20 --scenario crossing --seed 1 --validate
python -m armor_simulator --count 60 --scenario two-intruders --server-url http://127.0.0.1:8080 --ingest-token-file token.env
```

## 🧪 测试

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
python -I tools/armor_ci_validate.py
```

| 测试文件 | 测试数 | 覆盖内容 |
|---|---|---|
| `test_simulator.py` | 37 | 场景、故障、太阳能、电气、校验、向本地 HTTP 服务器投递 |
| `test_cli_options.py` | 26 | 选项、其限制和拒绝情形 |
| `test_alarm_scenarios.py` | 32 | 报警场景文件：严格读取、消息流、模式与日历、响应验证、选项 |
| `test_energy.py` | 32 | 能源模型：多种子下的物理性质、电价、电表、设置、契约、选项 |

## 🏗️ 构建与发布

纯 Python：无需编译。版本在 `pyproject.toml` 和 `armor.project.json` 中。

## 🩺 故障排除

| 现象 | 原因 | 处理 |
|---|---|---|
| `--server-url needs a token ...` | 有 URL 无令牌，或有令牌无 URL | 两者都提供 |
| HTTP 401 / 403 | 摄取令牌错误；严格的服务器要求每个节点一个令牌 | `--per-node-token` |
| `--allow-invalid` | 该故障故意违反合约 | 加上它，并且不要用 `--validate` |
| 服务器认为消息已过期 | 默认起始时间为 0，服务器会替换它 | `--start-ms now` |

## 📂 仓库结构

<p align="center">
  <img src="images/repository-structure.svg" alt="ARMOR-SIMULATOR 的仓库结构" width="100%">
</p>

<details>
<summary>目录树的文本版</summary>

```text
ARMOR-SIMULATOR/
├── src/armor_simulator/
│   ├── cli.py                           选项与运行
│   ├── scenarios.py cycle.py            四种场景、270 度几何和一天的光照
│   ├── alarm_scenarios.py               来自 JSON 文件的报警场景、其消息以及对响应的检查
│   ├── solar.py                         逆变器和两模块电池组
│   ├── electrical.py                    电气节点的三个通道
│   ├── energy.py                        真实的太阳能与电力数据:带云的日照、住宅、电价、电池、电表
│   ├── faults.py                        七种可重复的故障
│   └── publisher.py                     带重试的服务器投递
├── tests/                               测试
├── docs/                                本仓库的指南
├── tools/                               共享的 CI 检查和项目工具
├── .github/                             CI 工作流以及 Issue 和 Pull Request 模板
├── examples/                            可供起步的报警场景与能源模型设置
├── images/                              横幅、图标和本 README 的两幅图
├── build.sh build.bat                   通过共享的项目工作流构建
├── test.sh test.bat                     通过共享工作流运行测试
├── run.sh run.bat                       通过共享的项目工作流启动
├── armor.project.json                   清单：版本、角色、成熟度、构建命令
├── CHANGELOG.md                         每个版本的变化
├── SECURITY.md SUPPORT.md LICENSE       安全策略、支持和许可证
├── CONTRIBUTING.md CODE_OF_CONDUCT.md   如何贡献与行为准则
├── build-test.sh build-test.bat         通过共享工作流运行测试
├── pyproject.toml                       包元数据
└── .gitattributes .gitignore            Git 设置
```

</details>

## 🗺️ 路线图与已知限制

**目前已知的限制**

* 几何仅作演示，不是真实 LD2450 雷达的模型，也没有与真实硬件对比过。
* 只通过 HTTP 与服务器通信；刻意没有内置向 MQTT 代理发布。

**下一步**

* 节点安装后，用真实雷达的录制数据对比这些场景。

## 🌍 语言

README 和文本提供英语、西班牙语、法语、意大利语、德语、汉语、日语和欧洲葡萄牙语版本。

## 🔗 相关项目

**A.R.M.O.R.**（Autonomous Radar & Multimodal Observation Range）是一个由相互独立的仓库组成的周界安全系统。每个仓库都有自己的版本、自己的测试和自己的 README；这是整个系列：

* **[ARMOR-COMMON](https://github.com/JuanenRac/ARMOR-COMMON)** - 消息契约、验证器、一致性向量和生成的类型
* **[ARMOR-NODE-RADAR](https://github.com/JuanenRac/ARMOR-NODE-RADAR)** - 面向 ESP32-S3 的现场节点固件，配三个雷达和自带的网页面板
* **[ARMOR-NODE-SOLAR](https://github.com/JuanenRac/ARMOR-NODE-SOLAR)** - 太阳能逆变器和电池的协议，以及网关节点的消息
* **[ARMOR-NODE-ELECTRICAL](https://github.com/JuanenRac/ARMOR-NODE-ELECTRICAL)** - 电气节点：电表、电网读数的消息和切换规则
* **[ARMOR-NODE-ALARM](https://github.com/JuanenRac/ARMOR-NODE-ALARM)** - 报警节点与面板：防区、布防、延时、警笛和 PIN，可配合服务器也可独立使用
* **[ARMOR-NODE-HMI](https://github.com/JuanenRac/ARMOR-NODE-HMI)** - 触摸面板：壁挂屏幕上的系统状态、布防与确认，以及语音助手的所在
* **[ARMOR-NETWORK](https://github.com/JuanenRac/ARMOR-NETWORK)** - 本地网络：其设备、互联网以及变化
* **[ARMOR-SERVER](https://github.com/JuanenRac/ARMOR-SERVER)** - 中央协调器：遥测、报警、设备、太阳能读数和摄像头
* **[ARMOR-STUDIO](https://github.com/JuanenRac/ARMOR-STUDIO)** - 网页控制台：摄像头、雷达、报警、太阳能以及 2D/3D 场地设计器
* **[ARMOR-ANDROID-CONTROL](https://github.com/JuanenRac/ARMOR-ANDROID-CONTROL)** - 带实时 2D/3D 雷达的 Android 操作员客户端
* **[ARMOR-IOS-CONTROL](https://github.com/JuanenRac/ARMOR-IOS-CONTROL)** - iPhone 操作员客户端
* **[ARMOR-SERVER-AI](https://github.com/JuanenRac/ARMOR-SERVER-AI)** - 视觉推理策略，会解释其决策且从不驱动设备
* **[ARMOR-VISION](https://github.com/JuanenRac/ARMOR-VISION)** - 面向 Jetson Orin NX 的摄像头区域、遮罩和检测规则
* **[ARMOR-VOICE-AI](https://github.com/JuanenRac/ARMOR-VOICE-AI)** - 离线语音意图，附带无法伪造的确认
* **[ARMOR-HARDWARE](https://github.com/JuanenRac/ARMOR-HARDWARE)** - 外壳、电子器件和台架验收矩阵
* **[ARMOR-DEVOPS](https://github.com/JuanenRac/ARMOR-DEVOPS)** - 部署、CM5 测试台、备份和 TLS
* **ARMOR-SIMULATOR**（本仓库） - 带可重复故障的离线遥测模拟器
* **[ARMOR-UPDATER](https://github.com/JuanenRac/ARMOR-UPDATER)** - 检测、安装和更新生态系统自身的仓库
* **[ARMOR-DOCS](https://github.com/JuanenRac/ARMOR-DOCS)** - 架构、安全基线和能力矩阵

## 📚 文档

* [用法](docs/USAGE.md)：所有选项、场景和故障
* [报警场景](docs/ALARM_SCENARIOS.md)：文件格式以及如何验证服务器的响应
* [能源模型](docs/ENERGY_MODEL.md)：真实的太阳能与电力数据及其设置
* [能力矩阵：哪些已被证明，哪些没有](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/CAPABILITY_MATRIX.md)
* [项目目录：版本以及各仓库之间如何相互依赖](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/PROJECT_CATALOG.md)
* [本仓库的更新日志](CHANGELOG.md)

## 🤝 参与贡献与社区

* 提交 Pull Request 之前请运行 `python -m unittest discover -s tests` and `python -I tools/armor_ci_validate.py`：必须通过。参见 [CONTRIBUTING.md](CONTRIBUTING.md) 和[行为准则](CODE_OF_CONDUCT.md)。
* README 提供八种语言，由 ARMOR-DOCS 中的源文件生成：文本的修改在那里进行。
* 组件之间消息的变更从 ARMOR-COMMON 开始。
* 不要把仅仅构建过的东西描述为已在板子上运行。
* 请私下报告漏洞：[SECURITY.md](SECURITY.md)。问题、想法和报告：electrohobby3d@gmail.com（[SUPPORT.md](SUPPORT.md)）。

## 👤 作者

**JuanenRac (Electro Hobby 3D)** · electrohobby3d@gmail.com

## 📜 许可证

GPL-3.0-or-later - 见 [LICENSE](LICENSE)。
