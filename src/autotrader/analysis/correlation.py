"""ポートフォリオの相関分散。

「一緒に動く銘柄」を重ねて持つと、1業種の急落で全建玉が同時にやられる。
新規買いの直前に、候補銘柄のリターンが既保有銘柄と高く相関していないかを見て、
相関が閾値を超えるなら見送る。

相関は符号つきで評価する（高い"正"の相関＝集中リスク）。負相関はむしろ
分散を助けるので妨げない。
"""

from __future__ import annotations

import pandas as pd

_MIN_OVERLAP = 20  # これ未満しか重なる日が無ければ判定不能(=ブロックしない)


def pairwise_correlation(
    a_close: pd.Series, b_close: pd.Series, window: int, min_overlap: int = _MIN_OVERLAP
) -> float | None:
    """2銘柄の日次リターン相関（直近window日）。判定不能なら None。"""
    ra = a_close.pct_change()
    rb = b_close.pct_change()
    joined = pd.concat([ra, rb], axis=1, join="inner").dropna()
    if len(joined) < min_overlap:
        return None
    joined = joined.tail(window)
    if len(joined) < min_overlap:
        return None
    c = joined.iloc[:, 0].corr(joined.iloc[:, 1])
    return None if pd.isna(c) else float(c)


def max_correlation(
    candidate_close: pd.Series,
    held_closes: dict[str, pd.Series],
    window: int,
    min_overlap: int = _MIN_OVERLAP,
) -> tuple[float, str | None]:
    """候補と各保有銘柄の相関のうち最大（符号つき）と、その相手を返す。

    判定できる相手が無ければ (0.0, None)。
    """
    best = 0.0
    who: str | None = None
    for t, s in held_closes.items():
        c = pairwise_correlation(candidate_close, s, window, min_overlap)
        if c is not None and c > best:
            best = c
            who = t
    return best, who


def too_correlated(
    candidate_close: pd.Series,
    held_closes: dict[str, pd.Series],
    window: int,
    threshold: float,
    min_overlap: int = _MIN_OVERLAP,
) -> tuple[bool, float, str | None]:
    """相関が threshold を超える保有銘柄があるか。

    返り値: (見送るべきか, 最大相関, 相手ティッカー)。
    threshold<=0 なら常に許可（無効）。
    """
    if threshold <= 0 or not held_closes:
        return False, 0.0, None
    corr, who = max_correlation(candidate_close, held_closes, window, min_overlap)
    return (corr > threshold, corr, who)
