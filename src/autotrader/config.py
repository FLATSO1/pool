"""設定の読み込みと型付け。

YAMLファイル＋環境変数（.env）からアプリ全体の設定を組み立てる。
秘密情報（APIキー・パスワード）は環境変数からのみ読み、YAMLには置かない。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml


def _load_dotenv() -> None:
    """.env があれば読み込む（python-dotenv は任意依存）。"""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


@dataclass
class FundamentalConfig:
    min_score: float = 0.5
    max_per: float = 30.0
    min_roe: float = 0.08
    max_debt_to_equity: float = 2.0


# テクニカル各シグナルの既定の重み（加重平均の係数。0で無効化）。
# config.yaml の technical.weights で個別に上書きできる。
DEFAULT_WEIGHTS: dict[str, float] = {
    "trend": 1.0,            # 短期SMA vs 長期SMA の位置
    "cross": 0.5,           # ゴールデン/デッドクロス
    "macd": 0.5,            # MACDヒストグラム
    "rsi": 0.3,             # RSI 売られ/買われすぎ
    "bb": 0.3,              # ボリンジャーバンド ±2σ
    "vol": 0.5,             # 出来高ブレイク
    "ichimoku_cloud": 0.7,  # 一目: 雲の上/下
    "ichimoku_triple": 0.6, # 一目: 三役好転/逆転
    "perfect_order": 0.7,   # パーフェクトオーダー
    "candlestick": 0.4,     # ローソク足パターン
    "stoch": 0.3,           # ストキャスティクス
    "adx": 0.5,             # DMI/ADX
    "divergence": 0.4,      # ダイバージェンス
}


@dataclass
class TechnicalConfig:
    sma_short: int = 25
    sma_mid: int = 50
    sma_long: int = 75
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    atr_period: int = 14
    # ボリンジャーバンド
    bb_window: int = 20
    bb_std: float = 2.0
    # 出来高ブレイク
    vol_ma_window: int = 20
    vol_mult: float = 1.5
    breakout_window: int = 20
    # 一目均衡表
    ichimoku_tenkan: int = 9
    ichimoku_kijun: int = 26
    ichimoku_senkou_b: int = 52
    ichimoku_shift: int = 26
    # ストキャスティクス
    stoch_k: int = 14
    stoch_d: int = 3
    stoch_smooth: int = 3
    stoch_oversold: float = 20.0
    stoch_overbought: float = 80.0
    # DMI / ADX
    adx_period: int = 14
    adx_threshold: float = 25.0
    # ダイバージェンス（価格とRSIの逆行）の参照期間
    divergence_lookback: int = 14
    # 各シグナルの重み（DEFAULT_WEIGHTS を上書き）
    weights: dict = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))


@dataclass
class SentimentConfig:
    enabled: bool = True
    model: str = "claude-opus-4-8"
    lookback_days: int = 7
    max_headlines: int = 15
    weight: float = 0.3


@dataclass
class NotifyConfig:
    """売買・アラート・サマリの通知設定（秘密情報は環境変数から）。"""

    enabled: bool = True
    channel: str = "discord"  # "discord" | "telegram" | "console"


@dataclass
class SafetyConfig:
    """完全自動運用の安全ガード（暴走防止）。"""

    daily_loss_limit_pct: float = 0.03      # 当日-3%で新規買い停止
    max_trades_per_day: int = 10            # 1日の最大約定数
    max_new_positions_per_day: int = 3      # 1日の最大新規建て数


@dataclass
class AdvisorConfig:
    """Claudeを「提案レビュー＋地合い判定」のアドバイザーとして使う設定。"""

    enabled: bool = True
    model: str = "claude-opus-4-8"
    regime_enabled: bool = True          # 地合いゲートを使うか
    risk_off_block_buys: bool = True     # 地合いrisk_off時に新規買いを止める
    skip_blocks_buy: bool = True         # アドバイザーが skip と判断したら買わない


@dataclass
class TradingConfig:
    mode: str = "paper"  # "paper" | "live"
    exchange: int = 1
    cash: float = 1_000_000.0
    max_positions: int = 5
    position_pct: float = 0.2
    stop_loss_pct: float = 0.07
    take_profit_pct: float = 0.15
    buy_score_threshold: float = 0.6
    sell_score_threshold: float = -0.3


@dataclass
class BacktestConfig:
    start: str = "2022-01-01"
    end: str = "2024-12-31"
    commission_pct: float = 0.0005


@dataclass
class Secrets:
    """環境変数からのみ読み込む秘密情報。"""

    anthropic_api_key: str | None = None
    kabus_api_password: str | None = None
    kabus_base_url: str = "http://localhost:18080/kabusapi"
    enable_live: bool = False
    discord_webhook_url: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    @classmethod
    def from_env(cls) -> "Secrets":
        _load_dotenv()
        return cls(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            kabus_api_password=os.getenv("KABUS_API_PASSWORD"),
            kabus_base_url=os.getenv("KABUS_BASE_URL", cls.kabus_base_url),
            enable_live=os.getenv("AUTOTRADER_ENABLE_LIVE", "false").lower()
            in ("1", "true", "yes"),
            discord_webhook_url=os.getenv("DISCORD_WEBHOOK_URL"),
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID"),
        )


@dataclass
class Config:
    universe: list[str] = field(default_factory=list)
    universe_source: str = "manual"  # "manual"(下のリスト) | "file"(CSVを読む)
    universe_file: str = "data/universe/nikkei225.csv"
    fundamental: FundamentalConfig = field(default_factory=FundamentalConfig)
    technical: TechnicalConfig = field(default_factory=TechnicalConfig)
    sentiment: SentimentConfig = field(default_factory=SentimentConfig)
    advisor: AdvisorConfig = field(default_factory=AdvisorConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    secrets: Secrets = field(default_factory=Secrets.from_env)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        """YAMLから設定を読む。path未指定なら ./config.yaml → config.example.yaml の順に探す。"""
        raw: dict[str, Any] = {}
        candidate = _resolve_config_path(path)
        if candidate is not None:
            with open(candidate, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}

        technical = _build(TechnicalConfig, raw.get("technical"))
        # 部分指定された重みは既定値にマージ（未指定キーは既定のまま）
        merged = dict(DEFAULT_WEIGHTS)
        merged.update(technical.weights or {})
        technical.weights = merged

        return cls(
            universe=list(raw.get("universe", [])),
            universe_source=raw.get("universe_source", "manual"),
            universe_file=raw.get("universe_file", cls.universe_file),
            fundamental=_build(FundamentalConfig, raw.get("fundamental")),
            technical=technical,
            sentiment=_build(SentimentConfig, raw.get("sentiment")),
            advisor=_build(AdvisorConfig, raw.get("advisor")),
            notify=_build(NotifyConfig, raw.get("notify")),
            safety=_build(SafetyConfig, raw.get("safety")),
            trading=_build(TradingConfig, raw.get("trading")),
            backtest=_build(BacktestConfig, raw.get("backtest")),
            secrets=Secrets.from_env(),
        )

    def live_enabled(self) -> bool:
        """ライブ発注が実際に許可されているか（モード＝live かつ 環境変数で明示有効）。"""
        return self.trading.mode == "live" and self.secrets.enable_live


def _resolve_config_path(path: str | Path | None) -> Path | None:
    if path is not None:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"設定ファイルが見つかりません: {p}")
        return p
    for name in ("config.yaml", "config.example.yaml"):
        p = Path(name)
        if p.exists():
            return p
    return None


def _build(cls: type, data: Any):
    """dict から dataclass を構築（未知キーは無視、欠損キーはデフォルト）。"""
    if not data:
        return cls()
    allowed = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in allowed})
