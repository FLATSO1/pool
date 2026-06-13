"""戦略エンジンとバックテストのテスト。"""

from __future__ import annotations

from autotrader.backtest.backtester import Backtester
from autotrader.config import Config, SentimentConfig
from autotrader.data.fundamentals import Fundamentals
from autotrader.strategy.engine import StrategyEngine


def _config_no_sentiment() -> Config:
    cfg = Config()
    cfg.universe = ["TEST.T"]
    cfg.sentiment = SentimentConfig(enabled=False)
    return cfg


def test_engine_buy_on_uptrend_with_good_fundamentals(uptrend_ohlcv):
    cfg = _config_no_sentiment()
    cfg.trading.buy_score_threshold = 0.2
    engine = StrategyEngine(cfg)
    good = Fundamentals("TEST.T", per=10.0, roe=0.18, debt_to_equity=0.4)
    d = engine.evaluate("TEST.T", uptrend_ohlcv, good, [], equity=1_000_000.0)
    assert d.action == "BUY"
    assert d.quantity > 0
    assert d.combined_score > 0


def test_engine_no_buy_when_fundamentals_fail(uptrend_ohlcv):
    cfg = _config_no_sentiment()
    cfg.trading.buy_score_threshold = 0.2
    engine = StrategyEngine(cfg)
    bad = Fundamentals("TEST.T", per=99.0, roe=0.01, debt_to_equity=5.0)
    d = engine.evaluate("TEST.T", uptrend_ohlcv, bad, [], equity=1_000_000.0)
    # ファンダ不通過なので買わない
    assert d.action != "BUY"


def test_engine_sell_on_downtrend(downtrend_ohlcv):
    cfg = _config_no_sentiment()
    engine = StrategyEngine(cfg)
    d = engine.evaluate("TEST.T", downtrend_ohlcv, None, [], equity=1_000_000.0)
    assert d.action == "SELL"


def test_position_sizing_respects_budget(uptrend_ohlcv):
    cfg = _config_no_sentiment()
    cfg.trading.position_pct = 0.2
    cfg.trading.buy_score_threshold = 0.2
    engine = StrategyEngine(cfg)
    good = Fundamentals("TEST.T", per=10.0, roe=0.18, debt_to_equity=0.4)
    d = engine.evaluate("TEST.T", uptrend_ohlcv, good, [], equity=1_000_000.0)
    if d.action == "BUY" and d.price:
        # 配分予算（20万円）を超えない
        assert d.quantity * d.price <= 1_000_000.0 * 0.2 + d.price * 100


def test_backtest_runs_and_produces_curve(uptrend_ohlcv):
    cfg = _config_no_sentiment()
    cfg.trading.buy_score_threshold = 0.2
    result = Backtester(cfg).run({"TEST.T": uptrend_ohlcv})
    assert len(result.equity_curve) == len(uptrend_ohlcv)
    assert result.initial_cash == cfg.trading.cash
    # 上昇トレンドなのでトレードが発生し得る
    assert isinstance(result.total_return, float)
    # サマリ文字列が壊れていないこと
    assert "トータルリターン" in result.summary()


def test_backtest_empty_input():
    cfg = _config_no_sentiment()
    result = Backtester(cfg).run({})
    assert result.final_equity == 0.0
