"""ローソク足パターン検出のテスト。"""

from __future__ import annotations

import pandas as pd

from autotrader.analysis import candlestick as cs


def _df(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    idx = pd.date_range("2023-01-01", periods=len(rows), freq="B")
    return pd.DataFrame(
        rows, columns=["open", "high", "low", "close"], index=idx
    )


def test_bullish_engulfing():
    # 前日陰線(100→98) を当日陽線(95→101)が包む
    df = _df([(105, 106, 103, 104), (100, 101, 97, 98), (95, 102, 94, 101)])
    p = cs.detect(df)
    assert bool(p["cdl_bull_engulfing"].iloc[-1])
    assert bool(cs.aggregate(p)["cdl_bull"].iloc[-1])


def test_bearish_engulfing():
    # 前日陽線(95→98) を当日陰線(99→94)が包む
    df = _df([(90, 92, 89, 91), (95, 99, 94, 98), (99, 100, 93, 94)])
    p = cs.detect(df)
    assert bool(p["cdl_bear_engulfing"].iloc[-1])
    assert bool(cs.aggregate(p)["cdl_bear"].iloc[-1])


def test_three_white_soldiers():
    df = _df(
        [(100, 103, 99, 102.5), (102, 105, 101, 104.5), (104, 107, 103, 106.5)]
    )
    p = cs.detect(df)
    assert bool(p["cdl_three_soldiers"].iloc[-1])


def test_three_black_crows():
    df = _df(
        [(106, 107, 103, 103.5), (104, 105, 101, 101.5), (102, 103, 99, 99.5)]
    )
    p = cs.detect(df)
    assert bool(p["cdl_three_crows"].iloc[-1])


def test_hammer_requires_downtrend():
    # 下ヒゲの長いハンマー形。下降トレンド文脈でのみ買いシグナルになる
    df = _df([(100, 100.5, 90, 99.5)])
    downtrend = pd.Series([True], index=df.index)
    flat = pd.Series([False], index=df.index)
    assert bool(cs.detect(df, downtrend=downtrend)["cdl_hammer"].iloc[-1])
    # トレンド文脈なし → 無効
    assert not bool(cs.detect(df, downtrend=flat)["cdl_hammer"].iloc[-1])


def test_no_pattern_is_all_false():
    df = _df([(100, 101, 99, 100.2), (100, 101, 99, 100.1)])
    p = cs.detect(df)
    # ドジ気味の値動きでは反転パターンは立たない（集約も False）
    agg = cs.aggregate(p)
    assert not bool(agg["cdl_bull"].iloc[-1])
    assert not bool(agg["cdl_bear"].iloc[-1])
