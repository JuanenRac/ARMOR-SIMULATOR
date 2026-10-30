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
  🇯🇵 <b>日本語</b> |
  <a href="README_por.md">🇵🇹 Português</a>
</p>

### 再現可能な故障を備えたオフラインのテレメトリシミュレーター

<p align="center">
  <img src="https://img.shields.io/badge/License-GPL%203.0--or--later-blue.svg" alt="GPL 3.0 or later">
  <img src="https://img.shields.io/badge/Language-Python%203.11%2B-3776ab.svg" alt="Language">
  <img src="https://img.shields.io/badge/Dependencies-none-2ea44f.svg" alt="Dependencies">
  <img src="https://img.shields.io/badge/Tests-63%20passing-2ea44f.svg" alt="Tests">
  <img src="https://img.shields.io/badge/Version-0.2.7-0f6cbd.svg" alt="Version">
  <img src="https://img.shields.io/badge/Maturity-established-2EA44F.svg" alt="Maturity">
</p>

---

**正直さのチェック - 今日動いているもの:** シナリオ、故障、サーバーへの送信、63 件のテストは実在し、ノードを接続していないときにコンピューター上のサーバーにデータを送るのがシミュレーターです。ジオメトリは**例示的**なもので、実際の LD2450 レーダーのモデルではなく、実機との比較は一切していません。

---

## 📋 ひと目で

| | |
|---|---|
| バージョン | `0.2.7` |
| 成熟度 | 確立 |
| 役割 | オフラインのテレメトリ・環境シミュレーター（ファミリー：Testing、親：ARMOR-COMMON） |
| 技術 | Python 3.11+、標準ライブラリのみ |
| テスト | 63 (`python -m unittest discover -s tests`) |
| シナリオと障害 | シナリオ 4、障害 7（うち 3 は意図的にコントラクト違反） |
| 動作環境 | 任意のコンピューターまたは CI |
| 実機での確認 | 該当なし：ハードウェアの代役で、コンピューター上で使います |
| ライセンス | GPL-3.0-or-later |

