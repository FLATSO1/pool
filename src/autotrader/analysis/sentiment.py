"""ニュース/SNSセンチメント分析。

Claude API（claude-opus-4-8）で見出し群を解析し、銘柄に対する
マクロ・センチメントを -1.0〜+1.0 のスコアにする。
APIキーや anthropic SDK が無い場合は軽量な辞書ベースにフォールバックする。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from ..config import SentimentConfig
from ..data.news import Headline
from ..logging_setup import get_logger

log = get_logger(__name__)

# 構造化出力スキーマ（Claude に返させるJSON形式を固定する）
_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {
            "type": "number",
            "description": "銘柄に対する総合センチメント。-1.0(非常に弱気)〜+1.0(非常に強気)",
        },
        "label": {
            "type": "string",
            "enum": ["bullish", "neutral", "bearish"],
        },
        "summary": {"type": "string", "description": "根拠の短い要約（日本語）"},
    },
    "required": ["score", "label", "summary"],
    "additionalProperties": False,
}


@dataclass
class SentimentResult:
    ticker: str
    score: float          # -1.0 〜 +1.0
    label: str            # "bullish" | "neutral" | "bearish"
    summary: str
    source: str           # "claude" | "lexicon" | "empty"


def analyze_sentiment(
    ticker: str,
    headlines: list[Headline],
    cfg: SentimentConfig,
    api_key: str | None,
) -> SentimentResult:
    if not headlines:
        return SentimentResult(ticker, 0.0, "neutral", "ニュースなし", "empty")

    if cfg.enabled and api_key:
        result = _analyze_with_claude(ticker, headlines, cfg, api_key)
        if result is not None:
            return result

    return _analyze_with_lexicon(ticker, headlines)


def _analyze_with_claude(
    ticker: str,
    headlines: list[Headline],
    cfg: SentimentConfig,
    api_key: str,
) -> SentimentResult | None:
    try:
        import anthropic
    except ImportError:
        log.debug("anthropic SDK 未導入のため辞書ベースにフォールバック")
        return None

    titles = "\n".join(f"- {h.title}（{h.publisher}）" for h in headlines)
    prompt = (
        f"あなたは日本株のアナリストです。銘柄コード {ticker} に関する直近の"
        f"ニュース見出しを読み、その銘柄に対する市場センチメントを評価してください。\n\n"
        f"=== 見出し ===\n{titles}\n\n"
        "投資判断に効くマクロ・個別材料（業績・規制・需給・地合い）を踏まえ、"
        "総合センチメントを score(-1.0〜+1.0)、label、summary で返してください。"
    )

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=cfg.model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        )
        text = next((b.text for b in resp.content if b.type == "text"), "")
        data = json.loads(text)
        score = max(-1.0, min(1.0, float(data["score"])))
        return SentimentResult(
            ticker=ticker,
            score=score,
            label=str(data.get("label", "neutral")),
            summary=str(data.get("summary", "")),
            source="claude",
        )
    except Exception as exc:  # pragma: no cover - ネットワーク/APIキー依存
        log.warning("Claude センチメント分析に失敗 %s: %s", ticker, exc)
        return None


# --- フォールバック: 辞書ベースの簡易センチメント -----------------------

_POSITIVE = [
    "上方修正", "最高益", "増益", "増収", "好調", "上昇", "急騰", "回復",
    "受注", "提携", "黒字", "増配", "自社株買い", "格上げ", "expansion",
    "beat", "surge", "record", "growth", "upgrade",
]
_NEGATIVE = [
    "下方修正", "減益", "減収", "赤字", "急落", "下落", "不振", "リコール",
    "不正", "提訴", "減配", "格下げ", "懸念", "miss", "plunge", "loss",
    "downgrade", "recall", "lawsuit",
]


def _analyze_with_lexicon(ticker: str, headlines: list[Headline]) -> SentimentResult:
    pos = neg = 0
    for h in headlines:
        text = h.title
        pos += sum(1 for w in _POSITIVE if w in text)
        neg += sum(1 for w in _NEGATIVE if w in text)
    total = pos + neg
    if total == 0:
        return SentimentResult(
            ticker, 0.0, "neutral", "明確な材料語なし", "lexicon"
        )
    score = (pos - neg) / total
    label = "bullish" if score > 0.2 else "bearish" if score < -0.2 else "neutral"
    return SentimentResult(
        ticker=ticker,
        score=round(score, 3),
        label=label,
        summary=f"ポジ語{pos}/ネガ語{neg}（辞書ベース）",
        source="lexicon",
    )
