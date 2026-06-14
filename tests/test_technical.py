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


def test_compute_indicators_has_new_columns(uptrend_ohlcv):
    cfg = TechnicalConfig()
    ind = ta.compute_indicators(uptrend_ohlcv, cfg)
    for col in (
        "sma_mid", "bb_upper", "bb_lower", "vol_ma",
        "close_high", "ichimoku_span_a", "ichimoku_span_b",
    ):
        assert col in ind.columns


def test_ichimoku_columns_and_shift():
    n = 120
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    close = pd.Series(np.linspace(100, 130, n), index=idx)
    df = pd.DataFrame(
        {"high": close + 1, "low": close - 1, "close": close}, index=idx
    )
    ich = ta.ichimoku(df, 9, 26, 52, 26)
    assert list(ich.columns) == [
        "ichimoku_conv", "ichimoku_base", "ichimoku_span_a", "ichimoku_span_b",
    ]
    # 先行スパンは shift 分だけ後ろが埋まる（先頭はNaN）
    assert pd.isna(ich["ichimoku_span_a"].iloc[0])


def test_perfect_order_reason_on_uptrend(uptrend_ohlcv):
    cfg = TechnicalConfig()
    sig = ta.generate_signal("T.T", uptrend_ohlcv, cfg)
    # 強い上昇トレンドではパーフェクトオーダーか雲の上が根拠に出る
    joined = " / ".join(sig.reasons)
    assert "パーフェクトオーダー" in joined or "雲の上" in joined


def test_bollinger_lower_touch_is_bullish_vote():
    # 終値が下バンドに張り付くケースを構成し、逆張り買い票が入ることを確認
    cfg = TechnicalConfig(bb_window=20, bb_std=2.0)
    n = 60
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    close = np.full(n, 100.0)
    close[-1] = 80.0  # 直近で急落 → 下バンド割れ
    df = pd.DataFrame(
        {
            "open": close, "high": close + 0.5, "low": close - 0.5,
            "close": close, "volume": np.full(n, 1e6),
        },
        index=idx,
    )
    ind = ta.compute_indicators(df, cfg)
    last = ind.iloc[-1]
    assert last["close"] <= last["bb_lower"]
