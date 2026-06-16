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
- **テクニカル解析** — 移動平均クロス・MACD・RSI・ボリンジャーバンド・出来高ブレイク・
  一目均衡表・パーフェクトオーダー・ストキャスティクス・DMI/ADX・ダイバージェンス・
  ローソク足パターン（酒田五法）を加重統合（TA-Lib不要、pandasのみ）
- **センチメント** — Claude API（`claude-opus-4-8`）でニュース/SNS見出しを解析。
  APIキーが無い場合は辞書ベースに自動フォールバック
- **承認フロー＋Claudeアドバイザー** — `propose` で売買候補を根拠つきで提示
  （Claudeが各候補を go/caution/skip でレビュー＋リスク指摘、市場全体の地合いも判定）、
  `execute` で承認した分だけ発注。お金を動かす判断は決定論エンジンが担い、Claudeは助言役
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

# 3b) シグナル別バックテスト（どのテクニカルが効くかを比較）
autotrader eval-signals

# 4) 1サイクル評価して発注（既定はペーパー）。判断だけ見るなら --dry-run
autotrader run --dry-run
autotrader run

# 4b) 承認フロー: 根拠つきで提案 → 確認 → 承認した分だけ発注
autotrader propose                 # 候補を提示し proposals.json に保存（発注しない）
autotrader execute                 # 1件ずつ y/N で承認して発注
autotrader execute --only 7203.T   # 特定銘柄だけ
autotrader execute --yes           # 全提案を一括発注

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

### 現物 / 信用とレバレッジ上限

`config.yaml` の `trading` で取引区分を選べます。

```yaml
trading:
  trade_type: "cash"        # "cash"=現物 / "margin"=信用
  margin_trade_type: "day"  # 信用種別: "system"=制度 / "general"=一般(長期) / "day"=一般(デイトレ)
  max_leverage: 1.0         # 建玉合計 ≤ 評価額×この倍率（1.0=建玉≤余力＝レバ1倍）
```

- **信用でも `max_leverage: 1.0`** にしておけば、建玉の合計が口座評価額を超える
  新規買いを自動で見送るため、**追証リスクを実質ゼロ**に保てます（回転売買の利点だけ取る）。
- 買い=新規建て、売り=返済として発注します（本アプリは買って→売って決済する建玉のみ扱う）。
- レバレッジ上限は **ペーパー／バックテスト／ライブ共通**で効きます。`0` 以下でガード無効。

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

### シグナルの重み付けと有効性検証

各テクニカルシグナルの重みは `config.yaml` の `technical.weights` で調整できます
（`0` で無効化）。どのシグナルが効くかは **シグナル別バックテスト** で測れます:

```bash
autotrader eval-signals
```

各シグナルを単独で使ったときのリターン・最大DD・シャープ・勝率・売買回数を
一覧表示します。出力例（合成データ）:

```
シグナル              リターン     最大DD   ｼｬｰﾌﾟ    勝率   回数
ALL(既定重み)            69.4%     -8.2%    5.45    74%    57
perfect_order           57.2%     -6.1%    5.18    89%    38
trend                   55.7%     -6.4%    4.99    89%    39
...
divergence             -17.6%    -19.0%   -3.53     7%    29
```

→ 上位（効いた）シグナルを重く、下位を軽く/無効にして再検証、という
ワークフローで戦略を磨けます。

## 承認フローとClaudeアドバイザー

実弾でいきなり自動発注するのではなく、「**提案 → あなたが確認 → 承認した分だけ発注**」
の流れにできます。

```
autotrader propose
   │  ・地合い判定（Claudeが市場全体のニュースから risk_on/neutral/risk_off）
   │  ・各買い候補をClaudeがレビュー（go/caution/skip・確信度・リスク・平易な説明）
   │  ・proposals.json に保存（この時点では発注しない）
   ▼
（あなたが内容を確認）
   ▼
autotrader execute        # 1件ずつ y/N、または --only / --yes
```

**設計思想**: お金を動かす最終ロジックは決定論的な指標（テスト可能・再現可能）が担い、
Claudeはその上の「レビュー・説明・地合い判断」に徹します。LLMに直接トレードを
決めさせない（ハルシネーション・非再現性の回避）ことで、精度と安全性を両立します。

`advisor.enabled: false` でClaudeレビューを切れば、決定論のみの提案になります。
APIキーが無い場合はスコアベースのフォールバックで動作します。

## 完全自動運用（日中いなくても回す）

仕事中などPCの前にいられない人向けに、「**自動で売買 → スマホに通知 → 安全ガードで暴走防止**」
の運用ができます。

```
autotrader run        # 1サイクル: 評価→発注→スマホ通知（タスクスケジューラで定期実行）
autotrader report     # ポートフォリオ状況をスマホに通知（場の開始/引け後に）
```

**スマホ通知（Discord / Telegram）**
`.env` に `DISCORD_WEBHOOK_URL`（または `TELEGRAM_BOT_TOKEN`＋`TELEGRAM_CHAT_ID`）を
設定すると、売買・アラート・サイクルサマリがスマホにプッシュで届きます。未設定なら
コンソール出力にフォールバック。

**安全ガード（`config.yaml` の `safety`）**
完全自動でも事故らないよう、放置運用に歯止めをかけます。
- `daily_loss_limit_pct`: 当日この損失に達したら新規買いを停止
- `max_trades_per_day` / `max_new_positions_per_day`: 1日の取引・新規建ての上限
- **緊急停止**: `data/state/HALT` ファイルを置くと新規買いが止まる
  （クラウドストレージ同期フォルダに置けば**スマホからでも停止**できる）

日次の状態（当日の取引数・開始時資産）は `data/state/daily.json` に保存され、
タスクスケジューラで `run` を1日に複数回実行しても上限が正しく累積します。

> 運用の段階移行を推奨：①ペーパーで自動運転＋通知 → ②propose/execute の承認つき実弾
> → ③少額で完全自動 `run`。いきなり全自動・実弾にしないこと。

### Windowsで自動実行する

東証の**取引日だけ**「朝レポート → 場中サイクル → 引けレポート」を自動実行する
スクリプトと手順を同梱しています。

- `scripts/windows/autotrader_task.bat`（または `Invoke-Autotrader.ps1`）—
  非取引日（土日・祝日・年末年始）は自動スキップ。タスクスケジューラに登録して使う
- `autotrader is-trading-day` — 取引日判定（取引日=終了コード0 / 非取引日=1）
- 祝日判定には `pip install jpholiday`（未導入でも土日・年末年始は判定）

セットアップの詳細は **[docs/windows.md](docs/windows.md)** を参照。

## 今後の拡張案

- X(Twitter)/掲示板コネクタを `data/news.py` の共通形式で追加
- 機械学習によるシグナル重みの最適化、ウォークフォワード検証
- 約定スリッページ・板気配を考慮した発注ロジック
- 銘柄ごとのポジションサイジング（ボラティリティ/ATRベース）

## ライセンス

MIT
