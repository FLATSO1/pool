"""ポートフォリオのリスク管理（損切り・利確の判定）。"""

from __future__ import annotations

from dataclasses import dataclass

from .broker.base import Position
from .config import TradingConfig


@dataclass
class RiskExit:
    ticker: str
    quantity: int
    reason: str          # "stop_loss" | "take_profit" | "trailing_stop"
    pnl_pct: float


def check_risk_exits(
    positions: dict[str, Position],
    prices: dict[str, float],
    cfg: TradingConfig,
    peaks: dict[str, float] | None = None,
) -> list[RiskExit]:
    """保有ポジションを損切り/利確/トレイリングストップで点検し、決済対象を返す。

    peaks: 建玉以降の高値（ティッカー→価格）。トレイリングストップに使う。
    """
    exits: list[RiskExit] = []
    for ticker, pos in positions.items():
        px = prices.get(ticker)
        if px is None or pos.avg_price <= 0:
            continue
        pnl_pct = (px - pos.avg_price) / pos.avg_price

        if cfg.stop_loss_pct > 0 and pnl_pct <= -cfg.stop_loss_pct:
            exits.append(RiskExit(ticker, pos.quantity, "stop_loss", pnl_pct))
        elif cfg.take_profit_pct > 0 and pnl_pct >= cfg.take_profit_pct:
            exits.append(RiskExit(ticker, pos.quantity, "take_profit", pnl_pct))
        elif cfg.trailing_stop_pct > 0 and peaks is not None:
            peak = peaks.get(ticker, pos.avg_price)
            if peak > 0 and px <= peak * (1 - cfg.trailing_stop_pct):
                exits.append(
                    RiskExit(ticker, pos.quantity, "trailing_stop", pnl_pct)
                )
    return exits


def update_peaks(
    peaks: dict[str, float],
    positions: dict[str, Position],
    prices: dict[str, float],
) -> dict[str, float]:
    """保有銘柄の高値を更新し、保有していない銘柄は除去して返す。"""
    updated: dict[str, float] = {}
    for ticker, pos in positions.items():
        px = prices.get(ticker)
        prev = peaks.get(ticker, pos.avg_price)
        updated[ticker] = max(prev, px) if px is not None else prev
    return updated


def can_open_new(positions: dict[str, Position], cfg: TradingConfig) -> bool:
    """新規ポジションを開ける余地があるか（同時保有数の上限）。"""
    return len(positions) < cfg.max_positions
