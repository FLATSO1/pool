# Windows での自動運用セットアップ

働きながらでも「毎朝レポート → 日中は自動売買 → 引け後レポート」を**営業日だけ**
自動で回すための手順です。スマホ通知（Discord/Telegram）と安全ガードを併用します。

> ⚠️ いきなり実弾・完全自動にしないこと。**まずペーパーで自動運転＋通知**を数週間
> 試し、納得してから実弾に進んでください。

---

## 1. 前提のインストール

1. **Python 3.10+** … <https://www.python.org/> からインストール（「Add Python to PATH」にチェック）
2. **Git** … <https://git-scm.com/>
3. （実弾のみ）**kabuステーション** … 三菱UFJ eスマート証券（旧auカブコム）で口座開設・利用申込後にインストール

## 2. リポジトリの取得とセットアップ

PowerShell（またはコマンドプロンプト）で：

```powershell
git clone https://github.com/flatso1/pool.git
cd pool

python -m venv .venv
.venv\Scripts\Activate.ps1        # cmdなら .venv\Scripts\activate.bat

pip install -e ".[dev]"
pip install jpholiday              # 祝日判定（推奨）

copy config.example.yaml config.yaml
copy .env.example .env
```

## 3. 設定

- **config.yaml** … ユニバース・しきい値・`safety`（損失上限など）・`notify.channel` を調整
- **.env** … 必要なものだけ記入
  - `ANTHROPIC_API_KEY`（センチメント/アドバイザー。無くても動く）
  - `DISCORD_WEBHOOK_URL`（または `TELEGRAM_BOT_TOKEN` ＋ `TELEGRAM_CHAT_ID`）
  - 実弾時のみ：`KABUS_API_PASSWORD` / `KABUS_TRADE_PASSWORD` / `AUTOTRADER_ENABLE_LIVE=true`

### スマホ通知の準備（どちらか）

- **Discord**: サーバー設定 → 連携サービス → ウェブフックを作成し URL を `DISCORD_WEBHOOK_URL` に
- **Telegram**: @BotFather でBot作成 → トークンを `TELEGRAM_BOT_TOKEN`、自分の chat_id を `TELEGRAM_CHAT_ID` に

## 4. 動作確認（手動）

```powershell
autotrader is-trading-day     # 取引日か
autotrader backtest           # 過去検証（本物の株価）
autotrader report             # 通知が届くか確認
autotrader run --dry-run      # 何を売買するかだけ表示
```

実弾接続を確認するなら（kabuステーション起動中に）：

```powershell
autotrader kabus-check
```

## 5. タスクスケジューラで自動実行

同梱の `scripts\windows\autotrader_task.bat` を使います。これは
**非取引日（土日・祝日・年末年始）なら自動でスキップ**し、`logs\autotrader.log` に記録します。

### 登録するタスク（東証 9:00–15:30 を想定）

| タスク名 | トリガー | 操作の引数 |
|---|---|---|
| autotrader-朝レポート | 毎日 08:30 | `report` |
| autotrader-場中サイクル | 毎日 09:00〜15:00 を30分ごとに繰り返し | `run` |
| autotrader-引けレポート | 毎日 15:40 | `report` |

### 登録手順（「場中サイクル」の例）

1. **タスクスケジューラ** を開く →「タスクの作成」
2. **全般**: 名前「autotrader-場中サイクル」。「ユーザーがログオンしているかどうかにかかわらず実行する」を選択
3. **トリガー** → 新規:
   - 「毎日」09:00 開始
   - 「詳細設定」で **繰り返し間隔 30分 / 継続時間 6時間**
4. **操作** → 新規:
   - プログラム: `C:\path\to\pool\scripts\windows\autotrader_task.bat`
   - 引数の追加: `run`
   - 開始（オプション）: `C:\path\to\pool`
5. **条件**: 「コンピューターをスリープ解除してタスクを実行する」にチェック
6. 同様に 08:30 `report` と 15:40 `report` のタスクも作成

> PowerShell版を使う場合は、プログラムを `powershell.exe`、引数を
> `-ExecutionPolicy Bypass -File "C:\path\to\pool\scripts\windows\Invoke-Autotrader.ps1" -Command run`
> にします。

## 6. PCのスリープ対策

自分のPCで運用する場合、**スリープ/シャットダウン中は取引できません**。
- 電源オプションで立会時間中はスリープしない設定に
- 安定した有線ネット推奨
- これが負担なら **Windows VPS** への移行を検討（24時間安定）

## 7. 緊急停止（スマホから）

`data\state\HALT` というファイルを置くと、**新規買いが止まります**（保有の損切り/利確は動く）。
この `data\state` フォルダを **GoogleドライブやDropboxの同期フォルダ**にしておけば、
外出先からスマホでファイルを作るだけで停止できます。再開はファイルを削除するだけ。

## 8. 段階移行（強く推奨）

1. **ペーパー＋自動＋通知** を数週間（`trading.mode: paper`）
2. **propose / execute の承認つき実弾**（朝だけ承認）
3. 信頼できたら **少額・少銘柄で完全自動 `run`**（`mode: live` ＋ `AUTOTRADER_ENABLE_LIVE=true`）

## トラブルシュート

- `autotrader` が見つからない → 仮想環境を有効化（`.venv\Scripts\activate.bat`）したか確認
- 通知が来ない → `.env` の Webhook/トークン、`config.yaml` の `notify.channel` を確認
- 実弾が動かない → kabuステーションが起動中か、`autotrader kabus-check` で切り分け
- 実行ログ → `logs\autotrader.log`
