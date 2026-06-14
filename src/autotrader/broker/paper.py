"""ペーパートレード（仮想売買）ブローカー。

口座状態（現金・ポジション）をJSONに永続化する。発注は与えられた
参照価格で即時約定したものとして扱う簡易モデル。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..logging_setup import get_logger
from .base import AccountSnapshot, Broker, Order, OrderResult, Position, Side

log = get_logger(__name__)


class PaperBroker(Broker):
    def __init__(
        self,
        cash: float = 1_000_000.0,
        state_path: str | Path | None = "data/state/paper_account.json",
        price_provider=None,
    ):
        """price_provider: ticker -> float を返す呼び出し可能オブジェクト。

        成行注文の約定価格を解決するために使う（None の場合は limit_price 必須）。
        """
        self._cash = cash
        self._positions: dict[str, Position] = {}
        self._state_path = Path(state_path) if state_path else None
        self._price_provider = price_provider
        self._load()

    # --- Broker インターフェース ---

    def submit(self, order: Order) -> OrderResult:
        price = order.limit_price
        if price is None and self._price_provider is not None:
            price = self._price_provider(order.ticker)
        if price is None:
            return OrderResult(False, message="約定価格を解決できません")

        cost = price * order.quantity
        if order.side == Side.BUY:
            if cost > self._cash:
                return OrderResult(
                    False, message=f"資金不足: 必要{cost:.0f}円 / 残高{self._cash:.0f}円"
                )
            self._apply_buy(order.ticker, order.quantity, price)
            self._cash -= cost
        else:  # SELL
            pos = self._positions.get(order.ticker)
            if pos is None or pos.quantity < order.quantity:
                held = pos.quantity if pos else 0
                return OrderResult(
                    False, message=f"保有不足: 売却{order.quantity} / 保有{held}"
                )
            self._apply_sell(order.ticker, order.quantity)
            self._cash += cost

        self._save()
        return OrderResult(
            True,
            order_id=f"paper-{order.ticker}-{order.side.value}",
            filled_price=price,
            message="約定（ペーパー）",
        )

    def positions(self) -> dict[str, Position]:
        return dict(self._positions)

    def cash(self) -> float:
        return self._cash

    def snapshot(self) -> AccountSnapshot:
        return AccountSnapshot(cash=self._cash, positions=dict(self._positions))

    # --- 内部 ---

    def _apply_buy(self, ticker: str, qty: int, price: float) -> None:
        pos = self._positions.get(ticker)
        if pos is None:
            self._positions[ticker] = Position(ticker, qty, price)
        else:
            total_qty = pos.quantity + qty
            pos.avg_price = (pos.avg_price * pos.quantity + price * qty) / total_qty
            pos.quantity = total_qty

    def _apply_sell(self, ticker: str, qty: int) -> None:
        pos = self._positions[ticker]
        pos.quantity -= qty
        if pos.quantity <= 0:
            del self._positions[ticker]

    def _load(self) -> None:
        if not self._state_path or not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            self._cash = data["cash"]
            self._positions = {
                t: Position(t, p["quantity"], p["avg_price"])
                for t, p in data.get("positions", {}).items()
            }
            log.info("ペーパー口座を復元: 現金%.0f円, 保有%d銘柄",
                     self._cash, len(self._positions))
        except (json.JSONDecodeError, KeyError) as exc:
            log.warning("ペーパー口座の読込に失敗（初期化します）: %s", exc)

    def _save(self) -> None:
        if not self._state_path:
            return
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "cash": self._cash,
            "positions": {
                t: {"quantity": p.quantity, "avg_price": p.avg_price}
                for t, p in self._positions.items()
            },
        }
        self._state_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
