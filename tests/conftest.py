"""テスト共通フィクスチャ。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _random_walk(drift: float, seed: int, n: int = 250) -> pd.DataFrame:
    """ドリフト付きランダムウォークでOHLCVを生成（現実的なRSI挙動になる）。"""
    idx = pd.date_range("2023-01-01", periods=n, freq="B")
    rng = np.random.default_rng(seed)
    rets = drift + rng.normal(0, 0.012, n)
    close = 100.0 * np.cumprod(1.0 + rets)
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.full(n, 1_000_000),
        },
        index=idx,
    )


@pytest.fixture
def uptrend_ohlcv() -> pd.DataFrame:
    """上昇トレンドのOHLCV（テクニカルが買い寄りになるはず）。"""
    return _random_walk(drift=0.004, seed=0)


@pytest.fixture
def downtrend_ohlcv() -> pd.DataFrame:
    """下降トレンドのOHLCV。"""
    return _random_walk(drift=-0.004, seed=0)
