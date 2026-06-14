"""地合いゲート: 市場全体のニュースから相場環境を判定する。

日次で市場全体のニュースを読み、risk_on / neutral / risk_off と
新規買いの強弱バイアス(-1〜+1)を返す。risk_off時は新規買いを抑制できる。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import AdvisorConfig
from ..data.news import Headline, fetch_headlines
from ._llm import call_structured

_SCHEMA = {
    "type": "object",
    "properties": {
        "regime": {
            "type": "string",
            "enum": ["risk_on", "neutral", "risk_off"],
        },
        "bias": {
            "type": "number",
            "description": "新規買いの強弱 -1.0(抑制)〜+1.0(積極)",
        },
        "summary": {"type": "string", "description": "地合いの短い要約（日本語）"},
    },
    "required": ["regime", "bias", "summary"],
    "additionalProperties": False,
}

# 市場全体の地合いを測るための検索ワード（日経平均・マクロ）
_MARKET_QUERIES = ["日経平均", "株式市場 相場", "東証"]


@dataclass
class MarketRegime:
    regime: str          # "risk_on" | "neutral" | "risk_off"
    bias: float          # -1.0〜+1.0
    summary: str
    source: str = "claude"

    def blocks_new_buys(self) -> bool:
        return self.regime == "risk_off"

    def to_dict(self) -> dict:
        return {
            "regime": self.regime,
            "bias": round(self.bias, 3),
            "summary": self.summary,
            "source": self.source,
        }


def assess_market(
    cfg: AdvisorConfig,
    api_key: str | None,
    lookback_days: int = 3,
) -> MarketRegime:
    """市場全体のニュースから地合いを判定する。"""
    if not cfg.enabled or not cfg.regime_enabled:
        return MarketRegime("neutral", 0.0, "地合い判定は無効", "disabled")

    headlines = _collect_market_headlines(lookback_days)
    if not headlines:
        return MarketRegime("neutral", 0.0, "市場ニュースなし", "empty")

    titles = "\n".join(f"- {h.title}" for h in headlines[:20])
    prompt = (
        "あなたは日本株のストラテジストです。以下の市場全体のニュース見出しから、"
        "現在の相場の地合いを判定してください。\n\n"
        f"=== 市場ニュース ===\n{titles}\n\n"
        "regime（risk_on=強気/neutral=中立/risk_off=弱気）、"
        "bias（新規買いの強弱 -1.0〜+1.0）、summary を返してください。"
    )
    data = call_structured(cfg.model, prompt, _SCHEMA, api_key)
    if data is None:
        return MarketRegime("neutral", 0.0, "地合い判定はフォールバック", "fallback")

    try:
        return MarketRegime(
            regime=str(data["regime"]),
            bias=max(-1.0, min(1.0, float(data["bias"]))),
            summary=str(data.get("summary", "")),
            source="claude",
        )
    except (KeyError, ValueError, TypeError):
        return MarketRegime("neutral", 0.0, "地合い判定の解析失敗", "fallback")


def _collect_market_headlines(lookback_days: int) -> list[Headline]:
    seen: set[str] = set()
    out: list[Headline] = []
    for q in _MARKET_QUERIES:
        for h in fetch_headlines(q, lookback_days=lookback_days, limit=10):
            key = h.title.strip().lower()
            if key and key not in seen:
                seen.add(key)
                out.append(h)
    return out
