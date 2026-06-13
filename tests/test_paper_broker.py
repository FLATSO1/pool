"""ペーパートレード・ブローカーのテスト。"""

from __future__ import annotations

from autotrader.broker.base import Order, Side
from autotrader.broker.paper import PaperBroker


def make_broker(tmp_path, cash=1_000_000.0):
    return PaperBroker(cash=cash, state_path=tmp_path / "acct.json")


def test_buy_reduces_cash_and_adds_position(tmp_path):
    b = make_broker(tmp_path)
    r = b.submit(Order("7203.T", Side.BUY, 100, limit_price=2000.0))
    assert r.ok
    assert b.cash() == 1_000_000.0 - 2000.0 * 100
    assert b.positions()["7203.T"].quantity == 100


def test_buy_insufficient_cash(tmp_path):
    b = make_broker(tmp_path, cash=10_000.0)
    r = b.submit(Order("7203.T", Side.BUY, 100, limit_price=2000.0))
    assert not r.ok
    assert "資金不足" in r.message


def test_sell_increases_cash(tmp_path):
    b = make_broker(tmp_path)
    b.submit(Order("7203.T", Side.BUY, 100, limit_price=2000.0))
    r = b.submit(Order("7203.T", Side.SELL, 100, limit_price=2200.0))
    assert r.ok
    assert "7203.T" not in b.positions()
    # 100株を2000で買い2200で売却 → +20,000円
    assert b.cash() == 1_000_000.0 + 20_000.0


def test_sell_more_than_held(tmp_path):
    b = make_broker(tmp_path)
    b.submit(Order("7203.T", Side.BUY, 100, limit_price=2000.0))
    r = b.submit(Order("7203.T", Side.SELL, 200, limit_price=2200.0))
    assert not r.ok
    assert "保有不足" in r.message


def test_average_price_on_additional_buy(tmp_path):
    b = make_broker(tmp_path)
    b.submit(Order("7203.T", Side.BUY, 100, limit_price=2000.0))
    b.submit(Order("7203.T", Side.BUY, 100, limit_price=3000.0))
    pos = b.positions()["7203.T"]
    assert pos.quantity == 200
    assert pos.avg_price == 2500.0


def test_state_persists_across_instances(tmp_path):
    state = tmp_path / "acct.json"
    b1 = PaperBroker(cash=500_000.0, state_path=state)
    b1.submit(Order("6758.T", Side.BUY, 100, limit_price=1000.0))
    b2 = PaperBroker(cash=500_000.0, state_path=state)
    assert b2.positions()["6758.T"].quantity == 100
    assert b2.cash() == 400_000.0


def test_price_provider_for_market_order(tmp_path):
    prices = {"9984.T": 5000.0}
    b = PaperBroker(
        cash=1_000_000.0,
        state_path=tmp_path / "acct.json",
        price_provider=lambda t: prices.get(t),
    )
    r = b.submit(Order("9984.T", Side.BUY, 100))  # 成行
    assert r.ok
    assert r.filled_price == 5000.0
