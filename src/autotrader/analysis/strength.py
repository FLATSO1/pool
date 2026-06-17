"""直近の強さ（モメンタム/トレンド）フィルタ。

「②直近の強さ」ゲート。ファンダで選んだ銘柄のうち、実際に上昇基調にある
ものだけを新規買い対象に絞る。判定は価格データ（終値）のみで完結するため、
ライブ・バックテストで同一の挙動になり、テストもしやすい。

判定条件（有効なものすべてを満たせば通過）:
  - 直近 lookback_days 日のリターン ≥ min_recent_return
  - require_above_ma=True なら 終値 > ma_period 日移動平均（上昇基調）
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..config import StrengthConfig


@dataclass
class StrengthScore:
    ticker: str
    passed: bool
    recent_return: float | None
    reasons: list[str]


def strength_frame(df: pd.DataFrame, cfg: StrengthConfig) -> pd.Series:
    """各バーで強さフィルタを通過するか（True/False）の系列を返す。

    計算に必要な過去データが不足するバー（NaN）は不通過(False)扱い。
    """
    close = df["close"]
    ok = pd.Series(True, index=df.index)

    if cfg.lookback_days > 0:
        ret = close / close.shift(cfg.lookback_days) - 1.0
        ok = ok & (ret >= cfg.min_recent_return)

    if cfg.require_above_ma and cfg.ma_period > 0:
        ma = close.rolling(cfg.ma_period, min_periods=cfg.ma_period).mean()
        ok = ok & (close > ma)

    return ok.fillna(False)


def assess_strength(
    ticker: str, df: pd.DataFrame, cfg: StrengthConfig
) -> StrengthScore:
    """最新バーの強さを評価する（エンジン/表示用）。

    cfg.enabled=False のときは常に通過（フィルタ無効）。
    """
    if not cfg.enabled:
        return StrengthScore(ticker, True, None, ["強さフィルタ無効"])

    if df is None or df.empty or "close" not in df.columns:
        return StrengthScore(ticker, False, None, ["価格データ不足"])

    frame = strength_frame(df, cfg)
    passed = bool(frame.iloc[-1]) if len(frame) else False

    close = df["close"]
    recent_return: float | None = None
    if cfg.lookback_days > 0 and len(close) > cfg.lookback_days:
        base = close.iloc[-1 - cfg.lookback_days]
        if base and base == base:  # NaN/0除外
            recent_return = float(close.iloc[-1] / base - 1.0)

    reasons: list[str] = []
    if recent_return is not None:
        reasons.append(f"直近{cfg.lookback_days}日リターン {recent_return * 100:+.1f}%")
    if cfg.require_above_ma:
        reasons.append(f"{cfg.ma_period}日線との位置")
    reasons.append("強さ通過" if passed else "強さ不通過")

    return StrengthScore(ticker, passed, recent_return, reasons)
