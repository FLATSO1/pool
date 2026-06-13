"""auカブコム証券 kabuステーションAPI アダプタ（ライブ発注）。

kabuステーション（Windowsアプリ）がローカルで稼働し、REST API が
http://localhost:18080/kabusapi （本番）で待ち受けている前提。

⚠️ これは実弾の発注を行うアダプタです。`Config.live_enabled()` が True の
ときだけ生成・使用してください（CLI側でガードしています）。

API仕様: https://kabucom.github.io/kabusapi/ptal/
"""

from __future__ import annotations

import requests

from ..logging_setup import get_logger
from .base import AccountSnapshot, Broker, Order, OrderResult, Position, Side

log = get_logger(__name__)


class KabusBroker(Broker):
    def __init__(
        self,
        api_password: str,
        base_url: str = "http://localhost:18080/kabusapi",
        trade_password: str | None = None,
        exchange: int = 1,            # 1=東証
        account_type: int = 4,        # 4=特定
        timeout: float = 10.0,
    ):
        if not api_password:
            raise ValueError("kabuステーションAPIパスワードが未設定です")
        self._base_url = base_url.rstrip("/")
        self._api_password = api_password
        self._trade_password = trade_password
        self._exchange = exchange
        self._account_type = account_type
        self._timeout = timeout
        self._token: str | None = None

    # --- 認証 ---

    def _authenticate(self) -> str:
        resp = requests.post(
            f"{self._base_url}/token",
            json={"APIPassword": self._api_password},
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("ResultCode") != 0:
            raise RuntimeError(f"kabus 認証失敗: {data}")
        self._token = data["Token"]
        log.info("kabuステーションAPI 認証成功")
        return self._token

    def _headers(self) -> dict[str, str]:
        if self._token is None:
            self._authenticate()
        return {"Content-Type": "application/json", "X-API-KEY": self._token or ""}

    def _request(self, method: str, path: str, **kwargs):
        url = f"{self._base_url}{path}"
        resp = requests.request(
            method, url, headers=self._headers(), timeout=self._timeout, **kwargs
        )
        # トークン失効時は1回だけ再認証してリトライ
        if resp.status_code == 401:
            self._authenticate()
            resp = requests.request(
                method, url, headers=self._headers(), timeout=self._timeout, **kwargs
            )
        resp.raise_for_status()
        return resp.json()

    # --- ヘルパ ---

    @staticmethod
    def _symbol(ticker: str) -> str:
        """ "7203.T" -> "7203" """
        return ticker.split(".")[0]

    # --- Broker インターフェース ---

    def submit(self, order: Order) -> OrderResult:
        if not self._trade_password:
            return OrderResult(
                False, message="取引パスワード(KABUS_TRADE_PASSWORD)が未設定です"
            )
        side_code = "2" if order.side == Side.BUY else "1"  # 1=売, 2=買
        front_order_type = 10 if order.limit_price is None else 20  # 10=成行,20=指値
        price = 0 if order.limit_price is None else float(order.limit_price)
        deliv_type = 2 if order.side == Side.BUY else 0  # 買: お預り金, 売: 0

        payload = {
            "Password": self._trade_password,
            "Symbol": self._symbol(order.ticker),
            "Exchange": self._exchange,
            "SecurityType": 1,            # 株式
            "Side": side_code,
            "CashMargin": 1,              # 現物
            "DelivType": deliv_type,
            "AccountType": self._account_type,
            "Qty": order.quantity,
            "FrontOrderType": front_order_type,
            "Price": price,
            "ExpireDay": 0,               # 当日
        }
        try:
            data = self._request("POST", "/sendorder", json=payload)
        except requests.RequestException as exc:
            return OrderResult(False, message=f"発注リクエスト失敗: {exc}")

        if data.get("Result") == 0:
            return OrderResult(
                True, order_id=str(data.get("OrderId", "")), message="発注受付（ライブ）"
            )
        return OrderResult(False, message=f"発注拒否: {data}")

    def quote(self, ticker: str) -> float | None:
        """現在値（板情報の CurrentPrice）。"""
        symbol = f"{self._symbol(ticker)}@{self._exchange}"
        try:
            data = self._request("GET", f"/board/{symbol}")
        except requests.RequestException as exc:
            log.warning("板情報取得失敗 %s: %s", ticker, exc)
            return None
        return data.get("CurrentPrice")

    def positions(self) -> dict[str, Position]:
        try:
            data = self._request("GET", "/positions", params={"product": 1})
        except requests.RequestException as exc:
            log.warning("ポジション取得失敗: %s", exc)
            return {}
        out: dict[str, Position] = {}
        for p in data or []:
            symbol = str(p.get("Symbol", ""))
            ticker = f"{symbol}.T"
            qty = int(p.get("LeavesQty", 0) or 0)
            price = float(p.get("Price", 0) or 0)
            if qty > 0:
                out[ticker] = Position(ticker, qty, price)
        return out

    def cash(self) -> float:
        try:
            data = self._request("GET", "/wallet/cash")
        except requests.RequestException as exc:
            log.warning("買付余力取得失敗: %s", exc)
            return 0.0
        return float(data.get("StockAccountWallet", 0) or 0)

    def snapshot(self) -> AccountSnapshot:
        return AccountSnapshot(cash=self.cash(), positions=self.positions())
