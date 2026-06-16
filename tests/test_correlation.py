"""相関分散ロジックのテスト。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from autotrader.analysis.correlation import (
    max_correlation,
    pairwise_correlation,
    too_correlated,
)


def _series(values, start="2023-01-01"):
    idx = pd.date_range(start, periods=len(values), freq="B")
    return pd.Series(values, index=idx, dtype=float)


def _random_walk(n, seed, drift=0.0, scale=5.0):
    rng = np.random.default_rng(seed)
    return _series(np.clip(1000 + np.cumsum(rng.normal(drift, scale, n)), 100, None))


def test_identical_series_high_correlation():
    a = _random_walk(120, 1)
    b = a * 1.5  # 完全連動（リターンは同一）
    c = pairwise_correlation(a, b, window=60)
    assert c is not None and c > 0.99


def test_independent_series_low_correlation():
    a = _random_walk(200, 10)
    b = _random_walk(200, 999)
    c = pairwise_correlation(a, b, window=120)
    assert c is not None and abs(c) < 0.5


def test_insufficient_overlap_returns_none():
    a = _series([100, 101, 102])  # 重なるリターンが少なすぎ
    b = _series([50, 51, 52])
    assert pairwise_correlation(a, b, window=60) is None


def test_max_correlation_picks_worst():
    base = _random_walk(150, 3)
    held = {
        "SAME": base * 2.0,            # 強相関
        "INDEP": _random_walk(150, 77),
    }
    corr, who = max_correlation(base, held, window=90)
    assert who == "SAME"
    assert corr > 0.9


def test_too_correlated_blocks_and_respects_threshold():
    base = _random_walk(150, 3)
    held = {"SAME": base * 2.0}
    skip, corr, who = too_correlated(base, held, window=90, threshold=0.8)
    assert skip and who == "SAME" and corr > 0.8
    # 閾値0以下は無効（常に許可）
    skip2, _, _ = too_correlated(base, held, window=90, threshold=0.0)
    assert not skip2
    # 保有なしは常に許可
    skip3, _, _ = too_correlated(base, {}, window=90, threshold=0.8)
    assert not skip3


def test_negative_correlation_not_blocked():
    a = _random_walk(150, 5)
    # aと逆方向に動く系列（負相関）→ 集中リスクではないのでブロックしない
    rets = a.pct_change().fillna(0.0)
    b = _series(np.clip(1000 * np.cumprod(1 - rets.values * 0.9 + 1e-9), 100, None),
                start="2023-01-01")
    skip, corr, _ = too_correlated(a, {"INV": b}, window=90, threshold=0.7)
    assert not skip
    assert corr <= 0.7
