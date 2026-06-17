"""「直近の強さ」フィルタ（②モメンタム/トレンドゲート）のテスト。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from autotrader.analysis.strength import assess_strength, strength_frame
from autotrader.config import StrengthConfig


def _series_df(values: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(values), freq="D")
    return pd.DataFrame({"close": values}, index=idx)


def test_uptrend_passes():
    # 緩やかな右肩上がり: 直近リターンプラス＆MA上
    df = _series_df([100 + i for i in range(120)])
    cfg = StrengthConfig(lookback_days=60, min_recent_return=0.0, ma_period=75)
    s = assess_strength("X.T", df, cfg)
    assert s.passed
    assert s.recent_return is not None and s.recent_return > 0


def test_downtrend_fails():
    # 右肩下がり: 直近リターンはマイナス → 不通過
    df = _series_df([220 - i for i in range(120)])
    cfg = StrengthConfig(lookback_days=60, min_recent_return=0.0, ma_period=75)
    s = assess_strength("X.T", df, cfg)
    assert not s.passed
    assert s.recent_return is not None and s.recent_return < 0


def test_above_ma_requirement_blocks_below_ma():
    # 上昇後に直近だけ急落 → 直近60日リターンはプラスでもMA割れで不通過にできる
    up = [100 + i for i in range(100)]       # 100→199
    drop = [199 - i * 8 for i in range(1, 21)]  # 直近20日で急落
    df = _series_df(up + drop)
    cfg = StrengthConfig(lookback_days=60, min_recent_return=-1.0, require_above_ma=True, ma_period=75)
    s = assess_strength("X.T", df, cfg)
    assert not s.passed  # MAを割っているので不通過


def test_min_recent_return_threshold():
    df = _series_df([100 + i * 0.05 for i in range(120)])  # ごく緩い上昇（60日で約3%）
    # +5%以上を要求すると、緩い上昇では届かず不通過
    strict = StrengthConfig(lookback_days=60, min_recent_return=0.05, require_above_ma=False)
    assert not assess_strength("X.T", df, strict).passed
    # 0%要求なら通過
    loose = StrengthConfig(lookback_days=60, min_recent_return=0.0, require_above_ma=False)
    assert assess_strength("X.T", df, loose).passed


def test_disabled_always_passes():
    df = _series_df([220 - i for i in range(120)])  # 明確な下落でも
    cfg = StrengthConfig(enabled=False)
    s = assess_strength("X.T", df, cfg)
    assert s.passed


def test_insufficient_data_fails_when_enabled():
    df = _series_df([100, 101, 102])  # lookbackに満たない
    cfg = StrengthConfig(lookback_days=60, ma_period=75)
    s = assess_strength("X.T", df, cfg)
    assert not s.passed


def test_strength_frame_marks_early_bars_false():
    df = _series_df([100 + i for i in range(120)])
    cfg = StrengthConfig(lookback_days=60, ma_period=75)
    frame = strength_frame(df, cfg)
    # 計算に必要な過去が無い序盤は False、十分育った最終バーは True
    assert frame.iloc[0] == False  # noqa: E712
    assert frame.iloc[-1] == True  # noqa: E712
    assert not frame.isna().any()
