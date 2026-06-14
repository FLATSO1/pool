"""ニュース/SNS的な見出しの取得。

一次ソースとして yfinance の `.news`、補助として Google ニュースのRSSを使う。
（X/Twitter等のSNSは公式APIが有料・規約が厳しいため、RSSベースの
公開ニュースをマクロ・センチメントの代理として扱う設計。後から
SNSコネクタを news ソースとして差し込めるよう、戻り値は共通形式。）
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from urllib.parse import quote

import requests

from ..logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class Headline:
    title: str
    publisher: str
    published_at: dt.datetime | None
    link: str = ""

    def is_recent(self, days: int) -> bool:
        if self.published_at is None:
            return True
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
        ts = self.published_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=dt.timezone.utc)
        return ts >= cutoff


def fetch_headlines(
    ticker: str, lookback_days: int = 7, limit: int = 15
) -> list[Headline]:
    """銘柄に関連する見出しを取得（yfinance + Google News RSS をマージ）。"""
    headlines: list[Headline] = []
    headlines.extend(_from_yfinance(ticker))
    if len(headlines) < limit:
        headlines.extend(_from_google_news(ticker))

    # 期間でフィルタ → 重複タイトル除去 → 件数制限
    seen: set[str] = set()
    result: list[Headline] = []
    for h in headlines:
        if not h.is_recent(lookback_days):
            continue
        key = h.title.strip().lower()
        if key in seen or not key:
            continue
        seen.add(key)
        result.append(h)
        if len(result) >= limit:
            break
    return result


def _from_yfinance(ticker: str) -> list[Headline]:
    try:
        import yfinance as yf
    except ImportError:
        return []
    try:
        raw = yf.Ticker(ticker).news or []
    except Exception as exc:  # pragma: no cover - ネットワーク依存
        log.debug("yfinance news 取得失敗 %s: %s", ticker, exc)
        return []

    out: list[Headline] = []
    for item in raw:
        # yfinance の news スキーマは変動するため複数キーに対応
        content = item.get("content", item)
        title = content.get("title") or item.get("title") or ""
        if not title:
            continue
        pub = (
            (content.get("provider") or {}).get("displayName")
            or item.get("publisher")
            or "yfinance"
        )
        ts = _parse_ts(content.get("pubDate") or item.get("providerPublishTime"))
        link = (content.get("canonicalUrl") or {}).get("url") or item.get("link", "")
        out.append(Headline(title=title, publisher=pub, published_at=ts, link=link))
    return out


def _from_google_news(ticker: str) -> list[Headline]:
    """Google ニュースRSSから日本語ニュースを取得（依存なしの軽量XMLパース）。"""
    query = ticker.replace(".T", "") + " 株"
    url = (
        "https://news.google.com/rss/search?q="
        + quote(query)
        + "&hl=ja&gl=JP&ceid=JP:ja"
    )
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "autotrader/0.1"})
        resp.raise_for_status()
    except requests.RequestException as exc:  # pragma: no cover - ネットワーク依存
        log.debug("Google News RSS 取得失敗 %s: %s", ticker, exc)
        return []

    return _parse_rss(resp.text)


def _parse_rss(xml_text: str) -> list[Headline]:
    import xml.etree.ElementTree as ET

    out: list[Headline] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        source = item.findtext("source") or "GoogleNews"
        ts = _parse_ts(item.findtext("pubDate"))
        link = item.findtext("link") or ""
        out.append(Headline(title=title, publisher=source, published_at=ts, link=link))
    return out


def _parse_ts(value) -> dt.datetime | None:
    if value is None:
        return None
    # UNIXエポック秒
    if isinstance(value, (int, float)):
        try:
            return dt.datetime.fromtimestamp(value, tz=dt.timezone.utc)
        except (ValueError, OSError):
            return None
    # ISO8601 / RFC822 文字列
    text = str(value)
    for fmt in (None, "%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            if fmt is None:
                return dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
            return dt.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None
