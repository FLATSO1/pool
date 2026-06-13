# autotrader — 日本株 自動売買アプリ

ファンダメンタルで銘柄を選定し、テクニカルで売買タイミングを判定、
ニュース/SNSのセンチメントでマクロ視点を反映して、ペーパートレード
または実弾（**三菱UFJ eスマート証券**＝旧auカブコム証券の kabuステーションAPI）
で発注する Python アプリです。

> SBI証券など個人向けの自動発注APIが無い証券会社では、本アプリは
> 「銘柄選定〜売買シグナル」までを担い、発注は手動で行う半自動運用になります。
> 完全自動発注には kabuステーションAPI を提供する三菱UFJ eスマート証券などの
> 口座が必要です。

```
ファンダメンタル選定 → テクニカル解析 → ニュース/SNSセンチメント補正 → 発注
```

> ⚠️ **重要な免責事項**
> 本ソフトウェアは投資助言ではありません。相場は予測しきれず、自動売買で
> 「確実に儲かる」ことはありません。**実弾発注は自己責任**で、必ず
> ペーパートレードとバックテストで戦略を十分に検証してから使用してください。
> 過去のパフォーマンスは将来の結果を保証しません。

---

## 特徴

- **ユニバース** — 手書きリスト or CSV（日経225など）を全銘柄スキャンして選定
- **ファンダメンタル選定** — PER / ROE / 利益率 / 売上成長 / D/E をスコア化し足切り
- **テクニカル解析** — SMAクロス・MACD・RSI を加重統合（TA-Lib不要、pandasのみ）
- **センチメント** — Claude API（`claude-opus-4-8`）でニュース/SNS見出しを解析。
  APIキーが無い場合は辞書ベースに自動フォールバック
- **ブローカー抽象化** — 同一インターフェースで **ペーパー** と **ライブ（kabuステーション）** を切替
- **バックテスト** — 損切り/利確・手数料・資金配分・同時保有数を考慮した検証
- **安全ガード** — ライブ発注はデフォルト無効（`AUTOTRADER_ENABLE_LIVE=true` が必須）

## アーキテクチャ

```
src/autotrader/
├── config.py            設定（YAML＋環境変数）
├── data/
│   ├── market_data.py   株価OHLCV（yfinance）
│   ├── fundamentals.py  ファンダメンタル指標（yfinance）
│   └── news.py          ニュース見出し（yfinance + Google News RSS）
├── analysis/
│   ├── fundamental.py   ファンダメンタル・スコアリング
│   ├── technical.py     テクニカル指標とシグナル
│   └── sentiment.py     Claude API センチメント分析
├── strategy/
│   └── engine.py        3シグナルの統合と意思決定
├── broker/
│   ├── base.py          ブローカー共通インターフェース
│   ├── paper.py         ペーパートレード（状態をJSON永続化）
│   └── kabus.py         kabuステーションAPI（ライブ発注）
├── backtest/
│   └── backtester.py    イベント駆動バックテスト
├── portfolio.py         リスク管理（損切り/利確）
└── cli.py               コマンドライン
```

## セットアップ

```bash
# 依存をインストール（開発用ツール込み）
pip install -e ".[dev]"

# 設定ファイルを用意
cp config.example.yaml config.yaml
cp .env.example .env          # APIキー等を記入

# テスト
pytest
```

### 環境変数（.env）

| 変数 | 用途 |
|------|------|
| `ANTHROPIC_API_KEY` | Claude API（センチメント分析）。未設定なら辞書ベースに自動切替 |
| `KABUS_API_PASSWORD` | kabuステーションAPIパスワード（ライブ） |
| `KABUS_TRADE_PASSWORD` | 取引パスワード（発注に必須・ライブ） |
| `KABUS_BASE_URL` | 既定 `http://localhost:18080/kabusapi`（本番）/ `18081`（検証） |
| `AUTOTRADER_ENABLE_LIVE` | `true` で初めて実弾発注を許可（既定 `false`） |

## 使い方

