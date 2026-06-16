"""レバレッジ・ガード（建玉合計 ≤ 評価額×max_leverage）のテスト。"""

from __future__ import annotations

from autotrader.broker.base import Position
from autotrader.config import TradingConfig
from autotrader.portfolio import total_exposure, within_leverage


def _pos(ticker: str, qty: int, price: float) -> Position:
    return Position(ticker, qty, price)


def test_total_exposure_uses_current_price_then_avg():
    positions = {"7203.T": _pos("7203.T", 100, 2000.0)}
    # 現在値があればそれを使う
    assert total_exposure(positions, {"7203.T": 2500.0}) == 250_000.0
    # 現在値が無ければ建値で代用
    assert total_exposure(positions, {}) == 200_000.0


def test_within_leverage_blocks_above_equity_at_1x():
    cfg = TradingConfig(max_leverage=1.0)
    positions: dict[str, Position] = {}
    prices: dict[str, float] = {}
    equity = 1_000_000.0
    # 余力ちょうどはOK
    assert within_leverage(1_000_000.0, positions, prices, equity, cfg)
    # 余力を1円でも超えたらブロック
    assert not within_leverage(1_000_001.0, positions, prices, equity, cfg)


def test_within_leverage_counts_existing_positions():
    cfg = TradingConfig(max_leverage=1.0)
    positions = {"7203.T": _pos("7203.T", 100, 8000.0)}  # 建玉 80万円
    prices = {"7203.T": 8000.0}
    equity = 1_000_000.0
    # 既存80万 + 新規20万 = 100万 ≤ 100万 → OK
    assert within_leverage(200_000.0, positions, prices, equity, cfg)
    # 既存80万 + 新規25万 = 105万 > 100万 → ブロック
    assert not within_leverage(250_000.0, positions, prices, equity, cfg)


def test_within_leverage_allows_2x_when_configured():
    cfg = TradingConfig(max_leverage=2.0)
    equity = 1_000_000.0
    assert within_leverage(2_000_000.0, {}, {}, equity, cfg)
    assert not within_leverage(2_000_001.0, {}, {}, equity, cfg)


def test_within_leverage_disabled_when_non_positive():
    cfg = TradingConfig(max_leverage=0.0)
    # ガード無効: いくらでも通る
    assert within_leverage(10_000_000.0, {}, {}, 1.0, cfg)
