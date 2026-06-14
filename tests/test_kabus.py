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
