# autotrader — 日本株 自動売買アプリ

ファンダメンタルで銘柄を選定し、テクニカルで売買タイミングを判定、
ニュース/SNSのセンチメントでマクロ視点を反映して、ペーパートレード
または実弾（auカブコム証券 kabuステーションAPI）で発注する Python アプリです。

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
```

> モジュールとして実行する場合は `python -m autotrader.cli <command>`。

### ライブ発注（実弾）への切替

1. Windows で **kabuステーション** を起動し、API設定でパスワードを発行
2. `.env` に `KABUS_API_PASSWORD` と `KABUS_TRADE_PASSWORD` を設定
3. `config.yaml` の `trading.mode` を `live` に
4. `.env` で `AUTOTRADER_ENABLE_LIVE=true`（この二重ガードを通さない限りペーパーで動作）

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
