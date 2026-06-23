"""Claude Code レビュー連携。

`advisor.mode = "claude-code"` のとき、propose は API を呼ばずに各買い候補を
「レビュー待ち」にする。このモジュールは:

  1) export_review(): proposals.json の候補を、編集しやすい小さな review.json に
     書き出す（Claude Code がここに意見を記入する）。
  2) apply_review(): 記入済み review.json を読み、検証して proposals.json の
     advisor 欄へマージする（source="claude-code"）。

これにより Anthropic API のクレジットを使わずに Claude 品質のレビューを乗せられる。
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from .proposal import DEFAULT_PATH, load_proposals, save_proposals

REVIEW_PATH = "data/state/review.json"

_VALID_REC = ("go", "caution", "skip")
_PENDING = "claude-code-pending"


def export_review(
    proposals_path: str | Path = DEFAULT_PATH,
    review_path: str | Path = REVIEW_PATH,
) -> tuple[Path, int]:
    """proposals.json の買い候補を review.json に書き出す。

    返り値: (書き出したパス, レビュー対象件数)。
    """
    ps = load_proposals(proposals_path)
    if ps is None or not ps.proposals:
        raise FileNotFoundError(
            "提案がありません。先に `autotrader propose` を実行してください。"
        )

    candidates = []
    for p in ps.proposals:
        # advisor 欄を持つ候補（＝買い候補）だけがレビュー対象。
        if p.advisor is None:
            continue
        candidates.append(
            {
                "ticker": p.ticker,
                "action": p.action,
                "quantity": p.quantity,
                "price": p.price,
                "combined_score": p.combined_score,
                "fundamental_reasons": p.fundamental_reasons,
                "technical_reasons": p.technical_reasons,
                "sentiment_summary": p.sentiment_summary,
                # Claude Code はこの opinion を埋める。
                "opinion": {
                    "recommendation": "",          # go | caution | skip
                    "confidence": 0.0,             # 0.0〜1.0
                    "rationale": "",
                    "risks": [],
                },
            }
        )

    payload = {
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "source_proposals_at": ps.created_at,
        "note": (
            "各 candidates[].opinion を埋めて `autotrader review --apply` を実行。"
            " recommendation は go/caution/skip。"
        ),
        "candidates": candidates,
    }
    out = Path(review_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return out, len(candidates)


def apply_review(
    review_path: str | Path = REVIEW_PATH,
    proposals_path: str | Path = DEFAULT_PATH,
) -> tuple[int, list[str]]:
    """記入済み review.json を proposals.json の advisor 欄へマージする。

    返り値: (反映件数, 警告メッセージ一覧)。
    """
    rp = Path(review_path)
    if not rp.exists():
        raise FileNotFoundError(
            f"{review_path} がありません。先に `autotrader review` を実行してください。"
        )
    review = json.loads(rp.read_text(encoding="utf-8"))

    ps = load_proposals(proposals_path)
    if ps is None or not ps.proposals:
        raise FileNotFoundError("対象の提案 (proposals.json) がありません。")

    # ticker+action -> proposal の索引。
    index = {(p.ticker, p.action): p for p in ps.proposals}

    applied = 0
    warnings: list[str] = []
    for c in review.get("candidates", []):
        ticker = c.get("ticker")
        action = c.get("action", "BUY")
        op = c.get("opinion") or {}
        rec = str(op.get("recommendation", "")).strip().lower()
        if not rec:
            continue  # 未記入はスキップ
        if rec not in _VALID_REC:
            warnings.append(
                f"{ticker}: recommendation '{rec}' は無効（go/caution/skip）。スキップ。"
            )
            continue
        target = index.get((ticker, action))
        if target is None:
            warnings.append(f"{ticker} {action}: 対応する提案が無いためスキップ。")
            continue
        try:
            conf = max(0.0, min(1.0, float(op.get("confidence", 0.0))))
        except (TypeError, ValueError):
            conf = 0.0
        risks = [str(r) for r in (op.get("risks") or [])]
        target.advisor = {
            "recommendation": rec,
            "confidence": round(conf, 3),
            "rationale": str(op.get("rationale", "")),
            "risks": risks,
            "source": "claude-code",
        }
        applied += 1

    save_proposals(ps.proposals, ps.mode, ps.regime, proposals_path)
    return applied, warnings


def count_pending(proposals_path: str | Path = DEFAULT_PATH) -> int:
    """まだ Claude Code のレビュー待ち（pending）の提案数を返す。"""
    ps = load_proposals(proposals_path)
    if ps is None:
        return 0
    return sum(
        1
        for p in ps.proposals
        if p.advisor and p.advisor.get("source") == _PENDING
    )
