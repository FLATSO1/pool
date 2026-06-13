"""テクニカル指標とシグナル生成。

外部のTA-Lib等に依存せず、pandas/numpy だけで実装している。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config import TechnicalConfig


# --- 指標 ---------------------------------------------------------------

def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window, min_periods=window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    # avg_loss==0（下落なし）のときは RSI=100
    out = out.where(avg_loss != 0.0, 100.0)
    return out


def macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return pd.DataFrame(
        {"macd": macd_line, "signal": signal_line, "hist": hist}
    )


def bollinger(series: pd.Series, window: int = 20, n_std: float = 2.0) -> pd.DataFrame:
    mid = sma(series, window)
    std = series.rolling(window=window, min_periods=window).std()
    return pd.DataFrame(
        {"mid": mid, "upper": mid + n_std * std, "lower": mid - n_std * std}
    )


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


# --- シグナル ------------------------------------------------------------

@dataclass
class TechnicalSignal:
    ticker: str
    score: float            # -1.0(強い売り) 〜 +1.0(強い買い)
    action: str             # "BUY" | "SELL" | "HOLD"
    reasons: list[str]
    indicators: dict        # 直近の指標値（参考表示用）


def compute_indicators(df: pd.DataFrame, cfg: TechnicalConfig) -> pd.DataFrame:
    """OHLCV に各種テクニカル指標を付与した DataFrame を返す。"""
    out = df.copy()
    close = out["close"]
    out["sma_short"] = sma(close, cfg.sma_short)
    out["sma_long"] = sma(close, cfg.sma_long)
    out["rsi"] = rsi(close, cfg.rsi_period)
    m = macd(close, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
    out["macd"] = m["macd"]
    out["macd_signal"] = m["signal"]
    out["macd_hist"] = m["hist"]
    if {"high", "low"}.issubset(out.columns):
        out["atr"] = atr(out, cfg.atr_period)
    return out


# 各シグナルの重み（方向 ×1/-1 に乗じ、加重平均する）。
# トレンド（SMA）を主、MACDを副、RSIは過熱/売られすぎの小さな逆張り補正。
_W_TREND = 1.0   # 短期SMA vs 長期SMA の位置関係
_W_CROSS = 0.5   # ゴールデン/デッドクロスの発生（位置関係に上乗せ）
_W_MACD = 0.5    # MACDヒストグラムの符号
_W_RSI = 0.3     # RSIの逆張り補正（強トレンドを過度に打ち消さない）


def _weighted_components(
    ind: pd.DataFrame, cfg: TechnicalConfig
) -> tuple[pd.Series, pd.Series]:
    """加重スコアの分子（符号付き寄与の和）と分母（使用重みの和）を返す。"""
    num = pd.Series(0.0, index=ind.index)
    den = pd.Series(0.0, index=ind.index)

    def add(mask: pd.Series, sign: int, weight: float) -> None:
        nonlocal num, den
        m = mask.fillna(False)
        num = num.add(m * (sign * weight), fill_value=0.0)
        den = den.add(m * weight, fill_value=0.0)

    if {"sma_short", "sma_long"}.issubset(ind.columns):
        up = ind["sma_short"] > ind["sma_long"]
        down = ind["sma_short"] < ind["sma_long"]
        add(up, +1, _W_TREND)
        add(down, -1, _W_TREND)
        prev_up = up.shift(1)
        add(up & (prev_up == False), +1, _W_CROSS)   # ゴールデンクロス  # noqa: E712
        add(down & (prev_up == True), -1, _W_CROSS)   # デッドクロス     # noqa: E712

    if "macd_hist" in ind.columns:
        add(ind["macd_hist"] > 0, +1, _W_MACD)
        add(ind["macd_hist"] < 0, -1, _W_MACD)

    if "rsi" in ind.columns:
        add(ind["rsi"] <= cfg.rsi_oversold, +1, _W_RSI)
        add(ind["rsi"] >= cfg.rsi_overbought, -1, _W_RSI)

    return num, den


def score_frame(ind: pd.DataFrame, cfg: TechnicalConfig) -> pd.Series:
    """指標付きDataFrameから、各日付のテクニカルスコア(-1〜+1)の系列を返す。

    バックテストと generate_signal が共有する加重スコアの本体。
    """
    if len(ind) == 0:
        return pd.Series(dtype=float)
    num, den = _weighted_components(ind, cfg)
    score = (num / den.replace(0.0, np.nan)).fillna(0.0)
    return score.clip(-1.0, 1.0)


def generate_signal(
    ticker: str, df: pd.DataFrame, cfg: TechnicalConfig
) -> TechnicalSignal:
    """指標を総合し、-1〜+1 のテクニカルスコアと売買アクションを返す。

    スコアは score_frame と同一の加重ロジックの最終バー値。
    内訳:
      - 短期SMA vs 長期SMA（トレンド・クロス）
      - MACD ヒストグラムの符号
      - RSI の買われすぎ/売られすぎ（小さな逆張り補正）
    """
    if df.empty or "close" not in df.columns:
        return TechnicalSignal(ticker, 0.0, "HOLD", ["データ不足"], {})
    ind = compute_indicators(df, cfg)
    if ind.empty or len(ind) < 2:
        return TechnicalSignal(ticker, 0.0, "HOLD", ["データ不足"], {})

    score = float(score_frame(ind, cfg).iloc[-1])
    last = ind.iloc[-1]
    prev = ind.iloc[-2]
    reasons = _build_reasons(last, prev, cfg)
    action = "BUY" if score >= 0.3 else "SELL" if score <= -0.3 else "HOLD"

    indicators = {
        "close": _f(last.get("close")),
        "sma_short": _f(last.get("sma_short")),
        "sma_long": _f(last.get("sma_long")),
        "rsi": _f(last.get("rsi")),
        "macd_hist": _f(last.get("macd_hist")),
        "atr": _f(last.get("atr")),
    }
    return TechnicalSignal(ticker, round(score, 4), action, reasons, indicators)


def _build_reasons(last, prev, cfg: TechnicalConfig) -> list[str]:
    """最終バーの状態から、人が読める根拠リストを生成。"""
    reasons: list[str] = []
    if _valid(last.get("sma_short"), last.get("sma_long")):
        if last["sma_short"] > last["sma_long"]:
            reasons.append("短期SMAが長期SMAを上回る（上昇トレンド）")
            if _valid(prev.get("sma_short"), prev.get("sma_long")) and (
                prev["sma_short"] <= prev["sma_long"]
            ):
                reasons.append("ゴールデンクロス発生")
        else:
            reasons.append("短期SMAが長期SMAを下回る（下降トレンド）")
            if _valid(prev.get("sma_short"), prev.get("sma_long")) and (
                prev["sma_short"] >= prev["sma_long"]
            ):
                reasons.append("デッドクロス発生")
    if _valid(last.get("macd_hist")):
        if last["macd_hist"] > 0:
            reasons.append("MACDヒストグラムがプラス（強気）")
        else:
            reasons.append("MACDヒストグラムがマイナス（弱気）")
    if _valid(last.get("rsi")):
        if last["rsi"] <= cfg.rsi_oversold:
            reasons.append(f"RSI={last['rsi']:.0f} 売られすぎ（反発期待）")
        elif last["rsi"] >= cfg.rsi_overbought:
            reasons.append(f"RSI={last['rsi']:.0f} 買われすぎ（過熱）")
    return reasons


def _valid(*vals) -> bool:
    return all(v is not None and not (isinstance(v, float) and v != v) for v in vals)


def _f(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return None if f != f else round(f, 4)
    except (TypeError, ValueError):
        return None
