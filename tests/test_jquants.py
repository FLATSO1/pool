"""J-Quantsクライアント（認証・取得・正規化・CSV保存）のテスト。HTTPはフェイク。"""

from __future__ import annotations

import pandas as pd

from autotrader.data.jquants import JQuantsClient
from autotrader.data.local_store import LocalStore


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeSession:
    """auth_refresh と daily_quotes を返すフェイク。ページングも再現。"""

    def __init__(self, pages):
        self._pages = pages
        self.calls = []

    def post(self, url, **kw):
        if url.endswith("/token/auth_refresh"):
            return _Resp({"idToken": "ID123"})
        if url.endswith("/token/auth_user"):
            return _Resp({"refreshToken": "RT123"})
        raise AssertionError(url)

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((params or {}).get("pagination_key"))
        idx = len(self.calls) - 1
        return _Resp(self._pages[idx])


def _quote(date, close, adj=None):
    row = {"Date": date, "Open": close, "High": close, "Low": close,
           "Close": close, "Volume": 1000}
    if adj is not None:
        row["AdjustmentClose"] = adj
    return row


def test_daily_quotes_with_pagination():
    pages = [
        {"daily_quotes": [_quote("2024-01-04", 2500)], "pagination_key": "k1"},
        {"daily_quotes": [_quote("2024-01-05", 2600)]},
    ]
    sess = _FakeSession(pages)
    client = JQuantsClient(refresh_token="RT123", session=sess)
    df = client.daily_quotes("7203.T", from_="2024-01-01")
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 2
    assert df["close"].iloc[-1] == 2600
    assert isinstance(df.index, pd.DatetimeIndex)
    # 2ページ目はpagination_keyを渡して呼ばれている
    assert sess.calls == [None, "k1"]


def test_adjustment_close_preferred():
    pages = [{"daily_quotes": [_quote("2024-01-04", 5000, adj=2500)]}]
    client = JQuantsClient(refresh_token="RT", session=_FakeSession(pages))
    df = client.daily_quotes("7203")
    assert df["close"].iloc[0] == 2500  # 調整済みを優先


def test_auth_user_flow_without_refresh_token():
    pages = [{"daily_quotes": [_quote("2024-01-04", 100)]}]
    sess = _FakeSession(pages)
    client = JQuantsClient(mailaddress="a@b.c", password="pw", session=sess)
    df = client.daily_quotes("1234")
    assert len(df) == 1  # mail/passからトークン取得→取得まで通る


def test_save_csv_roundtrip(tmp_path):
    pages = [{"daily_quotes": [_quote("2024-01-04", 2500), _quote("2024-01-05", 2600)]}]
    client = JQuantsClient(refresh_token="RT", session=_FakeSession(pages))
    n = client.save_csv("7203.T", tmp_path)
    assert n == 2
    # local_store が読み戻せること
    store = LocalStore(tmp_path)
    df = store.load("7203.T")
    assert len(df) == 2
    assert df["close"].iloc[-1] == 2600
