"""イベント駆動の簡易バックテスト。

複数銘柄の過去OHLCVに対し、テクニカルスコア（＋ファンダ足切りの静的適用）
で日次にリバランスする。センチメントは過去再現が難しいため既定では使わない。
損切り/利確、手数料、資金配分・同時保有数の上限を考慮する。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..analysis.technical import compute_indicators, score_frame
from ..broker.base import Position
from ..config import Config
from ..logging_setup import get_logger
from ..strategy.engine import LOT_SIZE

log = get_logger(__name__)


@dataclass
class Trade:
    date: pd.Timestamp
    ticker: str
    side: str
    quantity: int
    price: float
    reason: str


@dataclass
class BacktestResult:
    equity_curve: pd.Series
    trades: list[Trade] = field(default_factory=list)
    initial_cash: float = 0.0
    benchmark_return: float = 0.0  # 全候補を均等に買い持ちした場合のリターン

    @property
    def final_equity(self) -> float:
        return float(self.equity_curve.iloc[-1]) if len(self.equity_curve) else 0.0

    @property
    def total_return(self) -> float:
        if self.initial_cash <= 0 or self.equity_curve.empty:
            return 0.0
        return self.final_equity / self.initial_cash - 1.0

    def max_drawdown(self) -> float:
        if self.equity_curve.empty:
            return 0.0
        running_max = self.equity_curve.cummax()
        dd = self.equity_curve / running_max - 1.0
        return float(dd.min())

    def sharpe(self, periods_per_year: int = 252) -> float:
        if len(self.equity_curve) < 2:
            return 0.0
        rets = self.equity_curve.pct_change().dropna()
        if rets.std() == 0:
            return 0.0
        return float(np.sqrt(periods_per_year) * rets.mean() / rets.std())

    def excess_return(self) -> float:
        """戦略リターン − バイ&ホールド（プラスなら売買が価値を生んだ）。"""
        return self.total_return - self.benchmark_return

    def summary(self) -> str:
        verdict = (
            "✅ バイ&ホールドを上回った"
            if self.excess_return() > 0
            else "⚠️ バイ&ホールドに負けた（売買の価値が出ていない）"
        )
        return (
            f"初期資金: {self.initial_cash:,.0f}円\n"
            f"最終資産: {self.final_equity:,.0f}円\n"
            f"トータルリターン: {self.total_return * 100:+.2f}%\n"
            f"バイ&ホールド比較: {self.benchmark_return * 100:+.2f}%"
            f"（差 {self.excess_return() * 100:+.2f}%）\n"
            f"  → {verdict}\n"
            f"最大ドローダウン: {self.max_drawdown() * 100:.2f}%\n"
            f"シャープレシオ: {self.sharpe():.2f}\n"
            f"約定回数: {len(self.trades)}"
        )


class Backtester:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def run(
        self,
        ohlcv: dict[str, pd.DataFrame],
        passed_tickers: set[str] | None = None,
    ) -> BacktestResult:
        """ohlcv: ticker -> OHLCV DataFrame。

        passed_tickers: ファンダ足切りを通過した銘柄集合（None=全銘柄許可）。
        """
        if not ohlcv:
            return BacktestResult(pd.Series(dtype=float), [], self.cfg.trading.cash)

        # 各銘柄のテクニカルスコア系列と終値を準備
        scores: dict[str, pd.Series] = {}
        closes: dict[str, pd.Series] = {}
        for t, df in ohlcv.items():
            ind = compute_indicators(df, self.cfg.technical)
            scores[t] = score_frame(ind, self.cfg.technical)
            closes[t] = df["close"]

        # 共通の日付インデックス（全銘柄の和集合）
        index = sorted(set().union(*[df.index for df in ohlcv.values()]))
        index = pd.DatetimeIndex(index)

        cash = self.cfg.trading.cash
        positions: dict[str, Position] = {}
        trades: list[Trade] = []
        equity_points: list[float] = []
        t_cfg = self.cfg.trading
        commission = self.cfg.backtest.commission_pct

        def price_on(ticker: str, date) -> float | None:
            s = closes.get(ticker)
            if s is None or date not in s.index:
                return None
            v = s.loc[date]
            return None if pd.isna(v) else float(v)

        for date in index:
            prices = {t: price_on(t, date) for t in ohlcv}
            prices = {t: p for t, p in prices.items() if p is not None}

            # 1) リスク決済（損切り/利確）
            for t in list(positions):
                px = prices.get(t)
                if px is None:
                    continue
                pos = positions[t]
                pnl = (px - pos.avg_price) / pos.avg_price if pos.avg_price else 0.0
                if pnl <= -t_cfg.stop_loss_pct or pnl >= t_cfg.take_profit_pct:
                    cash += px * pos.quantity * (1 - commission)
                    reason = "stop_loss" if pnl < 0 else "take_profit"
                    trades.append(Trade(date, t, "SELL", pos.quantity, px, reason))
                    del positions[t]

            # 2) シグナルに基づく売買
            for t in ohlcv:
                px = prices.get(t)
                if px is None:
                    continue
                sc_series = scores[t]
                if date not in sc_series.index:
                    continue
                score = float(sc_series.loc[date])

                # 売り（保有していてスコアが弱い）
                if t in positions and score <= t_cfg.sell_score_threshold:
                    pos = positions[t]
                    cash += px * pos.quantity * (1 - commission)
                    trades.append(Trade(date, t, "SELL", pos.quantity, px, "signal"))
                    del positions[t]
                    continue

                # 買い
                if (
                    t not in positions
                    and score >= t_cfg.buy_score_threshold
                    and len(positions) < t_cfg.max_positions
                    and (passed_tickers is None or t in passed_tickers)
                ):
                    equity = cash + sum(
                        positions[p].quantity * prices.get(p, positions[p].avg_price)
                        for p in positions
                    )
                    budget = equity * t_cfg.position_pct
                    qty = int(budget // (px * LOT_SIZE)) * LOT_SIZE
                    cost = px * qty * (1 + commission)
                    if qty > 0 and cost <= cash:
                        cash -= cost
                        positions[t] = Position(t, qty, px)
                        trades.append(Trade(date, t, "BUY", qty, px, "signal"))

            # 3) 資産評価
            equity = cash + sum(
                pos.quantity * prices.get(t, pos.avg_price)
                for t, pos in positions.items()
            )
            equity_points.append(equity)

        curve = pd.Series(equity_points, index=index, name="equity")
        benchmark = self._buy_and_hold_return(closes, passed_tickers)
        return BacktestResult(curve, trades, self.cfg.trading.cash, benchmark)

    @staticmethod
    def _buy_and_hold_return(
        closes: dict[str, pd.Series], passed_tickers: set[str] | None
    ) -> float:
        """全候補を均等配分で買い持ちした場合の平均リターン（等加重）。"""
        universe = (
            [t for t in closes if t in passed_tickers]
            if passed_tickers
            else list(closes)
        )
        rets: list[float] = []
        for t in universe:
            s = closes[t].dropna()
            if len(s) >= 2 and s.iloc[0] > 0:
                rets.append(float(s.iloc[-1] / s.iloc[0] - 1.0))
        return sum(rets) / len(rets) if rets else 0.0
