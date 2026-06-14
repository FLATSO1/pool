"""営業日判定のテスト。"""

from __future__ import annotations

import datetime as dt

from autotrader import market_calendar as mc


def test_weekend_is_not_trading_day():
    assert not mc.is_trading_day(dt.date(2026, 6, 13))  # 土
    assert not mc.is_trading_day(dt.date(2026, 6, 14))  # 日
    assert mc.describe_non_trading(dt.date(2026, 6, 13)) == "土曜日"
    assert mc.describe_non_trading(dt.date(2026, 6, 14)) == "日曜日"


def test_year_end_holidays():
    assert not mc.is_trading_day(dt.date(2025, 12, 31))
    assert not mc.is_trading_day(dt.date(2026, 1, 1))
    assert not mc.is_trading_day(dt.date(2026, 1, 3))
    assert mc.describe_non_trading(dt.date(2026, 1, 2)) == "年末年始休場"


def test_normal_weekday_is_trading_day():
    # 2026-06-16 は火曜・6月に日本の祝日なし → 取引日
    d = dt.date(2026, 6, 16)
    assert mc.is_trading_day(d)
    assert mc.describe_non_trading(d) == ""


def test_default_today_runs():
    # 引数なしでも例外なく bool を返す
    assert isinstance(mc.is_trading_day(), bool)
