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
  🇯🇵 <b>日本語</b>
</p>

### 再現可能な故障を備えたオフラインのテレメトリシミュレーター

<p align="center">
  <img src="https://img.shields.io/badge/License-GPL%203.0-blue.svg" alt="GPL 3.0">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-3776ab.svg" alt="Language">
  <img src="https://img.shields.io/badge/Dependencies-none-2ea44f.svg" alt="Dependencies">
  <img src="https://img.shields.io/badge/Maturity-functional-00E5FF.svg" alt="Maturity">
</p>

---

**正直さのチェック - 今日動いているもの:** シナリオ、故障、サーバーへの送信、24 件のテストは実在します。ジオメトリは**説明用**であり、実際の LD2450 レーダーのモデルではなく、実ハードウェアと比較したものは何もありません。

---

## 🎯 概要

* **シナリオ：** `patrol`、`crossing`、`two-intruders`、`empty`。センサー 3 基のコーナー配置で、昼夜の光サイクルまたは固定の夜を選べます。
* **再現可能な故障：** 沈黙するノード、順序が入れ替わったり重複したりするメッセージ、不安定なノード、そして否定テスト用にわざと無効にしたメッセージ（lux の上限超過、未知のフィールド、トラックが多すぎる）。
* **決定的：** 同じシードは常に同じ行を出力します。`--server-url` と `--ingest-token` を指定しない限り何も送信しません。
* **契約に照らして検査：** `--validate` は各メッセージを送り出す前に ARMOR-COMMON に通します。
* **慎重な送信：** 単純な http(s) オリジンのみ受け付けます。4xx は実行を止め、5xx やネットワークエラーは再試行します。

## 📂 リポジトリの構成

```text
ARMOR-SIMULATOR/
├── src/armor_simulator/   scenarios, faults, publisher, cli
├── tests/                 24 tests, including a local HTTP server
└── docs/USAGE.md
```

## 🛠️ 開発環境

```powershell
$env:PYTHONPATH="src"
python -m armor_simulator --count 20 --scenario crossing --seed 1 --validate
python -m unittest discover -s tests   # 24 tests
```

全オプション、シナリオ、故障：[使い方](docs/USAGE.md)。

## 🔗 関連プロジェクト

**A.R.M.O.R.**（Autonomous Radar & Multimodal Observation Range）は、独立したリポジトリで構成される周辺警備システムです。それぞれに独自のバージョン、テスト、README があります。ファミリーは次のとおりです：

* **[ARMOR-COMMON](../ARMOR-COMMON)** - メッセージ契約、検証器、適合性ベクトル、生成された型
* **[ARMOR-RADAR](../ARMOR-RADAR)** - ESP32-S3 用フィールドノードのファームウェア。レーダー 3 基と独自の Web パネル付き
* **[ARMOR-SOLAR](../ARMOR-SOLAR)** - 太陽光インバーターとバッテリーのプロトコル、およびゲートウェイノードのメッセージ
* **[ARMOR-SERVER](../ARMOR-SERVER)** - 中央コーディネーター：テレメトリ、アラーム、デバイス、太陽光の測定値、カメラ
* **[ARMOR-STUDIO](../ARMOR-STUDIO)** - Web コンソール：カメラ、レーダー、アラーム、太陽光発電、2D/3D サイト設計
* **[ARMOR-ANDROID-CONTROL](../ARMOR-ANDROID-CONTROL)** - リアルタイム 2D/3D レーダー付きの Android オペレータークライアント
* **[ARMOR-SERVER-AI](../ARMOR-SERVER-AI)** - 判断を説明し、決して動作しない視覚推論ポリシー
* **[ARMOR-VOICE-AI](../ARMOR-VOICE-AI)** - 偽造できない確認を備えたオフライン音声インテント
* **[ARMOR-HARDWARE](../ARMOR-HARDWARE)** - 筐体、電子部品、ベンチ受け入れマトリクス
* **[ARMOR-DEVOPS](../ARMOR-DEVOPS)** - デプロイ、CM5 テストベンチ、バックアップ、TLS
* **ARMOR-SIMULATOR** (このリポジトリ) - 再現可能な故障を備えたオフラインのテレメトリシミュレーター
* **[ARMOR-DOCS](../ARMOR-DOCS)** - アーキテクチャ、セキュリティ基準、機能マトリクス

## 📚 ドキュメントとコミュニティ

詳しくは：

* [機能マトリクス：実証済みのものとそうでないもの](../ARMOR-DOCS/docs/CAPABILITY_MATRIX.md)
* [プロジェクト一覧：バージョンとリポジトリ間の依存関係](../ARMOR-DOCS/docs/PROJECT_CATALOG.md)
* [このリポジトリの変更履歴](CHANGELOG.md)
* [ライセンス（GPL-3.0-or-later）](LICENSE)
* 質問・提案・報告：electrohobby3d@gmail.com

## 👤 作者

**JuanenRac (Electro Hobby 3D)** · electrohobby3d@gmail.com

## 📜 ライセンス

GPL-3.0-or-later - [LICENSE](LICENSE) を参照。
