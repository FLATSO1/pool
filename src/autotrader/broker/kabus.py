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

# 信用種別（trade_type="margin"）→ kabuステーション MarginTradeType コード
# 1=制度信用, 2=一般信用(長期), 3=一般信用(デイトレ/日計り)
_MARGIN_TYPE_CODE: dict[str, int] = {"system": 1, "general": 2, "day": 3}


class KabusBroker(Broker):
    def __init__(
        self,
        api_password: str,
        base_url: str = "http://localhost:18080/kabusapi",
        trade_password: str | None = None,
        exchange: int = 1,            # 1=東証
        account_type: int = 4,        # 4=特定
        trade_type: str = "cash",     # "cash"=現物 / "margin"=信用
        margin_trade_type: str = "day",  # "system" | "general" | "day"
        timeout: float = 10.0,
    ):
        if not api_password:
            raise ValueError("kabuステーションAPIパスワードが未設定です")
        self._base_url = base_url.rstrip("/")
        self._api_password = api_password
        self._trade_password = trade_password
        self._exchange = exchange
        self._account_type = account_type
        self._trade_type = trade_type
        self._margin_trade_type = margin_trade_type
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

    def connect(self) -> None:
        """明示的に認証を行う（接続チェック用の公開メソッド）。"""
        self._authenticate()

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

    def _build_order_payload(self, order: Order) -> dict:
        """/sendorder に渡す注文ペイロードを構築する（ネットワーク非依存・テスト可能）。

        - 現物（trade_type="cash"）: CashMargin=1。買=お預り金(DelivType2)、売=0。
        - 信用（trade_type="margin"）: 買=新規建て(CashMargin2,DelivType0)、
          売=返済(CashMargin3,DelivType2)。MarginTradeType は margin_trade_type で決定。
          このアプリは買って→売って決済する建玉のみ扱うため、売り=返済とみなす。
        """
        side_code = "2" if order.side == Side.BUY else "1"  # 1=売, 2=買
        front_order_type = 10 if order.limit_price is None else 20  # 10=成行,20=指値
        price = 0 if order.limit_price is None else float(order.limit_price)

        payload: dict = {
            "Password": self._trade_password,
            "Symbol": self._symbol(order.ticker),
            "Exchange": self._exchange,
            "SecurityType": 1,            # 株式
            "Side": side_code,
            "AccountType": self._account_type,
            "Qty": order.quantity,
            "FrontOrderType": front_order_type,
            "Price": price,
            "ExpireDay": 0,               # 当日
        }

        if self._trade_type == "margin":
            payload["MarginTradeType"] = _MARGIN_TYPE_CODE.get(
                self._margin_trade_type, 3
            )
            if order.side == Side.BUY:          # 新規建て
                payload["CashMargin"] = 2
                payload["DelivType"] = 0
            else:                                # 返済
                payload["CashMargin"] = 3
                payload["DelivType"] = 2
                payload["FundType"] = "  "       # 信用は半角スペース2文字
                payload["ClosePositionOrder"] = 0  # 建日の古い順から返済
        else:                                    # 現物
            payload["CashMargin"] = 1
            payload["DelivType"] = 2 if order.side == Side.BUY else 0

        return payload

    def submit(self, order: Order) -> OrderResult:
        if not self._trade_password:
            return OrderResult(
                False, message="取引パスワード(KABUS_TRADE_PASSWORD)が未設定です"
            )
        payload = self._build_order_payload(order)
        try:
            data = self._request("POST", "/sendorder", json=payload)
        except requests.RequestException as exc:
            return OrderResult(False, message=f"発注リクエスト失敗: {exc}")

        if data.get("Result") == 0:
            return OrderResult(
                True, order_id=str(data.get("OrderId", "")), message="発注受付（ライブ）"
            )
        return OrderResult(False, message=f"発注拒否: {data}")

    def board(self, ticker: str) -> dict | None:
        """板情報（気配値・数量）の生データを返す。"""
        symbol = f"{self._symbol(ticker)}@{self._exchange}"
        try:
            return self._request("GET", f"/board/{symbol}")
        except requests.RequestException as exc:
            log.warning("板情報取得失敗 %s: %s", ticker, exc)
            return None

    def quote(self, ticker: str) -> float | None:
        """現在値（板情報の CurrentPrice）。"""
        data = self.board(ticker)
        return data.get("CurrentPrice") if data else None

    def positions(self) -> dict[str, Position]:
        # product: 1=現物 / 2=信用。取引区分に合わせて建玉を取得する。
        product = 2 if self._trade_type == "margin" else 1
        try:
            data = self._request("GET", "/positions", params={"product": product})
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
