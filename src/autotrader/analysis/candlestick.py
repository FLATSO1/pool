"""ローソク足（酒田五法）パターンの検出。

OHLCから定番の反転/継続パターンを判定し、各バーで成立したかを
真偽の系列で返す。単独ではダマシが多いため、トレンド文脈（上昇/下降）
を加味し、テクニカル統合スコアには控えめな重みで組み込む。

実装パターン（定番セット）:
  買い: 赤三兵 / 明けの明星 / 陽の包み足 / 陽のはらみ / ハンマー(下落後)
  売り: 三羽烏 / 宵の明星 / 陰の包み足 / 陰のはらみ / 首吊り線・流れ星(上昇後)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# パターン名（根拠表示用）。キーは列名、値は日本語ラベル。
BULLISH_PATTERNS = {
    "cdl_three_soldiers": "赤三兵（3連続陽線・強気）",
    "cdl_morning_star": "明けの明星（底打ち反転）",
    "cdl_bull_engulfing": "陽の包み足（強気転換）",
    "cdl_bull_harami": "陽のはらみ（下落一服）",
    "cdl_hammer": "ハンマー（下ヒゲ・下落後の反発期待）",
}
BEARISH_PATTERNS = {
    "cdl_three_crows": "三羽烏（3連続陰線・弱気）",
    "cdl_evening_star": "宵の明星（天井反転）",
    "cdl_bear_engulfing": "陰の包み足（弱気転換）",
    "cdl_bear_harami": "陰のはらみ（上昇一服）",
    "cdl_hanging_man": "首吊り線/流れ星（上昇後の反落注意）",
}


def detect(
    df: pd.DataFrame,
    uptrend: pd.Series | None = None,
    downtrend: pd.Series | None = None,
) -> pd.DataFrame:
    """各パターンの成立を真偽の列で返す。

    uptrend/downtrend: トレンド文脈（ハンマー/首吊り線などの位置判定に使用）。
    省略時は文脈を要するパターンは無効化される。
    """
    o, h, l, c = df["open"], df["high"], df["low"], df["close"]
    body = c - o
    ab = body.abs()
    rng = (h - l).replace(0.0, np.nan)
    upper = h - np.maximum(o, c)
    lower = np.minimum(o, c) - l
    bull = c > o
    bear = c < o

    if uptrend is None:
        uptrend = pd.Series(False, index=df.index)
    if downtrend is None:
        downtrend = pd.Series(False, index=df.index)

    out = pd.DataFrame(index=df.index)

    # --- 買いパターン ---

    # 赤三兵: 3連続陽線・終値切り上げ・始値が前日実体内
    out["cdl_three_soldiers"] = (
        bull & bull.shift(1) & bull.shift(2)
        & (c > c.shift(1)) & (c.shift(1) > c.shift(2))
        & (o <= c.shift(1)) & (o.shift(1) <= c.shift(2))
    )

    # 明けの明星: 大陰線 → 小実体 → 大陽線（一本目の実体中値超え）
    mid1 = (o.shift(2) + c.shift(2)) / 2.0
    out["cdl_morning_star"] = (
        bear.shift(2) & (ab.shift(1) <= ab.shift(2) * 0.5)
        & bull & (c > mid1)
    )

    # 陽の包み足: 前日陰線を当日陽線が包む
    out["cdl_bull_engulfing"] = (
        bear.shift(1) & bull
        & (o <= c.shift(1)) & (c >= o.shift(1))
    )

    # 陽のはらみ: 前日大陰線の実体内に当日小陽線
    out["cdl_bull_harami"] = (
        bear.shift(1) & bull
        & (np.maximum(o, c) <= o.shift(1)) & (np.minimum(o, c) >= c.shift(1))
        & (ab < ab.shift(1))
    )

    # ハンマー: 下ヒゲが実体の2倍以上・上ヒゲ小・下降トレンド中
    hammer_shape = (lower >= 2.0 * ab) & (upper <= ab) & (ab <= rng * 0.5)
    out["cdl_hammer"] = hammer_shape.fillna(False) & downtrend

    # --- 売りパターン ---

    out["cdl_three_crows"] = (
        bear & bear.shift(1) & bear.shift(2)
        & (c < c.shift(1)) & (c.shift(1) < c.shift(2))
        & (o >= c.shift(1)) & (o.shift(1) >= c.shift(2))
    )

    out["cdl_evening_star"] = (
        bull.shift(2) & (ab.shift(1) <= ab.shift(2) * 0.5)
        & bear & (c < mid1)
    )

    out["cdl_bear_engulfing"] = (
        bull.shift(1) & bear
        & (o >= c.shift(1)) & (c <= o.shift(1))
    )

    out["cdl_bear_harami"] = (
        bull.shift(1) & bear
        & (np.maximum(o, c) <= c.shift(1)) & (np.minimum(o, c) >= o.shift(1))
        & (ab < ab.shift(1))
    )

    # 首吊り線/流れ星: 長い下ヒゲ or 長い上ヒゲ・小実体・上昇トレンド中
    star_shape = (
        ((lower >= 2.0 * ab) | (upper >= 2.0 * ab)) & (ab <= rng * 0.4)
    )
    out["cdl_hanging_man"] = star_shape.fillna(False) & uptrend

    return out.fillna(False).astype(bool)


def aggregate(patterns: pd.DataFrame) -> pd.DataFrame:
    """個別パターン列を、買い/売りの集約フラグにまとめる。"""
    bull_cols = [c for c in BULLISH_PATTERNS if c in patterns.columns]
    bear_cols = [c for c in BEARISH_PATTERNS if c in patterns.columns]
    return pd.DataFrame(
        {
            "cdl_bull": patterns[bull_cols].any(axis=1) if bull_cols else False,
            "cdl_bear": patterns[bear_cols].any(axis=1) if bear_cols else False,
        },
        index=patterns.index,
    )
