"""Claudeアドバイザー: 決定論エンジンの売買候補をレビューする。

数値シグナル＋ファンダ＋直近ニュースを踏まえ、候補に対して
go / caution / skip の推奨度、確信度、リスク、平易な説明を返す。
お金を動かす最終判断は決定論側が持ち、Claudeは“助言と説明”に徹する。

APIキー/SDKが無い場合はスコアベースのフォールバックを返す。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import AdvisorConfig
from ..data.news import Headline
from ._llm import call_structured

_SCHEMA = {
    "type": "object",
    "properties": {
        "recommendation": {"type": "string", "enum": ["go", "caution", "skip"]},
        "confidence": {"type": "number", "description": "0.0〜1.0の確信度"},
        "rationale": {"type": "string", "description": "判断理由の短い説明（日本語）"},
        "risks": {
            "type": "array",
            "items": {"type": "string"},
            "description": "留意すべきリスク（日本語）",
        },
    },
    "required": ["recommendation", "confidence", "rationale", "risks"],
    "additionalProperties": False,
}


@dataclass
class AdvisorOpinion:
    ticker: str
    recommendation: str          # "go" | "caution" | "skip"
    confidence: float            # 0.0〜1.0
    rationale: str
    risks: list[str] = field(default_factory=list)
    source: str = "claude"       # "claude" | "fallback"

    def to_dict(self) -> dict:
        return {
            "recommendation": self.recommendation,
            "confidence": round(self.confidence, 3),
            "rationale": self.rationale,
            "risks": self.risks,
            "source": self.source,
        }


def review_candidate(
    ticker: str,
    action: str,
    combined_score: float,
    fundamental_reasons: list[str],
    technical_reasons: list[str],
    sentiment_summary: str,
    headlines: list[Headline],
    cfg: AdvisorConfig,
    api_key: str | None,
) -> AdvisorOpinion:
    """1つの売買候補をレビューして意見を返す。"""
    if not cfg.enabled:
        return _fallback(ticker, combined_score)

    titles = "\n".join(f"- {h.title}" for h in headlines[:10]) or "（ニュースなし）"
    prompt = (
        f"あなたは日本株の慎重なアナリストです。以下の銘柄に対する自動売買システムの"
        f"売買候補をレビューし、実行してよいか助言してください。\n\n"
        f"【銘柄】{ticker}\n"
        f"【システムの判断】{action}（総合スコア {combined_score:+.2f}）\n"
        f"【ファンダメンタル根拠】{', '.join(fundamental_reasons) or 'なし'}\n"
        f"【テクニカル根拠】{', '.join(technical_reasons) or 'なし'}\n"
        f"【センチメント】{sentiment_summary or 'なし'}\n"
        f"【直近ニュース見出し】\n{titles}\n\n"
        "数値では拾いにくい定性情報（決算の中身・規制・競合・経営・需給）も加味し、"
        "recommendation（go=実行推奨 / caution=注意して実行 / skip=見送り推奨）、"
        "confidence、rationale、risks を返してください。"
    )

    data = call_structured(cfg.model, prompt, _SCHEMA, api_key)
    if data is None:
        return _fallback(ticker, combined_score)

    try:
        return AdvisorOpinion(
            ticker=ticker,
            recommendation=str(data["recommendation"]),
            confidence=max(0.0, min(1.0, float(data["confidence"]))),
            rationale=str(data.get("rationale", "")),
            risks=[str(r) for r in data.get("risks", [])],
            source="claude",
        )
    except (KeyError, ValueError, TypeError):
        return _fallback(ticker, combined_score)


def _fallback(ticker: str, combined_score: float) -> AdvisorOpinion:
    """LLM不使用時: 総合スコアの強さから機械的に推奨度を決める。"""
    if combined_score >= 0.7:
        rec, conf = "go", 0.6
    elif combined_score >= 0.5:
        rec, conf = "caution", 0.5
    else:
        rec, conf = "skip", 0.4
    return AdvisorOpinion(
        ticker=ticker,
        recommendation=rec,
        confidence=conf,
        rationale=f"スコア{combined_score:+.2f}に基づく機械判定（LLM未使用）",
        risks=[],
        source="fallback",
    )
