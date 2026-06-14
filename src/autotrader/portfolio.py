"""ポートフォリオのリスク管理（損切り・利確の判定）。"""

from __future__ import annotations

from dataclasses import dataclass

from .broker.base import Position
from .config import TradingConfig


@dataclass
class RiskExit:
    ticker: str
    quantity: int
    reason: str          # "stop_loss" | "take_profit"
    pnl_pct: float


def check_risk_exits(
    positions: dict[str, Position],
    prices: dict[str, float],
    cfg: TradingConfig,
) -> list[RiskExit]:
    """保有ポジションを損切り/利確ルールで点検し、決済すべきものを返す。"""
    exits: list[RiskExit] = []
    for ticker, pos in positions.items():
        px = prices.get(ticker)
        if px is None or pos.avg_price <= 0:
            continue
        pnl_pct = (px - pos.avg_price) / pos.avg_price
        if pnl_pct <= -cfg.stop_loss_pct:
            exits.append(RiskExit(ticker, pos.quantity, "stop_loss", pnl_pct))
        elif pnl_pct >= cfg.take_profit_pct:
            exits.append(RiskExit(ticker, pos.quantity, "take_profit", pnl_pct))
    return exits


def can_open_new(positions: dict[str, Position], cfg: TradingConfig) -> bool:
    """新規ポジションを開ける余地があるか（同時保有数の上限）。"""
    return len(positions) < cfg.max_positions
