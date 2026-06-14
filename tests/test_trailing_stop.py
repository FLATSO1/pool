"""トレイリングストップ（追従型損切り）のテスト。"""

from __future__ import annotations

from autotrader.broker.base import Position
from autotrader.config import TradingConfig
from autotrader.portfolio import check_risk_exits, update_peaks


def _pos(avg=1000.0, qty=100):
    return {"7203.T": Position("7203.T", qty, avg)}


def test_trailing_stop_triggers_on_pullback_from_peak():
    cfg = TradingConfig(stop_loss_pct=0.0, take_profit_pct=0.0, trailing_stop_pct=0.10)
    pos = _pos(avg=1000.0)
    # 高値1500まで上昇 → 10%下げの1350割れで手仕舞い
    peaks = {"7203.T": 1500.0}
    exits = check_risk_exits(pos, {"7203.T": 1340.0}, cfg, peaks)
    assert len(exits) == 1
    assert exits[0].reason == "trailing_stop"


def test_trailing_stop_holds_while_rising():
    cfg = TradingConfig(stop_loss_pct=0.0, take_profit_pct=0.0, trailing_stop_pct=0.10)
    pos = _pos(avg=1000.0)
    peaks = {"7203.T": 1500.0}
    # 1400は高値1500から-6.7%（10%以内）→ まだ売らない
    exits = check_risk_exits(pos, {"7203.T": 1400.0}, cfg, peaks)
    assert exits == []


def test_take_profit_zero_is_disabled():
    cfg = TradingConfig(stop_loss_pct=0.07, take_profit_pct=0.0, trailing_stop_pct=0.0)
    pos = _pos(avg=1000.0)
    # +50%でも take_profit=0 なら利確しない
    assert check_risk_exits(pos, {"7203.T": 1500.0}, cfg) == []


def test_update_peaks_tracks_high_and_drops_sold():
    pos = _pos(avg=1000.0)
    peaks = update_peaks({"7203.T": 1200.0}, pos, {"7203.T": 1300.0})
    assert peaks["7203.T"] == 1300.0  # 高値更新
    # 保有していない銘柄は消える
    peaks2 = update_peaks({"6758.T": 999.0}, pos, {"7203.T": 1300.0})
    assert "6758.T" not in peaks2
    assert "7203.T" in peaks2