```bash
# 1) ファンダメンタルでユニバースを選定
autotrader screen

# 2) 1銘柄を総合解析（ファンダ＋テクニカル＋センチメント）
autotrader analyze 7203.T

# 3) 過去データでバックテスト
autotrader backtest

# 4) 1サイクル評価して発注（既定はペーパー）。判断だけ見るなら --dry-run
autotrader run --dry-run
autotrader run

# 5) ペーパー口座の状態を表示
autotrader account

# 6) kabuステーションAPIへの接続確認（発注しない・セットアップの切り分け用）
autotrader kabus-check          # ユニバース先頭の現在値で確認
autotrader kabus-check 7203.T   # 銘柄を指定
```

> モジュールとして実行する場合は `python -m autotrader.cli <command>`。

### ライブ発注（実弾）への切替

対応証券会社: **三菱UFJ eスマート証券（旧auカブコム証券）** の kabuステーションAPI。

1. 三菱UFJ eスマート証券で口座を開設し、**kabuステーションの利用を申し込む**
   （利用条件あり。最新は公式で確認）
2. Windows で **kabuステーション** を起動・ログインし、設定→APIでパスワードを発行
   （kabuステーションはWindows専用。APIは起動中PCの `localhost:18080` のみ応答）
3. `.env` に `KABUS_API_PASSWORD` と `KABUS_TRADE_PASSWORD` を設定
4. **`autotrader kabus-check` で接続を確認**（認証・現在値・余力。発注はしない）
5. `config.yaml` の `trading.mode` を `live` に
6. `.env` で `AUTOTRADER_ENABLE_LIVE=true`（この二重ガードを通さない限りペーパーで動作）

> まずは検証環境（`KABUS_BASE_URL=http://localhost:18081/kabusapi`）で
> 動作を確認してから本番（18080）に切り替えるのが安全です。

## ユニバース（銘柄選定の範囲）

「どの銘柄を検討対象にするか」は `config.yaml` で切り替えます。

```yaml
universe_source: "file"                       # "manual" | "file"
universe_file: "data/universe/nikkei225.csv"  # file時に読むCSV（code列）
```

- **`manual`** … `universe:` に手書きした銘柄だけを対象
- **`file`** … CSV（`code` 列）の銘柄を対象。**日経225を全銘柄スキャン**したい場合はこちら

同梱の `data/universe/nikkei225.csv` には日経225の**主要構成銘柄**を収録しています。
**全225銘柄**に拡張するには、日経公式やJPXからダウンロードした構成銘柄CSVを
変換ツールに通してください（Webスクレイピングせず手元のCSVを変換するだけ）:

```bash
python tools/build_universe.py 公式構成銘柄.csv -o data/universe/nikkei225.csv
```

> ⚠️ **センチメントは銘柄選定には使いません。** 選定はファンダメンタル（割安・高収益・
> 健全性）で行い、センチメントはあくまで「いつ買うか」のタイミング補正に使います。
> ニュースの“話題性”で銘柄を拾うと、急騰後や仕手銘柄を掴むリスクが高いためです。

## 戦略ロジックの概要

総合スコア（-1.0〜+1.0）= テクニカルスコア ×(1 − w) + センチメント ×w
（`w` = `sentiment.weight`）

- 新規買い: 総合スコア ≥ `buy_score_threshold` **かつ** ファンダ足切り通過
- 売り: 総合スコア ≤ `sell_score_threshold`（保有の損切り/利確も別途判定）
- 株数: 口座評価額 × `position_pct` を 100株単位で配分

しきい値・指標パラメータ・ユニバースはすべて `config.yaml` で調整できます。

## 今後の拡張案

- X(Twitter)/掲示板コネクタを `data/news.py` の共通形式で追加
- 機械学習によるシグナル重みの最適化、ウォークフォワード検証
- 約定スリッページ・板気配を考慮した発注ロジック
- 銘柄ごとのポジションサイジング（ボラティリティ/ATRベース）

## ライセンス

MIT
