"""重みチューニング（データ駆動でテクニカル重みを決める）。

過学習を避けるため、巨大なグリッド探索ではなく説明可能な方式をとる:
  1) TRAIN期間で各シグナル単独のバックテスト成績を測る（signal_eval）
  2) 成績が正のシグナルだけを、その成績に比例した重みに配分（負は0）
  3) その重みを TEST期間（アウトオブサンプル）で検証し、既定重みと比較

「効くシグナルに重みを寄せる」を、in-sample/out-of-sampleで検証しながら行う。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

import pandas as pd

from ..config import DEFAULT_WEIGHTS, Config
from .backtester import BacktestResult, Backtester
from .signal_eval import SignalEval, evaluate_signals

# 目的関数: SignalEval/BacktestResult からスカラを取り出す
_METRICS = {
    "excess": lambda r: r.excess_return(),     # バイ&ホールド超過（既定）
    "sharpe": lambda r: r.sharpe(),
    "return": lambda r: r.total_return,
}


@dataclass
class OptimizeResult:
    metric: str
    split_date: pd.Timestamp
    weights: dict[str, float]              # 提案重み（合計1.0）
    train_baseline: BacktestResult
    train_tuned: BacktestResult
    test_baseline: BacktestResult
    test_tuned: BacktestResult

    def weights_yaml(self) -> str:
        """config.yaml に貼れる technical.weights スニペット。"""
        lines = ["technical:", "  weights:"]
        for k, v in sorted(self.weights.items(), key=lambda kv: -kv[1]):
            lines.append(f"    {k}: {v:.3f}")
        return "\n".join(lines)


def combined_split_date(
    ohlcv: dict[str, pd.DataFrame], fraction: float = 0.7
) -> pd.Timestamp:
    """全銘柄の日付和集合のうち、fraction の位置の日付を返す。"""
    index = sorted(set().union(*[df.index for df in ohlcv.values()]))
    if not index:
        raise ValueError("データが空です")
    i = min(int(len(index) * fraction), len(index) - 1)
    return pd.Timestamp(index[i])


def split_ohlcv(
    ohlcv: dict[str, pd.DataFrame], split_date: pd.Timestamp
) -> tuple[dict, dict]:
    """split_date 未満を train、以降を test に分割（空フレームは除外）。"""
    train, test = {}, {}
    for t, df in ohlcv.items():
        tr = df[df.index < split_date]
        te = df[df.index >= split_date]
        if not tr.empty:
            train[t] = tr
        if not te.empty:
            test[t] = te
    return train, test


def derive_weights(
    evals: list[SignalEval], metric: str = "excess"
) -> dict[str, float]:
    """各シグナル単独の成績(metric)に比例した重みを作る。負の成績は0。"""
    fn = _METRICS[metric]
    raw: dict[str, float] = {}
    for e in evals:
        if e.name in DEFAULT_WEIGHTS:   # 単独シグナルのみ（ALLは除外）
            raw[e.name] = max(fn(e.result), 0.0)

    total = sum(raw.values())
    # 全部0（どれも単独では勝てない）→ 既定重みにフォールバック
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)

    return {k: round(raw.get(k, 0.0) / total, 4) for k in DEFAULT_WEIGHTS}


def _with_weights(base: Config, weights: dict[str, float]) -> Config:
    cfg = copy.deepcopy(base)
    cfg.technical.weights = dict(weights)
    return cfg


def optimize_weights(
    cfg: Config,
    ohlcv: dict[str, pd.DataFrame],
    passed_tickers: set[str] | None = None,
    split_date: pd.Timestamp | str | None = None,
    fraction: float = 0.7,
    metric: str = "excess",
) -> OptimizeResult:
    """train/test分割で重みを導出・検証する。"""
    if metric not in _METRICS:
        raise ValueError(f"未知のmetric: {metric}（{list(_METRICS)}）")

    if split_date is None:
        split = combined_split_date(ohlcv, fraction)
    else:
        split = pd.Timestamp(split_date)

    train, test = split_ohlcv(ohlcv, split)
    if not train or not test:
        raise ValueError("train/testに十分なデータがありません（分割日を見直してください）")

    # 1) TRAINで各シグナル単独の成績 → 2) 重み導出
    evals = evaluate_signals(cfg, train, passed_tickers)
    weights = derive_weights(evals, metric)

    tuned_cfg = _with_weights(cfg, weights)
    return OptimizeResult(
        metric=metric,
        split_date=split,
        weights=weights,
        train_baseline=Backtester(cfg).run(train, passed_tickers),
        train_tuned=Backtester(tuned_cfg).run(train, passed_tickers),
        test_baseline=Backtester(cfg).run(test, passed_tickers),
        test_tuned=Backtester(tuned_cfg).run(test, passed_tickers),
    )
