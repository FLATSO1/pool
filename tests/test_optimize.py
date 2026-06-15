"""重みチューニング（分割・重み導出・end-to-end）のテスト。"""

from __future__ import annotations

import numpy as np
import pandas as pd

from autotrader.config import DEFAULT_WEIGHTS, Config
from autotrader.backtest.backtester import BacktestResult
from autotrader.backtest.optimize import (
    combined_split_date,
    derive_weights,
    optimize_weights,
    split_ohlcv,
)
from autotrader.backtest.signal_eval import SignalEval


def _result(total_return: float, benchmark: float = 0.0) -> BacktestResult:
    # initial=100, final=100*(1+total_return) になる equity_curve を作る
    curve = pd.Series([100.0, 100.0 * (1 + total_return)])
    return BacktestResult(curve, [], initial_cash=100.0, benchmark_return=benchmark)


def _frame(n=300, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-01-01", periods=n, freq="B")
    price = 1000 + np.cumsum(rng.normal(0, 5, n))
    price = np.clip(price, 100, None)
    return pd.DataFrame(
        {"open": price, "high": price * 1.01, "low": price * 0.99,
         "close": price, "volume": 1_000_000},
        index=idx,
    )


def test_combined_split_and_split_ohlcv():
    ohlcv = {"A": _frame(100, 1), "B": _frame(100, 2)}
    split = combined_split_date(ohlcv, fraction=0.7)
    train, test = split_ohlcv(ohlcv, split)
    assert train and test
    for df in train.values():
        assert df.index.max() < split
    for df in test.values():
        assert df.index.min() >= split


def test_derive_weights_proportional_and_zero_negatives():
    evals = [
        SignalEval("ALL(既定重み)", _result(0.5)),
        SignalEval("trend", _result(0.30)),  # 勝ち
        SignalEval("rsi", _result(0.10)),    # 勝ち（小）
        SignalEval("macd", _result(-0.20)),  # 負け → 0
    ]
    w = derive_weights(evals, metric="return")
    assert abs(sum(w.values()) - 1.0) < 1e-6
    assert w["macd"] == 0.0
    assert w["trend"] > w["rsi"] > 0
    # 評価に出ていないシグナルは0で埋まる
    assert all(k in w for k in DEFAULT_WEIGHTS)


def test_derive_weights_all_negative_fallback():
    evals = [SignalEval("trend", _result(-0.1)), SignalEval("rsi", _result(-0.2))]
    w = derive_weights(evals, metric="return")
    assert w == dict(DEFAULT_WEIGHTS)  # 全敗→既定重みにフォールバック


def test_optimize_weights_end_to_end():
    cfg = Config()
    ohlcv = {"7203.T": _frame(400, 3), "6758.T": _frame(400, 4)}
    res = optimize_weights(cfg, ohlcv, fraction=0.7, metric="excess")
    assert abs(sum(res.weights.values()) - 1.0) < 1e-6 or res.weights == dict(DEFAULT_WEIGHTS)
    # 4本のバックテスト結果が揃う
    assert res.train_tuned is not None and res.test_tuned is not None
    assert "technical:" in res.weights_yaml()
