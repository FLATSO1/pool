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


@dataclass
class TechnicalConfig:
    sma_short: int = 25
    sma_long: int = 75
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    atr_period: int = 14


@dataclass
class SentimentConfig:
    enabled: bool = True
    model: str = "claude-opus-4-8"
    lookback_days: int = 7
    max_headlines: int = 15
    weight: float = 0.3


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

    @classmethod
    def from_env(cls) -> "Secrets":
        _load_dotenv()
        return cls(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            kabus_api_password=os.getenv("KABUS_API_PASSWORD"),
            kabus_base_url=os.getenv("KABUS_BASE_URL", cls.kabus_base_url),
            enable_live=os.getenv("AUTOTRADER_ENABLE_LIVE", "false").lower()
            in ("1", "true", "yes"),
        )


@dataclass
class Config:
    universe: list[str] = field(default_factory=list)
    fundamental: FundamentalConfig = field(default_factory=FundamentalConfig)
    technical: TechnicalConfig = field(default_factory=TechnicalConfig)
    sentiment: SentimentConfig = field(default_factory=SentimentConfig)
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

        return cls(
            universe=list(raw.get("universe", [])),
            fundamental=_build(FundamentalConfig, raw.get("fundamental")),
            technical=_build(TechnicalConfig, raw.get("technical")),
            sentiment=_build(SentimentConfig, raw.get("sentiment")),
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
