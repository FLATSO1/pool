"""テクニカル指標とシグナルのテスト。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from autotrader.analysis import technical as ta
from autotrader.config import TechnicalConfig


def test_sma_basic():
    s = pd.Series([1, 2, 3, 4, 5], dtype=float)
    result = ta.sma(s, 2)
    assert result.iloc[1] == 1.5
    assert result.iloc[-1] == 4.5
    assert pd.isna(result.iloc[0])


def test_rsi_bounds():
    s = pd.Series(np.linspace(100, 200, 100))
    r = ta.rsi(s, 14).dropna()
    assert (r >= 0).all() and (r <= 100).all()
    # 一貫した上昇では RSI は高くなる
    assert r.iloc[-1] > 70


def test_rsi_all_up_is_100():
    s = pd.Series(range(1, 50), dtype=float)
    r = ta.rsi(s, 14)
    assert r.iloc[-1] == 100.0


def test_macd_columns():
    s = pd.Series(np.linspace(100, 200, 100))
    m = ta.macd(s)
    assert list(m.columns) == ["macd", "signal", "hist"]
    assert len(m) == len(s)


def test_uptrend_signal_is_bullish(uptrend_ohlcv):
    cfg = TechnicalConfig()
    sig = ta.generate_signal("TEST.T", uptrend_ohlcv, cfg)
    assert sig.score > 0
    assert sig.action in ("BUY", "HOLD")
    assert sig.indicators["close"] is not None


def test_downtrend_signal_is_bearish(downtrend_ohlcv):
    cfg = TechnicalConfig()
    sig = ta.generate_signal("TEST.T", downtrend_ohlcv, cfg)
    assert sig.score < 0


def test_score_frame_matches_signal_direction(uptrend_ohlcv):
    cfg = TechnicalConfig()
    ind = ta.compute_indicators(uptrend_ohlcv, cfg)
    series = ta.score_frame(ind, cfg)
    assert len(series) == len(uptrend_ohlcv)
    assert (series >= -1).all() and (series <= 1).all()
    # 上昇トレンドの後半は概ね正のスコア
    assert series.iloc[-1] > 0


def test_empty_df_returns_hold():
    cfg = TechnicalConfig()
    sig = ta.generate_signal("X.T", pd.DataFrame(), cfg)
    assert sig.action == "HOLD"
    assert sig.score == 0.0
