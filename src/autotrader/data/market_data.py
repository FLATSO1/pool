"""株価（OHLCV）の取得。

yfinance を遅延インポートして使う。テストや一部処理ではダミーデータを
注入できるよう、関数ベースで分離している。
"""

from __future__ import annotations

import pandas as pd

from ..logging_setup import get_logger

log = get_logger(__name__)

# ローカルCSVをデータソースにする場合に CLI 起動時へ設定される。
_LOCAL_STORE = None       # LocalStore | None
_LOCAL_SOURCE = "yfinance"  # "yfinance" | "local" | "auto"


def configure_local_store(store, source: str = "auto") -> None:
    """ローカルヒストリカルCSVを株価ソースとして登録する。"""
    global _LOCAL_STORE, _LOCAL_SOURCE
    _LOCAL_STORE = store
    _LOCAL_SOURCE = source


def fetch_ohlcv(
    ticker: str,
    period: str = "1y",
    interval: str = "1d",
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """1銘柄の OHLCV を DataFrame で返す。

    返り値のカラム: open, high, low, close, volume（小文字に正規化）。
    index は日時。

    ローカルCSVソースが設定されている場合、日足はまずローカルから読む
    （source="local" は失敗時に空、"auto" は yfinance にフォールバック）。
    分足など 1d 以外はローカル対象外で常に yfinance を使う。
    """
    if _LOCAL_STORE is not None and interval == "1d" and _LOCAL_SOURCE in ("local", "auto"):
        df = _LOCAL_STORE.load(ticker, period=period, start=start, end=end)
        if not df.empty:
            return df
        if _LOCAL_SOURCE == "local":
            log.warning("ローカルにデータがありません: %s", ticker)
            return pd.DataFrame()
        # "auto": yfinance にフォールバック

    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover - 環境依存
        raise RuntimeError(
            "yfinance が未導入です。`pip install yfinance` を実行してください。"
        ) from exc

    kwargs: dict = {"interval": interval, "auto_adjust": True, "progress": False}
    if start or end:
        kwargs["start"] = start
        kwargs["end"] = end
    else:
        kwargs["period"] = period

    df = yf.download(ticker, **kwargs)
    if df is None or df.empty:
        log.warning("株価データを取得できませんでした: %s", ticker)
        return pd.DataFrame()

    # yfinance が MultiIndex カラムを返す場合があるので平坦化
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.rename(columns=str.lower)
    keep = [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]
    return df[keep].dropna()


def fetch_many(
    tickers: list[str], period: str = "1y", interval: str = "1d"
) -> dict[str, pd.DataFrame]:
    """複数銘柄の OHLCV をまとめて取得。"""
    out: dict[str, pd.DataFrame] = {}
    for t in tickers:
        df = fetch_ohlcv(t, period=period, interval=interval)
        if not df.empty:
            out[t] = df
    return out


def latest_price(df: pd.DataFrame) -> float | None:
    """直近終値。"""
    if df.empty or "close" not in df:
        return None
    return float(df["close"].iloc[-1])
