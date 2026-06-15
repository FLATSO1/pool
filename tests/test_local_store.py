"""ローカルヒストリカルCSV読み込みのテスト。"""

from __future__ import annotations

import pandas as pd

from autotrader.data.local_store import LocalStore
from autotrader.data import market_data


def _write_sbi_csv(path, encoding="cp932"):
    """SBI風: 日本語ヘッダ・カンマ区切り桁・cp932。"""
    rows = [
        "日付,始値,高値,安値,終値,出来高",
        "2024/01/04,2500,2550,2480,2540,1,000,000".replace(",000,000", "000000"),
        "2024/01/05,2540,2600,2530,2590,1200000",
        "2024/01/09,2590,2620,2570,2580,900000",
    ]
    path.write_text("\n".join(rows) + "\n", encoding=encoding)


def test_load_japanese_cp932(tmp_path):
    _write_sbi_csv(tmp_path / "7203.csv")
    store = LocalStore(tmp_path)
    df = store.load("7203.T")
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 3
    assert df["close"].iloc[-1] == 2580
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.is_monotonic_increasing


def test_filename_resolution_and_available(tmp_path):
    _write_sbi_csv(tmp_path / "7203.csv")
    store = LocalStore(tmp_path)
    assert store.available("7203.T")
    assert store.available("7203")
    assert not store.available("9999.T")
    assert store.load("9999.T").empty


def test_period_slice(tmp_path):
    idx = pd.date_range("2020-01-01", periods=800, freq="D")
    df = pd.DataFrame(
        {"日付": idx.strftime("%Y-%m-%d"), "始値": 1, "高値": 1, "安値": 1,
         "終値": range(800), "出来高": 100},
    )
    df.to_csv(tmp_path / "1234.csv", index=False, encoding="utf-8-sig")
    store = LocalStore(tmp_path)
    full = store.load("1234.T", period="max")
    assert len(full) == 800
    one_year = store.load("1234.T", period="1y")
    # 直近1年分のみ（おおよそ366行以下）
    assert len(one_year) < len(full)
    assert one_year.index[-1] == full.index[-1]


def test_start_end_filter(tmp_path):
    _write_sbi_csv(tmp_path / "7203.csv")
    store = LocalStore(tmp_path)
    df = store.load("7203.T", start="2024-01-05", end="2024-01-05")
    assert len(df) == 1
    assert df["close"].iloc[0] == 2590


def test_coverage(tmp_path):
    _write_sbi_csv(tmp_path / "7203.csv")
    store = LocalStore(tmp_path)
    rows, d0, d1 = store.coverage("7203.T")
    assert rows == 3
    assert d0 == "2024-01-04"
    assert d1 == "2024-01-09"


def test_market_data_local_source(tmp_path):
    _write_sbi_csv(tmp_path / "7203.csv")
    store = LocalStore(tmp_path)
    try:
        market_data.configure_local_store(store, "local")
        df = market_data.fetch_ohlcv("7203.T", period="max")
        assert len(df) == 3
        # ローカルに無い銘柄は local モードで空（yfinanceに行かない）
        assert market_data.fetch_ohlcv("9999.T").empty
        # 分足はローカル対象外（yfinanceへ行くため、ここでは取得結果は問わない）
    finally:
        market_data.configure_local_store(None, "yfinance")
