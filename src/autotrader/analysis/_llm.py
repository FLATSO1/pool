"""Claude API 呼び出しの共通ヘルパー（構造化出力）。

anthropic SDK / APIキーが無い場合は None を返し、呼び出し側で
フォールバックできるようにする。
"""

from __future__ import annotations

import json
from typing import Any

from ..logging_setup import get_logger

log = get_logger(__name__)


def call_structured(
    model: str,
    prompt: str,
    schema: dict,
    api_key: str | None,
    max_tokens: int = 1024,
) -> dict[str, Any] | None:
    """Claudeにプロンプトを投げ、schemaに沿ったJSON(dict)を返す。失敗時 None。"""
    if not api_key:
        return None
    try:
        import anthropic
    except ImportError:
        log.debug("anthropic SDK 未導入のためLLM呼び出しをスキップ")
        return None

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        text = next((b.text for b in resp.content if b.type == "text"), "")
        return json.loads(text)
    except Exception as exc:  # pragma: no cover - ネットワーク/APIキー依存
        log.warning("Claude 構造化呼び出しに失敗: %s", exc)
        return None
