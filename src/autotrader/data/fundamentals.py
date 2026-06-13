"""ファンダメンタル指標の取得。

yfinance の Ticker.info から主要指標を取り出して正規化する。
取得失敗時は欠損（None）を許容し、後段のスコアリングで吸収する。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class Fundamentals:
    ticker: str
    per: float | None = None            # 株価収益率 (trailingPE)
    pbr: float | None = None            # 株価純資産倍率 (priceToBook)
    roe: float | None = None            # 自己資本利益率 (returnOnEquity)
    profit_margin: float | None = None  # 純利益率 (profitMargins)
    revenue_growth: float | None = None # 売上成長率 (revenueGrowth)
    debt_to_equity: float | None = None # D/E（%表記を倍率へ正規化）
    dividend_yield: float | None = None # 配当利回り
    market_cap: float | None = None     # 時価総額


def fetch_fundamentals(ticker: str) -> Fundamentals:
    try:
        import yfinance as yf
    except ImportError as exc:  # pragma: no cover - 環境依存
        raise RuntimeError(
            "yfinance が未導入です。`pip install yfinance` を実行してください。"
        ) from exc

    try:
        info = yf.Ticker(ticker).info or {}
    except Exception as exc:  # pragma: no cover - ネットワーク依存
        log.warning("ファンダメンタル取得失敗 %s: %s", ticker, exc)
        info = {}

    de = info.get("debtToEquity")
    # yfinance の debtToEquity は % 表記（例: 150 = 1.5倍）なので正規化
    if de is not None:
        de = de / 100.0

    return Fundamentals(
        ticker=ticker,
        per=_num(info.get("trailingPE")),
        pbr=_num(info.get("priceToBook")),
        roe=_num(info.get("returnOnEquity")),
        profit_margin=_num(info.get("profitMargins")),
        revenue_growth=_num(info.get("revenueGrowth")),
        debt_to_equity=_num(de),
        dividend_yield=_num(info.get("dividendYield")),
        market_cap=_num(info.get("marketCap")),
    )


def _num(v) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        # NaN を除外
        if f != f:  # noqa: PLR0124 - NaN チェック
            return None
        return f
    except (TypeError, ValueError):
        return None
