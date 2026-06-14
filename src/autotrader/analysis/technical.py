"""テクニカル指標とシグナル生成。

外部のTA-Lib等に依存せず、pandas/numpy だけで実装している。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config import DEFAULT_WEIGHTS, TechnicalConfig
from . import candlestick


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


def stochastic(
    df: pd.DataFrame, k: int = 14, d: int = 3, smooth: int = 3
) -> pd.DataFrame:
    """ストキャスティクス（スロー %K, %D）を返す。"""
    low_n = df["low"].rolling(k, min_periods=k).min()
    high_n = df["high"].rolling(k, min_periods=k).max()
    rng = (high_n - low_n).replace(0.0, np.nan)
    fast_k = 100.0 * (df["close"] - low_n) / rng
    slow_k = fast_k.rolling(smooth, min_periods=smooth).mean()
    slow_d = slow_k.rolling(d, min_periods=d).mean()
    return pd.DataFrame({"stoch_k": slow_k, "stoch_d": slow_d})


def dmi_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """DMI（+DI, -DI）と ADX を返す（Wilder式）。"""
    high, low, close = df["high"], df["low"], df["close"]
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    plus_dm = pd.Series(plus_dm, index=df.index)
    minus_dm = pd.Series(minus_dm, index=df.index)

    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    atr_n = tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    plus_di = 100.0 * (
        plus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        / atr_n.replace(0.0, np.nan)
    )
    minus_di = 100.0 * (
        minus_dm.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        / atr_n.replace(0.0, np.nan)
    )
    di_sum = (plus_di + minus_di).replace(0.0, np.nan)
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum
    adx = dx.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    return pd.DataFrame({"plus_di": plus_di, "minus_di": minus_di, "adx": adx})


def ichimoku(
    df: pd.DataFrame,
    tenkan: int = 9,
    kijun: int = 26,
    senkou_b: int = 52,
    shift: int = 26,
) -> pd.DataFrame:
    """一目均衡表の主要ラインを返す。

    先行スパンA/Bは表示位置（shift日先行）に合わせてシフト済み。
    """
    high, low = df["high"], df["low"]

    def midline(period: int) -> pd.Series:
        return (
            high.rolling(period, min_periods=period).max()
            + low.rolling(period, min_periods=period).min()
        ) / 2.0

    conv = midline(tenkan)   # 転換線
    base = midline(kijun)    # 基準線
    span_a = ((conv + base) / 2.0).shift(shift)  # 先行スパンA（雲）
    span_b = midline(senkou_b).shift(shift)      # 先行スパンB（雲）
    return pd.DataFrame(
        {
            "ichimoku_conv": conv,
            "ichimoku_base": base,
            "ichimoku_span_a": span_a,
            "ichimoku_span_b": span_b,
        }
    )


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
    out["sma_mid"] = sma(close, cfg.sma_mid)
    out["sma_long"] = sma(close, cfg.sma_long)
    out["rsi"] = rsi(close, cfg.rsi_period)
    m = macd(close, cfg.macd_fast, cfg.macd_slow, cfg.macd_signal)
    out["macd"] = m["macd"]
    out["macd_signal"] = m["signal"]
    out["macd_hist"] = m["hist"]

    # ボリンジャーバンド
    bb = bollinger(close, cfg.bb_window, cfg.bb_std)
    out["bb_mid"] = bb["mid"]
    out["bb_upper"] = bb["upper"]
    out["bb_lower"] = bb["lower"]

    # 出来高ブレイク用
    if "volume" in out.columns:
        out["vol_ma"] = sma(out["volume"], cfg.vol_ma_window)
        out["close_high"] = close.rolling(
            cfg.breakout_window, min_periods=cfg.breakout_window
        ).max()
        out["close_low"] = close.rolling(
            cfg.breakout_window, min_periods=cfg.breakout_window
        ).min()

    # ダイバージェンス（価格とRSIの逆行）の参照用に過去値を保持
    lb = cfg.divergence_lookback
    out["close_lb_ago"] = close.shift(lb)
    out["rsi_lb_ago"] = out["rsi"].shift(lb)

    # 一目均衡表・ATR・ストキャス・DMI/ADX（高安が必要）
    if {"high", "low"}.issubset(out.columns):
        out["atr"] = atr(out, cfg.atr_period)
        st = stochastic(out, cfg.stoch_k, cfg.stoch_d, cfg.stoch_smooth)
        out["stoch_k"] = st["stoch_k"]
        out["stoch_d"] = st["stoch_d"]
        dm = dmi_adx(out, cfg.adx_period)
        out["plus_di"] = dm["plus_di"]
        out["minus_di"] = dm["minus_di"]
        out["adx"] = dm["adx"]
        ich = ichimoku(
            out,
            cfg.ichimoku_tenkan,
            cfg.ichimoku_kijun,
            cfg.ichimoku_senkou_b,
            cfg.ichimoku_shift,
        )
        for col in ich.columns:
            out[col] = ich[col]

    # ローソク足パターン（始値・高安が必要）
    if {"open", "high", "low"}.issubset(out.columns):
        uptrend = out["sma_short"] > out["sma_long"]
        downtrend = out["sma_short"] < out["sma_long"]
        patterns = candlestick.detect(out, uptrend, downtrend)
        agg = candlestick.aggregate(patterns)
        for col in patterns.columns:
            out[col] = patterns[col]
        out["cdl_bull"] = agg["cdl_bull"]
        out["cdl_bear"] = agg["cdl_bear"]
    return out


def _weighted_components(
    ind: pd.DataFrame, cfg: TechnicalConfig
) -> tuple[pd.Series, pd.Series]:
    """加重スコアの分子（符号付き寄与の和）と分母（使用重みの和）を返す。

    各シグナルの重みは cfg.weights（未指定キーは DEFAULT_WEIGHTS）から取得。
    重み0のシグナルは投票しない（無効化）。
    """
    num = pd.Series(0.0, index=ind.index)
    den = pd.Series(0.0, index=ind.index)
    weights = cfg.weights or {}

    def w(key: str) -> float:
        return float(weights.get(key, DEFAULT_WEIGHTS[key]))

    def add(mask: pd.Series, sign: int, weight: float) -> None:
        nonlocal num, den
        if weight == 0.0:
            return
        m = mask.fillna(False)
        num = num.add(m * (sign * weight), fill_value=0.0)
        den = den.add(m * weight, fill_value=0.0)

    if {"sma_short", "sma_long"}.issubset(ind.columns):
        up = ind["sma_short"] > ind["sma_long"]
        down = ind["sma_short"] < ind["sma_long"]
        add(up, +1, w("trend"))
        add(down, -1, w("trend"))
        prev_up = up.shift(1)
        add(up & (prev_up == False), +1, w("cross"))   # ゴールデンクロス  # noqa: E712
        add(down & (prev_up == True), -1, w("cross"))   # デッドクロス     # noqa: E712

    if "macd_hist" in ind.columns:
        add(ind["macd_hist"] > 0, +1, w("macd"))
        add(ind["macd_hist"] < 0, -1, w("macd"))

    if "rsi" in ind.columns:
        add(ind["rsi"] <= cfg.rsi_oversold, +1, w("rsi"))
        add(ind["rsi"] >= cfg.rsi_overbought, -1, w("rsi"))

    # ボリンジャーバンド（±2σの逆張り）
    if {"bb_lower", "bb_upper"}.issubset(ind.columns):
        add(ind["close"] <= ind["bb_lower"], +1, w("bb"))
        add(ind["close"] >= ind["bb_upper"], -1, w("bb"))

    # 出来高急増を伴うブレイク（直近高値/安値更新＋出来高>平均×倍率）
    if {"vol_ma", "close_high", "close_low", "volume"}.issubset(ind.columns):
        high_vol = ind["volume"] > ind["vol_ma"] * cfg.vol_mult
        new_high = ind["close"] >= ind["close_high"]
        new_low = ind["close"] <= ind["close_low"]
        add(new_high & high_vol, +1, w("vol"))
        add(new_low & high_vol, -1, w("vol"))

    # パーフェクトオーダー（短期>中期>長期 / その逆）
    if {"sma_short", "sma_mid", "sma_long"}.issubset(ind.columns):
        po_up = (ind["sma_short"] > ind["sma_mid"]) & (
            ind["sma_mid"] > ind["sma_long"]
        )
        po_down = (ind["sma_short"] < ind["sma_mid"]) & (
            ind["sma_mid"] < ind["sma_long"]
        )
        add(po_up, +1, w("perfect_order"))
        add(po_down, -1, w("perfect_order"))

    # 一目均衡表（雲抜け＋三役好転/逆転）
    if {"ichimoku_span_a", "ichimoku_span_b"}.issubset(ind.columns):
        cloud_top = pd.concat(
            [ind["ichimoku_span_a"], ind["ichimoku_span_b"]], axis=1
        ).max(axis=1)
        cloud_bot = pd.concat(
            [ind["ichimoku_span_a"], ind["ichimoku_span_b"]], axis=1
        ).min(axis=1)
        above_cloud = ind["close"] > cloud_top
        below_cloud = ind["close"] < cloud_bot
        add(above_cloud, +1, w("ichimoku_cloud"))
        add(below_cloud, -1, w("ichimoku_cloud"))

        if {"ichimoku_conv", "ichimoku_base"}.issubset(ind.columns):
            # 遅行スパン > 26日前の株価  ≡  現在値 > 26日前の現在値
            chikou_up = ind["close"] > ind["close"].shift(cfg.ichimoku_shift)
            tk_up = ind["ichimoku_conv"] > ind["ichimoku_base"]
            triple_up = above_cloud & tk_up & chikou_up
            triple_down = below_cloud & (~tk_up) & (~chikou_up)
            add(triple_up, +1, w("ichimoku_triple"))
            add(triple_down, -1, w("ichimoku_triple"))

    # ローソク足パターン（買い/売りの集約フラグ）
    if "cdl_bull" in ind.columns:
        add(ind["cdl_bull"], +1, w("candlestick"))
    if "cdl_bear" in ind.columns:
        add(ind["cdl_bear"], -1, w("candlestick"))

    # ストキャスティクス（買われ/売られすぎの逆張り）
    if "stoch_k" in ind.columns:
        add(ind["stoch_k"] <= cfg.stoch_oversold, +1, w("stoch"))
        add(ind["stoch_k"] >= cfg.stoch_overbought, -1, w("stoch"))

    # DMI/ADX（ADXが閾値超＝トレンドが強いときだけ方向に投票）
    if {"plus_di", "minus_di", "adx"}.issubset(ind.columns):
        strong = ind["adx"] >= cfg.adx_threshold
        add(strong & (ind["plus_di"] > ind["minus_di"]), +1, w("adx"))
        add(strong & (ind["minus_di"] > ind["plus_di"]), -1, w("adx"))

    # ダイバージェンス（価格とRSIの逆行）
    if {"close_lb_ago", "rsi_lb_ago", "rsi"}.issubset(ind.columns):
        # 強気: 価格は下げたがRSIは上昇（売られすぎ圏から）
        bull_div = (
            (ind["close"] < ind["close_lb_ago"])
            & (ind["rsi"] > ind["rsi_lb_ago"])
            & (ind["rsi_lb_ago"] <= 40.0)
        )
        # 弱気: 価格は上げたがRSIは低下（買われすぎ圏から）
        bear_div = (
            (ind["close"] > ind["close_lb_ago"])
            & (ind["rsi"] < ind["rsi_lb_ago"])
            & (ind["rsi_lb_ago"] >= 60.0)
        )
        add(bull_div, +1, w("divergence"))
        add(bear_div, -1, w("divergence"))

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
        "sma_mid": _f(last.get("sma_mid")),
        "sma_long": _f(last.get("sma_long")),
        "rsi": _f(last.get("rsi")),
        "macd_hist": _f(last.get("macd_hist")),
        "atr": _f(last.get("atr")),
        "bb_upper": _f(last.get("bb_upper")),
        "bb_lower": _f(last.get("bb_lower")),
        "ichimoku_span_a": _f(last.get("ichimoku_span_a")),
        "ichimoku_span_b": _f(last.get("ichimoku_span_b")),
        "stoch_k": _f(last.get("stoch_k")),
        "adx": _f(last.get("adx")),
        "plus_di": _f(last.get("plus_di")),
        "minus_di": _f(last.get("minus_di")),
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

    # ボリンジャーバンド
    if _valid(last.get("close"), last.get("bb_lower"), last.get("bb_upper")):
        if last["close"] <= last["bb_lower"]:
            reasons.append("ボリンジャー −2σ 到達（逆張り買い期待）")
        elif last["close"] >= last["bb_upper"]:
            reasons.append("ボリンジャー +2σ 到達（過熱）")

    # 出来高ブレイク
    if _valid(
        last.get("close"), last.get("close_high"),
        last.get("volume"), last.get("vol_ma"),
    ):
        high_vol = last["volume"] > last["vol_ma"] * cfg.vol_mult
        if high_vol and last["close"] >= last["close_high"]:
            reasons.append("出来高急増を伴う直近高値ブレイク（強気）")
        elif high_vol and last["close"] <= last.get("close_low", float("inf")):
            reasons.append("出来高急増を伴う直近安値ブレイク（弱気）")

    # パーフェクトオーダー
    if _valid(last.get("sma_short"), last.get("sma_mid"), last.get("sma_long")):
        if last["sma_short"] > last["sma_mid"] > last["sma_long"]:
            reasons.append("パーフェクトオーダー（短期>中期>長期・強い上昇）")
        elif last["sma_short"] < last["sma_mid"] < last["sma_long"]:
            reasons.append("逆パーフェクトオーダー（短期<中期<長期・強い下降）")

    # 一目均衡表
    if _valid(last.get("close"), last.get("ichimoku_span_a"), last.get("ichimoku_span_b")):
        top = max(last["ichimoku_span_a"], last["ichimoku_span_b"])
        bot = min(last["ichimoku_span_a"], last["ichimoku_span_b"])
        if last["close"] > top:
            reasons.append("一目: 雲の上（強気）")
        elif last["close"] < bot:
            reasons.append("一目: 雲の下（弱気）")

    # ストキャスティクス
    if _valid(last.get("stoch_k")):
        if last["stoch_k"] <= cfg.stoch_oversold:
            reasons.append(f"ストキャス %K={last['stoch_k']:.0f} 売られすぎ")
        elif last["stoch_k"] >= cfg.stoch_overbought:
            reasons.append(f"ストキャス %K={last['stoch_k']:.0f} 買われすぎ")

    # DMI / ADX
    if _valid(last.get("plus_di"), last.get("minus_di"), last.get("adx")):
        if last["adx"] >= cfg.adx_threshold:
            if last["plus_di"] > last["minus_di"]:
                reasons.append(f"DMI: +DI>-DI・ADX={last['adx']:.0f}（強い上昇）")
            else:
                reasons.append(f"DMI: -DI>+DI・ADX={last['adx']:.0f}（強い下降）")

    # ダイバージェンス
    if _valid(last.get("close"), last.get("close_lb_ago"),
              last.get("rsi"), last.get("rsi_lb_ago")):
        if (last["close"] < last["close_lb_ago"] and last["rsi"] > last["rsi_lb_ago"]
                and last["rsi_lb_ago"] <= 40.0):
            reasons.append("強気ダイバージェンス（価格↓だがRSI↑）")
        elif (last["close"] > last["close_lb_ago"] and last["rsi"] < last["rsi_lb_ago"]
                and last["rsi_lb_ago"] >= 60.0):
            reasons.append("弱気ダイバージェンス（価格↑だがRSI↓）")

    # ローソク足パターン（成立したものを名前で表示）
    for col, label in {**candlestick.BULLISH_PATTERNS, **candlestick.BEARISH_PATTERNS}.items():
        if bool(last.get(col, False)):
            reasons.append(f"ローソク足: {label}")
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
