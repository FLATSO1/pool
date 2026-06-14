"""シグナル別バックテスト（各テクニカルシグナルの有効性を比較）。

各シグナルを単独で使った場合（他の重みを0にする）にバックテストを回し、
リターン・勝率・シャープ等を比較する。これにより「どのシグナルが効くか」を
データで把握し、重み付けの優先順位づけに使える。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

import pandas as pd

from ..config import DEFAULT_WEIGHTS, Config
from .backtester import Backtester, BacktestResult


@dataclass
class SignalEval:
    name: str
    result: BacktestResult

    @property
    def total_return(self) -> float:
        return self.result.total_return

    @property
    def n_trades(self) -> int:
        return len(self.result.trades)

    def win_rate(self) -> float:
        """売却(SELL)トレードのうち利益が出た割合（概算）。"""
        trades = self.result.trades
        # BUY価格→対応するSELL価格の対応付けは簡易（FIFO）にせず、
        # 約定履歴から銘柄ごとに直近BUYと突き合わせる近似。
        buys: dict[str, float] = {}
        wins = sells = 0
        for t in trades:
            if t.side == "BUY":
                buys[t.ticker] = t.price
            elif t.side == "SELL" and t.ticker in buys:
                sells += 1
                if t.price > buys[t.ticker]:
                    wins += 1
                del buys[t.ticker]
        return wins / sells if sells else 0.0


def _isolated_config(base: Config, signal_key: str | None) -> Config:
    """指定シグナルだけ重み1.0、他は0にした設定を返す。None=既定の重み。"""
    cfg = copy.deepcopy(base)
    if signal_key is not None:
        cfg.technical.weights = {k: 0.0 for k in DEFAULT_WEIGHTS}
        cfg.technical.weights[signal_key] = 1.0
    return cfg


def evaluate_signals(
    cfg: Config,
    ohlcv: dict[str, pd.DataFrame],
    passed_tickers: set[str] | None = None,
) -> list[SignalEval]:
    """各シグナル単独＋既定重み(ALL)のバックテスト結果を返す。

    価格データ(ohlcv)は一度だけ取得して使い回す。
    """
    evals: list[SignalEval] = []

    # ベースライン（現在の重み構成すべて）
    base_result = Backtester(cfg).run(ohlcv, passed_tickers)
    evals.append(SignalEval("ALL(既定重み)", base_result))

    # 各シグナル単独
    for key in DEFAULT_WEIGHTS:
        iso = _isolated_config(cfg, key)
        result = Backtester(iso).run(ohlcv, passed_tickers)
        evals.append(SignalEval(key, result))

    return evals
