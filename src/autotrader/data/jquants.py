"""J-Quants API（JPX公式）からヒストリカル日足を取得する。

GUI自動操作（マウス座標でSBIソフトを操作）に代わる、安定したHTTP取得経路。
取得したデータは local_store が読めるCSV形式でローカルに保存し、
以降は data.source="local"/"auto" でそのまま使う。

認証:
  - JQUANTS_REFRESH_TOKEN があればそれを使う（推奨）
  - 無ければ JQUANTS_MAILADDRESS / JQUANTS_PASSWORD でリフレッシュトークンを取得
API仕様: https://jpx.gitbook.io/j-quants-ja
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import requests

from ..logging_setup import get_logger

log = get_logger(__name__)

_BASE = "https://api.jquants.com/v1"


class JQuantsError(RuntimeError):
    pass


class JQuantsClient:
    def __init__(
        self,
        refresh_token: str | None = None,
        mailaddress: str | None = None,
        password: str | None = None,
        base_url: str = _BASE,
        timeout: float = 30.0,
        session: requests.Session | None = None,
    ) -> None:
        self._refresh_token = refresh_token
        self._mailaddress = mailaddress
        self._password = password
        self._base = base_url.rstrip("/")
        self._timeout = timeout
        self._session = session or requests.Session()
        self._id_token: str | None = None

    # -- 認証 ------------------------------------------------------------
    def _ensure_refresh_token(self) -> str:
        if self._refresh_token:
            return self._refresh_token
        if not (self._mailaddress and self._password):
            raise JQuantsError(
                "J-Quantsの認証情報がありません（JQUANTS_REFRESH_TOKEN または "
                "JQUANTS_MAILADDRESS/JQUANTS_PASSWORD を設定してください）"
            )
        r = self._session.post(
            f"{self._base}/token/auth_user",
            json={"mailaddress": self._mailaddress, "password": self._password},
            timeout=self._timeout,
        )
        r.raise_for_status()
        token = r.json().get("refreshToken")
        if not token:
            raise JQuantsError("リフレッシュトークンの取得に失敗しました")
        self._refresh_token = token
        return token

    def _ensure_id_token(self) -> str:
        if self._id_token:
            return self._id_token
        refresh = self._ensure_refresh_token()
        r = self._session.post(
            f"{self._base}/token/auth_refresh",
            params={"refreshtoken": refresh},
            timeout=self._timeout,
        )
        r.raise_for_status()
        token = r.json().get("idToken")
        if not token:
            raise JQuantsError("IDトークンの取得に失敗しました")
        self._id_token = token
        return token

    # -- データ取得 ------------------------------------------------------
    def daily_quotes(
        self, code: str, from_: str | None = None, to: str | None = None
    ) -> pd.DataFrame:
        """1銘柄の日足を取得して正規化（open/high/low/close/volume）。"""
        headers = {"Authorization": f"Bearer {self._ensure_id_token()}"}
        params: dict[str, str] = {"code": _jq_code(code)}
        if from_:
            params["from"] = from_
        if to:
            params["to"] = to

        rows: list[dict] = []
        pagination_key: str | None = None
        while True:
            if pagination_key:
                params["pagination_key"] = pagination_key
            r = self._session.get(
                f"{self._base}/prices/daily_quotes",
                params=params,
                headers=headers,
                timeout=self._timeout,
            )
            r.raise_for_status()
            payload = r.json()
            rows.extend(payload.get("daily_quotes", []))
            pagination_key = payload.get("pagination_key")
            if not pagination_key:
                break

        return _normalize(rows)

    def save_csv(
        self, code: str, directory: str | Path, from_: str | None = None,
        to: str | None = None,
    ) -> int:
        """日足を取得し local_store が読めるCSVで保存。保存行数を返す。"""
        df = self.daily_quotes(code, from_=from_, to=to)
        if df.empty:
            return 0
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        out = df.reset_index().rename(columns={"index": "date"})
        out.to_csv(directory / f"{_code(code)}.csv", index=False, encoding="utf-8")
        return len(df)


def _code(code: str) -> str:
    return code.split(".")[0].strip()


def _jq_code(code: str) -> str:
    """J-Quantsは5桁コード（末尾0）も4桁も受け付ける。4桁に正規化して渡す。"""
    return _code(code)


def _pick(row: dict, *keys: str):
    for k in keys:
        if row.get(k) is not None:
            return row[k]
    return None


def _normalize(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    recs = []
    for row in rows:
        # 分割調整済み(Adjustment*)を優先、無ければ素の値
        recs.append(
            {
                "date": row.get("Date"),
                "open": _pick(row, "AdjustmentOpen", "Open"),
                "high": _pick(row, "AdjustmentHigh", "High"),
                "low": _pick(row, "AdjustmentLow", "Low"),
                "close": _pick(row, "AdjustmentClose", "Close"),
                "volume": _pick(row, "AdjustmentVolume", "Volume"),
            }
        )
    df = pd.DataFrame(recs)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["date", "close"]).set_index("date").sort_index()
    return df[["open", "high", "low", "close", "volume"]]
