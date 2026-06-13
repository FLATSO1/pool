"""ブローカー共通インターフェースとデータ型。

ペーパートレードもライブ（kabuステーション）も同じ Broker インターフェースを
実装するので、戦略エンジンは発注先を意識しなくてよい。
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from enum import Enum


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass
class Order:
    ticker: str          # 例: "7203.T"
    side: Side
    quantity: int        # 株数（日本株は通常100株単位）
    limit_price: float | None = None  # None=成行


@dataclass
class OrderResult:
    ok: bool
    order_id: str = ""
    filled_price: float | None = None
    message: str = ""


@dataclass
class Position:
    ticker: str
    quantity: int
    avg_price: float

    def market_value(self, price: float) -> float:
        return self.quantity * price

    def unrealized_pnl(self, price: float) -> float:
        return (price - self.avg_price) * self.quantity


@dataclass
class AccountSnapshot:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)

    def equity(self, prices: dict[str, float]) -> float:
        """現金＋保有評価額。"""
        total = self.cash
        for t, pos in self.positions.items():
            px = prices.get(t)
            if px is not None:
                total += pos.market_value(px)
        return total


class Broker(abc.ABC):
    """発注・口座照会の抽象基底。"""

    @abc.abstractmethod
    def submit(self, order: Order) -> OrderResult:
        ...

    @abc.abstractmethod
    def positions(self) -> dict[str, Position]:
        ...

    @abc.abstractmethod
    def cash(self) -> float:
        ...

    @abc.abstractmethod
    def snapshot(self) -> AccountSnapshot:
        ...
