"""kabuステーションAPIアダプタのテスト（ネットワーク不要な部分のみ）。"""

from __future__ import annotations

import pytest

from autotrader.broker.base import Order, Side
from autotrader.broker.kabus import KabusBroker


def test_requires_api_password():
    with pytest.raises(ValueError):
        KabusBroker(api_password="")


def test_symbol_conversion():
    assert KabusBroker._symbol("7203.T") == "7203"
    assert KabusBroker._symbol("6758") == "6758"


def test_submit_without_trade_password_is_rejected_offline():
    # 取引パスワード未設定なら、ネットワークに触れる前に拒否される
    broker = KabusBroker(api_password="dummy", trade_password=None)
    result = broker.submit(Order("7203.T", Side.BUY, 100, limit_price=2000.0))
    assert not result.ok
    assert "取引パスワード" in result.message


# --- 注文ペイロード構築（現物/信用） ---------------------------------------

def test_cash_buy_payload():
    broker = KabusBroker(api_password="dummy", trade_password="pw", trade_type="cash")
    p = broker._build_order_payload(Order("7203.T", Side.BUY, 100, limit_price=2000.0))
    assert p["Symbol"] == "7203"
    assert p["Side"] == "2"            # 買
    assert p["CashMargin"] == 1        # 現物
    assert p["DelivType"] == 2         # 買=お預り金
    assert p["FrontOrderType"] == 20   # 指値
    assert p["Price"] == 2000.0
    assert "MarginTradeType" not in p


def test_cash_sell_payload_is_market_when_no_limit():
    broker = KabusBroker(api_password="dummy", trade_password="pw", trade_type="cash")
    p = broker._build_order_payload(Order("6758.T", Side.SELL, 200, limit_price=None))
    assert p["Side"] == "1"            # 売
    assert p["CashMargin"] == 1
    assert p["DelivType"] == 0         # 現物売
    assert p["FrontOrderType"] == 10   # 成行
    assert p["Price"] == 0


def test_margin_buy_is_new_open_position():
    broker = KabusBroker(
        api_password="dummy", trade_password="pw",
        trade_type="margin", margin_trade_type="day",
    )
    p = broker._build_order_payload(Order("7203.T", Side.BUY, 100, limit_price=2500.0))
    assert p["CashMargin"] == 2        # 新規建て
    assert p["DelivType"] == 0
    assert p["MarginTradeType"] == 3   # day=一般(デイトレ)
    assert "ClosePositionOrder" not in p


def test_margin_sell_is_close_position():
    broker = KabusBroker(
        api_password="dummy", trade_password="pw",
        trade_type="margin", margin_trade_type="system",
    )
    p = broker._build_order_payload(Order("7203.T", Side.SELL, 100, limit_price=None))
    assert p["CashMargin"] == 3        # 返済
    assert p["DelivType"] == 2
    assert p["MarginTradeType"] == 1   # system=制度
    assert p["FundType"] == "  "
    assert p["ClosePositionOrder"] == 0


def test_margin_trade_type_defaults_to_day_on_unknown():
    broker = KabusBroker(
        api_password="dummy", trade_password="pw",
        trade_type="margin", margin_trade_type="bogus",
    )
    p = broker._build_order_payload(Order("7203.T", Side.BUY, 100))
    assert p["MarginTradeType"] == 3   # 不明値は day(3) にフォールバック
