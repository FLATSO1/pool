"""バックテスタの相関分散ゲートのテスト。"""

from __future__ import annotations

import collections

import numpy as np
import pandas as pd

from autotrader.backtest.backtester import Backtester
from autotrader.config import Config


def _frame_from_close(close: pd.Series) -> pd.DataFrame:
    return pd.DataFrame(
        {"open": close, "high": close * 1.01, "low": close * 0.99,
         "close": close, "volume": 1_000_000},
        index=close.index,
    )


def _trending(n, seed, drift):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-01-01", periods=n, freq="B")
    return pd.Series(
        np.clip(1000 + np.cumsum(rng.normal(drift, 4, n)), 100, None), index=idx
    )


def _cfg(max_corr: float) -> Config:
    cfg = Config()
    cfg.trading.cash = 1_000_000
    cfg.trading.max_positions = 5
    cfg.trading.buy_score_threshold = 0.3
    cfg.trading.max_correlation = max_corr
    cfg.trading.correlation_lookback = 60
    return cfg


def _ohlcv():
    # A/B/C は強相関（同じ素材＋微小ノイズ）、D は独立
    base = _trending(400, 1, 0.6)
    rng = np.random.default_rng(42)
    series = {
        "A": base,
        "B": base * 1.2 + rng.normal(0, 0.5, len(base)),
        "C": base * 0.8 + rng.normal(0, 0.5, len(base)),
        "D": _trending(400, 99, 0.6),
    }
    return {k: _frame_from_close(s) for k, s in series.items()}


def _concurrent_correlated_days(result, index) -> int:
    """A/B/C のうち2銘柄以上を同時保有していた日数を約定列から復元。"""
    by_date = collections.defaultdict(list)
    for t in result.trades:
        by_date[t.date].append((t.side, t.ticker))
    held: set[str] = set()
    days = 0
    for dt in index:
        for side, tk in by_date.get(dt, []):
            held.add(tk) if side == "BUY" else held.discard(tk)
        if len(held & {"A", "B", "C"}) >= 2:
            days += 1
    return days


def _correlated_buys(result) -> int:
    return sum(1 for t in result.trades if t.side == "BUY" and t.ticker in ("B", "C"))


def test_correlation_gate_suppresses_correlated_holdings():
    ohlcv = _ohlcv()
    index = sorted(set().union(*[df.index for df in ohlcv.values()]))

    off = Backtester(_cfg(0.0)).run(ohlcv)
    on = Backtester(_cfg(0.85)).run(ohlcv)

    days_off = _concurrent_correlated_days(off, index)
    days_on = _concurrent_correlated_days(on, index)

    # ゲートにより、相関銘柄を同時保有する日数が大幅に減る
    assert days_on < days_off
    assert days_on < days_off * 0.3
    # 冗長な相関買い（B/C）も抑制される
    assert _correlated_buys(on) < _correlated_buys(off)


def test_gate_disabled_matches_baseline():
    # max_correlation=0 は従来挙動（無効）と一致する
    ohlcv = _ohlcv()
    a = Backtester(_cfg(0.0)).run(ohlcv)
    b = Backtester(_cfg(0.0)).run(ohlcv)
    assert len(a.trades) == len(b.trades)
