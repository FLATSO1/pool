"""入口需給判定（1分足・板）のテスト。"""

from __future__ import annotations

import pandas as pd

from autotrader.analysis.orderflow import board_imbalance, intraday_pressure


def _bars(rows):
    idx = pd.date_range("2024-01-01 09:00", periods=len(rows), freq="min")
    return pd.DataFrame(
        rows, columns=["open", "high", "low", "close", "volume"], index=idx
    )


def test_intraday_buy_pressure_from_volume():
    # 上昇足の出来高が多い → 買い圧
    df = _bars([
        (100, 101, 99, 101, 1000),   # 陽線・大商い
        (101, 102, 100, 100, 200),   # 陰線・小商い
        (100, 103, 100, 103, 1500),  # 陽線・大商い
    ])
    r = intraday_pressure(df)
    assert r is not None and r.label == "buy"
    assert r.buy_ratio > 0.55


def test_intraday_sell_pressure():
    df = _bars([
        (100, 100.5, 98, 98, 1500),  # 陰線・大商い
        (98, 99, 97, 99, 200),       # 陽線・小商い
        (99, 99.5, 96, 96, 1200),    # 陰線・大商い
    ])
    r = intraday_pressure(df)
    assert r is not None and r.label == "sell"
    assert r.buy_ratio < 0.45


def test_intraday_empty_returns_none():
    assert intraday_pressure(pd.DataFrame()) is None


def test_board_imbalance_buy_side_thick():
    board = {
        "Buy1": {"Price": 1000, "Qty": 8000},
        "Buy2": {"Price": 999, "Qty": 5000},
        "Sell1": {"Price": 1001, "Qty": 1000},
        "Sell2": {"Price": 1002, "Qty": 2000},
    }
    r = board_imbalance(board)
    assert r is not None and r.label == "buy"
    assert r.buy_ratio > 0.55


def test_board_imbalance_fallback_totals():
    # 各気配が無くても総量フィールドで算出
    board = {"UnderBuyQty": 3000, "OverSellQty": 7000}
    r = board_imbalance(board)
    assert r is not None and r.label == "sell"
    assert abs(r.buy_ratio - 0.3) < 1e-6


def test_board_none():
    assert board_imbalance(None) is None
    assert board_imbalance({}) is None