**移動先：** [概要](#-概要) · [アーキテクチャ](#-アーキテクチャ) · [セキュリティ](#-セキュリティと安全) · [インターフェース](#-インターフェース) · [設定](#-設定) · [クイックスタート](#-クイックスタート) · [テスト](#-テスト) · [トラブルシューティング](#-トラブルシューティング) · [構成](#-リポジトリの構成) · [関連](#-関連プロジェクト)

## 🚦 プロジェクトの状況

各行はこのリポジトリの一部分で、信号は今日どこまで進んでいるかを示します。計画ではなく、リポジトリが示せるもの（テスト、ビルド、実行）に基づいて書かれています。

🟢 完了・検証済み · 🟡 動作する（既知の制限あり） · 🟠 一部のみ、または未検証 · 🔴 未実装または動作しない

| 領域 | 状態 | ここでの意味 |
|---|---|---|
| ソフトウェア | 🟢 | シナリオ、故障、サーバーへの配信は動作します。ノードを接続していないとき、コンピューター上のサーバーにデータを送るのがこれです。 |
| テスト | 🟢 | 63 件のテストが通ります（`python -m unittest discover -s tests`）。 |
| プロトコルとデータ | 🟠 | 幾何は例示用で、実際の LD2450 レーダーのモデルではありません。実機との比較もしていません。 |
| 連携 | 🟢 | テストではメッセージをサーバーに配信しており、CM5 テストベンチのサーバーにもこれでデータを送れます。 |
| ドキュメント | 🟢 | 8 言語と変更履歴は最新です。 |

## 🎯 概要

* **シナリオ：** `patrol`、`crossing`、`two-intruders`、`empty`。センサー 3 基の 270 度配置で、昼夜の光サイクルまたは固定の夜を選べます。
* **再現可能な故障：** 沈黙するノード、順序が入れ替わったり重複したりするメッセージ、不安定なノード、そして否定テスト用にわざと無効にしたメッセージ（lux の上限超過、未知のフィールド、トラックが多すぎる）。
* **決定的：** 同じシードは常に同じ行を出力します。`--server-url` と `--ingest-token` を指定しない限り何も送信しません。
* **契約に照らして検査：** `--validate` は各メッセージを送り出す前に ARMOR-COMMON に通します。
* **慎重な送信：** 単純な http(s) オリジンのみ受け付けます。4xx は実行を止め、5xx やネットワークエラーは再試行します。
* **電気ノード：** `--electrical` は、電気ノードの 3 つのチャンネル（系統入力、給湯器、直流バス）を加速した 1 日にわたって出力し、停電、高電圧の期間、電力量計の警報を含みます。
* **太陽光設備：** `--solar` は、240 サンプルの早送りの 1 日の間に、インバーターと 2 モジュールのバッテリースタック（各 15 セル、容量付き）を加え、夕方に系統の停電を起こします。メッセージは ARMOR-COMMON の太陽光契約で検査され、`/api/v1/solar` に送られます。

## 🧩 A.R.M.O.R. での役割

ARMOR-SIMULATOR は、ハードウェアなしでファミリーの他の部分を試す手段です。レーダーノード、ソーラーゲートウェイ、電気ノードの役を演じてそのメッセージを [ARMOR-SERVER](https://github.com/JuanenRac/ARMOR-SERVER) に送り、再現できる故障も起こせるため、存在しない家で [ARMOR-STUDIO](https://github.com/JuanenRac/ARMOR-STUDIO) とスマートフォンアプリが動く様子を見られます。生成するメッセージはすべて [ARMOR-COMMON](https://github.com/JuanenRac/ARMOR-COMMON) のコントラクトで検査されます。

| 名前 | 方法 | 用途 |
|---|---|---|
| ARMOR-SERVER | `POST /api/v1/telemetry`, `/health`, `/solar`, `/electrical/readings` | 模擬メッセージを受け取る |
| ARMOR-COMMON | `--validate` | 各メッセージを検証するコントラクト |
| ARMOR-STUDIO, ARMOR-ANDROID-CONTROL | サーバー経由 | 模擬の家を表示する |

## 🏛️ アーキテクチャ

<p align="center">
  <img src="images/architecture.svg" alt="ARMOR-SIMULATOR のアーキテクチャ：呼び出し元、内部、依存先" width="100%">
</p>

## 🔒 セキュリティと安全

| 脅威 | 対策 |
|---|---|
| 不審な宛先への送信 | パスや認証情報のない単純な http(s) オリジンのみ受け付けます。4xx は実行を止め、5xx やネットワークエラーは 3 回再試行します |
| トークンがプロセス一覧に表示される | `--ingest-token` は非推奨です。`ARMOR_INGEST_TOKEN` か `--ingest-token-file` を使ってください。トークンはどこにも書き込まれません |
| テストが誤って本番サーバーに届く | `--server-url` とトークンを指定しない限り何も送信されません。ブローカークライアントは一切ありません |
| 意図的にコントラクトを破るメッセージ | `corrupt-lux`、`unknown-field`、`oversized-targets` は `--allow-invalid` が必要で、`--validate` とは併用できません |
| コマンドラインへの悪意ある入力 | ノード ID は `^[a-z0-9][a-z0-9_-]{0,63}$` に合致する必要があり、`--count` は 1〜10 000 です |

これはテスト用ツールです。安全機能ではなく、配置は実際のレーダーのモデルではありません。

## 🔌 インターフェース

| オプション | 既定値 | 設定内容 |
|---|---|---|
| `--scenario` | `patrol` | `patrol`, `crossing`, `two-intruders`, `empty` |
| `--count` | `1` | サンプル数（1〜10 000）。1 サンプルは 1 秒 |
| `--seed` | `0` | 同じシードなら同じ出力 |
| `--light` | `cycle` | `cycle`（昼夜）または `night`（0.3 lux 固定） |
| `--solar`, `--electrical` | off | インバーターとバッテリー／電気ノードも出力 |
| `--fault`, `--fault-every`, `--fault-topic` | `none`, `3`, `all` | 一部のメッセージに再現可能な障害を入れる |
| `--validate`, `--allow-invalid` | off | 各メッセージを ARMOR-COMMON で検証／違反する障害を許可 |
| `--server-url`, `--ingest-token-file`, `--per-node-token` | - | 配信先は ARMOR-SERVER。サーバーが厳格な場合はノードごとのトークン |

すべてのオプション、シナリオ、障害は [docs/USAGE.md](docs/USAGE.md) にあります。メッセージ：`armor/node/<id>/telemetry` と `health`、`armor/solar/<ノード>/<機器>/state`、`armor/electrical/<ノード>/state`。配信先は `/api/v1/telemetry`、`/api/v1/health`、`/api/v1/solar`、`/api/v1/electrical/readings` です。

## ⚙️ 設定

| 変数 | 必須 | 設定内容 |
|---|---|---|
| `ARMOR_INGEST_TOKEN` | `--server-url` 使用時 | サーバーの取り込みトークン（または `--ingest-token-file` のファイルの `ARMOR_INGEST_TOKEN=...` 行） |
| `PYTHONPATH=src` | チェックアウトから | パッケージの場所 |

| 制限 | 値 |
|---|---|
| 1 回あたりのサンプル数 | 1 - 10 000 |
| センサーと視野 | 3 (-75, 0, +75°) × ±60°, 6000 mm |
| 光・ソーラー・電気の 1 日 | 240 サンプル |
| 配信の試行回数／タイムアウト | 3 / 5 s |

## 🚀 クイックスタート

**必要なもの:** Python 3.11+ (標準ライブラリのみ).

```powershell
$env:PYTHONPATH = "src"
python -m armor_simulator --count 20 --scenario crossing --seed 1 --validate
python -m armor_simulator --count 60 --scenario two-intruders --server-url http://127.0.0.1:8080 --ingest-token-file token.env
```

## 🧪 テスト

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests
python -I tools/armor_ci_validate.py
```

| テストファイル | テスト数 | 対象 |
|---|---|---|
| `test_simulator.py` | 37 | シナリオ、障害、ソーラー、電気、検証、ローカル HTTP サーバーへの配信 |
| `test_cli_options.py` | 26 | オプション、その制限、拒否 |

## 🏗️ ビルドとリリース

純粋な Python なのでコンパイルは不要です。バージョンは `pyproject.toml` と `armor.project.json` にあります。

## 🩺 トラブルシューティング

| 症状 | 原因 | 対処 |
|---|---|---|
| `--server-url needs a token ...` | トークンなしの URL、または URL なしのトークン | 両方を指定する |
| HTTP 401 / 403 | 取り込みトークンが誤り。厳格なサーバーはノードごとのトークンを要求 | `--per-node-token` |
| `--allow-invalid` | その障害は意図的にコントラクトを破ります | 追加し、`--validate` は使わない |
| サーバーがメッセージを古いと判断する | 既定の開始日時は 0 でサーバーが置き換える | `--start-ms now` |

## 📂 リポジトリの構成

<p align="center">
  <img src="images/repository-structure.svg" alt="ARMOR-SIMULATOR のリポジトリ構造" width="100%">
</p>

<details>
<summary>ツリーのテキスト版</summary>

```text
ARMOR-SIMULATOR/
├── src/armor_simulator/
│   ├── cli.py                           オプションと実行
│   ├── scenarios.py cycle.py            4 つのシナリオ、270 度の配置、1 日の光
│   ├── solar.py                         インバーターと 2 モジュールのバッテリー
│   ├── electrical.py                    電気ノードの 3 チャンネル
│   ├── faults.py                        再現可能な 7 つの障害
│   └── publisher.py                     再試行つきのサーバーへの配信
├── tests/                               テスト
├── docs/                                このリポジトリのガイド
├── tools/                               共通の CI チェックとプロジェクトツール
├── .github/                             CI ワークフローと Issue・Pull Request のテンプレート
├── images/                              バナー、アイコン、この README の 2 つの図
├── build.sh build.bat                   共通のプロジェクトワークフローでビルド
├── test.sh test.bat                     共通のワークフローでテストを実行
├── run.sh run.bat                       共通のプロジェクトワークフローで起動
├── armor.project.json                   マニフェスト：バージョン、役割、成熟度、ビルドコマンド
├── CHANGELOG.md                         各バージョンの変更点
├── SECURITY.md SUPPORT.md LICENSE       セキュリティポリシー、サポート、ライセンス
├── CONTRIBUTING.md CODE_OF_CONDUCT.md   貢献方法と行動規範
├── build-test.sh build-test.bat         共通のワークフローでテストを実行
├── pyproject.toml                       パッケージのメタデータ
└── .gitattributes .gitignore            Git の設定
```

</details>

## 🗺️ ロードマップと既知の制限

**現時点の既知の制限**

* 配置は説明用で、実際の LD2450 レーダーのモデルではなく、実機との比較はしていません。
* サーバーとは HTTP のみで通信し、MQTT ブローカーへの発行は意図的に組み込んでいません。

**今後**

* ノードが設置されたら、実際のレーダーの記録とシナリオを比較する。

## 🌍 言語

README とテキストは、英語、スペイン語、フランス語、イタリア語、ドイツ語、中国語、日本語、ヨーロッパポルトガル語で提供されています。

## 🔗 関連プロジェクト

**A.R.M.O.R.**（Autonomous Radar & Multimodal Observation Range）は、独立したリポジトリで構成される境界セキュリティシステムです。各リポジトリは独自のバージョン、テスト、README を持ちます。ファミリーは次のとおりです：

* **[ARMOR-COMMON](https://github.com/JuanenRac/ARMOR-COMMON)** - メッセージのコントラクト、バリデーター、適合ベクトル、生成された型
* **[ARMOR-NODE-RADAR](https://github.com/JuanenRac/ARMOR-NODE-RADAR)** - 3 つのレーダーと独自の Web パネルを備えた ESP32-S3 向けフィールドノードのファームウェア
* **[ARMOR-NODE-SOLAR](https://github.com/JuanenRac/ARMOR-NODE-SOLAR)** - ソーラーインバーターとバッテリーのプロトコル、ゲートウェイノードのメッセージ
* **[ARMOR-NODE-ELECTRICAL](https://github.com/JuanenRac/ARMOR-NODE-ELECTRICAL)** - 電気ノード：メーター、系統の読み取り値のメッセージ、切り替えのルール
* **[ARMOR-NODE-ALARM](https://github.com/JuanenRac/ARMOR-NODE-ALARM)** - 警報ノードとパネル：ゾーン、警戒、遅延、サイレン、PIN。サーバーありでもなしでも動作
* **[ARMOR-NODE-HMI](https://github.com/JuanenRac/ARMOR-NODE-HMI)** - タッチパネル：壁面画面でのシステムの状態、警戒と確認応答、そして音声アシスタントの置き場
* **[ARMOR-NETWORK](https://github.com/JuanenRac/ARMOR-NETWORK)** - ローカルネットワーク：そのデバイス、インターネット、そして変化
* **[ARMOR-SERVER](https://github.com/JuanenRac/ARMOR-SERVER)** - 中央コーディネーター：テレメトリ、警報、デバイス、ソーラーの読み取り値、カメラ
* **[ARMOR-STUDIO](https://github.com/JuanenRac/ARMOR-STUDIO)** - Web コンソール：カメラ、レーダー、警報、太陽光エネルギー、2D/3D のサイトデザイナー
* **[ARMOR-ANDROID-CONTROL](https://github.com/JuanenRac/ARMOR-ANDROID-CONTROL)** - ライブの 2D/3D レーダーを備えた Android オペレータークライアント
* **[ARMOR-IOS-CONTROL](https://github.com/JuanenRac/ARMOR-IOS-CONTROL)** - iPhone オペレータークライアント
* **[ARMOR-SERVER-AI](https://github.com/JuanenRac/ARMOR-SERVER-AI)** - 判断を説明し、決して作動させない視覚推論ポリシー
* **[ARMOR-VISION](https://github.com/JuanenRac/ARMOR-VISION)** - Jetson Orin NX 向けのカメラゾーン、マスク、検出ルール
* **[ARMOR-VOICE-AI](https://github.com/JuanenRac/ARMOR-VOICE-AI)** - 偽造できない確認つきのオフライン音声インテント
* **[ARMOR-HARDWARE](https://github.com/JuanenRac/ARMOR-HARDWARE)** - 筐体、電子回路、ベンチ受け入れマトリクス
* **[ARMOR-DEVOPS](https://github.com/JuanenRac/ARMOR-DEVOPS)** - デプロイ、CM5 テストベンチ、バックアップ、TLS
* **ARMOR-SIMULATOR**（このリポジトリ） - 再現可能な障害を持つオフラインのテレメトリシミュレーター
* **[ARMOR-UPDATER](https://github.com/JuanenRac/ARMOR-UPDATER)** - エコシステム自身のリポジトリを検出、インストール、更新
* **[ARMOR-DOCS](https://github.com/JuanenRac/ARMOR-DOCS)** - アーキテクチャ、セキュリティのベースライン、機能マトリクス

## 📚 ドキュメント

* [使い方](docs/USAGE.md)：すべてのオプション、シナリオ、障害
* [機能マトリクス：何が証明され、何が証明されていないか](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/CAPABILITY_MATRIX.md)
* [プロジェクトカタログ：バージョンと、リポジトリ同士の依存関係](https://github.com/JuanenRac/ARMOR-DOCS/blob/main/docs/PROJECT_CATALOG.md)
* [このリポジトリの変更履歴](CHANGELOG.md)

## 🤝 コントリビュートとコミュニティ

* Pull Request の前に `python -m unittest discover -s tests` and `python -I tools/armor_ci_validate.py` を実行してください。通る必要があります。[CONTRIBUTING.md](CONTRIBUTING.md) と[行動規範](CODE_OF_CONDUCT.md)を参照してください。
* README は 8 言語で提供され、ARMOR-DOCS のソースから生成されます。文面の変更はそちらで行います。
* コンポーネント間のメッセージの変更は ARMOR-COMMON から始めます。
* ビルドしただけのものを、ボード上で動いているかのように書かないでください。
* 脆弱性は非公開で報告してください：[SECURITY.md](SECURITY.md)。質問、アイデア、報告：electrohobby3d@gmail.com（[SUPPORT.md](SUPPORT.md)）。

## 👤 作者

**JuanenRac (Electro Hobby 3D)** · electrohobby3d@gmail.com

## 📜 ライセンス

GPL-3.0-or-later - [LICENSE](LICENSE) を参照してください。
