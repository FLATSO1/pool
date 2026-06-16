"""ポートフォリオのリスク管理（損切り・利確の判定）。"""

from __future__ import annotations

from dataclasses import dataclass

from .broker.base import Position
from .config import TradingConfig


@dataclass
class RiskExit:
    ticker: str
    quantity: int
    # "stop_loss" | "stop_loss_atr" | "take_profit" | "trailing_stop"
    reason: str
    pnl_pct: float


def _valid_atr(v) -> bool:
    return v is not None and v > 0 and v == v  # NaN除外


def check_risk_exits(
    positions: dict[str, Position],
    prices: dict[str, float],
    cfg: TradingConfig,
    peaks: dict[str, float] | None = None,
    atrs: dict[str, float] | None = None,
) -> list[RiskExit]:
    """保有ポジションを損切り/利確/トレイリングで点検し、決済対象を返す。

    peaks: 建玉以降の高値（トレイリング用）。
    atrs:  各銘柄のATR（ATRベース損切り用）。stop_loss_atr_mult>0かつATRがあれば
           「建値 − N×ATR」を損切り線とし、固定%より優先する。
    """
    exits: list[RiskExit] = []
    for ticker, pos in positions.items():
        px = prices.get(ticker)
        if px is None or pos.avg_price <= 0:
            continue
        pnl_pct = (px - pos.avg_price) / pos.avg_price
        reason: str | None = None

        # 1) 損切り（ATR優先、無ければ固定%）
        atr_val = atrs.get(ticker) if atrs else None
        if cfg.stop_loss_atr_mult > 0 and _valid_atr(atr_val):
            if px <= pos.avg_price - cfg.stop_loss_atr_mult * atr_val:
                reason = "stop_loss_atr"
        elif cfg.stop_loss_pct > 0 and pnl_pct <= -cfg.stop_loss_pct:
            reason = "stop_loss"

        # 2) 利確
        if reason is None and cfg.take_profit_pct > 0 and pnl_pct >= cfg.take_profit_pct:
            reason = "take_profit"

        # 3) トレイリングストップ
        if reason is None and cfg.trailing_stop_pct > 0 and peaks is not None:
            peak = peaks.get(ticker, pos.avg_price)
            if peak > 0 and px <= peak * (1 - cfg.trailing_stop_pct):
                reason = "trailing_stop"

        if reason is not None:
            exits.append(RiskExit(ticker, pos.quantity, reason, pnl_pct))
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


def total_exposure(
    positions: dict[str, Position], prices: dict[str, float]
) -> float:
    """保有建玉の時価合計（株数×現在値。現在値が無ければ建値で代用）。"""
    total = 0.0
    for ticker, pos in positions.items():
        px = prices.get(ticker)
        total += pos.quantity * (px if px is not None else pos.avg_price)
    return total


def within_leverage(
    new_cost: float,
    positions: dict[str, Position],
    prices: dict[str, float],
    equity: float,
    cfg: TradingConfig,
) -> bool:
    """新規建て（コスト=new_cost）が許容レバレッジ内に収まるか。

    「建玉合計（新規を含む） ≤ 評価額 × max_leverage」を満たすとき True。
    max_leverage<=0 ならガード無効で常に True。

    例: max_leverage=1.0 なら、建玉の時価合計が口座評価額を超える新規買いを
    ブロックする（＝レバレッジ1倍上限。信用でも追証リスクを実質ゼロに保つ）。
    """
    if cfg.max_leverage <= 0:
        return True
    projected = total_exposure(positions, prices) + max(0.0, new_cost)
    # 浮動小数の誤差を吸収する微小マージン
    return projected <= equity * cfg.max_leverage + 1e-6
