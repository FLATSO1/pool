"""Claude Code レビュー連携（export / apply）のテスト。"""

from __future__ import annotations

import json

from autotrader.strategy.proposal import Proposal, load_proposals, save_proposals
from autotrader.strategy.review import (
    apply_review,
    count_pending,
    export_review,
)


def _sample_proposals():
    return [
        Proposal(
            ticker="2801.T", action="BUY", quantity=100, price=1579.5,
            combined_score=0.7,
            fundamental_reasons=["PER=23.9"],
            technical_reasons=["上昇トレンド"],
            sentiment_summary="材料なし",
            advisor={
                "recommendation": "caution", "confidence": 0.0,
                "rationale": "Claude Codeのレビュー待ち", "risks": [],
                "source": "claude-code-pending",
            },
        ),
        # SELL はレビュー対象外（advisor なし）。
        Proposal(
            ticker="8750.T", action="SELL", quantity=100, price=1800.0,
            combined_score=-0.4, reason="売りシグナル",
        ),
    ]


def test_export_only_includes_buy_candidates(tmp_path):
    ppath = tmp_path / "proposals.json"
    rpath = tmp_path / "review.json"
    save_proposals(_sample_proposals(), "paper", None, ppath)

    out, n = export_review(ppath, rpath)

    assert out == rpath
    assert n == 1
    data = json.loads(rpath.read_text(encoding="utf-8"))
    tickers = [c["ticker"] for c in data["candidates"]]
    assert tickers == ["2801.T"]  # SELL は含まれない
    assert data["candidates"][0]["opinion"]["recommendation"] == ""


def test_apply_merges_opinion_into_proposals(tmp_path):
    ppath = tmp_path / "proposals.json"
    rpath = tmp_path / "review.json"
    save_proposals(_sample_proposals(), "paper", None, ppath)
    export_review(ppath, rpath)

    review = json.loads(rpath.read_text(encoding="utf-8"))
    review["candidates"][0]["opinion"] = {
        "recommendation": "caution",
        "confidence": 0.62,
        "rationale": "財務健全だが集中度上昇に注意",
        "risks": ["集中度上昇"],
    }
    rpath.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")

    applied, warnings = apply_review(rpath, ppath)

    assert applied == 1
    assert warnings == []
    ps = load_proposals(ppath)
    adv = ps.proposals[0].advisor
    assert adv["source"] == "claude-code"
    assert adv["recommendation"] == "caution"
    assert adv["confidence"] == 0.62
    assert adv["risks"] == ["集中度上昇"]


def test_apply_clamps_confidence_and_rejects_bad_rec(tmp_path):
    ppath = tmp_path / "proposals.json"
    rpath = tmp_path / "review.json"
    save_proposals(_sample_proposals(), "paper", None, ppath)
    export_review(ppath, rpath)

    review = json.loads(rpath.read_text(encoding="utf-8"))
    # 無効な recommendation はスキップされ警告される。
    review["candidates"][0]["opinion"] = {
        "recommendation": "BUY!!", "confidence": 5.0, "rationale": "", "risks": [],
    }
    rpath.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")

    applied, warnings = apply_review(rpath, ppath)

    assert applied == 0
    assert warnings  # 無効値の警告が出る
    # 元の pending のまま。
    ps = load_proposals(ppath)
    assert ps.proposals[0].advisor["source"] == "claude-code-pending"


def test_count_pending(tmp_path):
    ppath = tmp_path / "proposals.json"
    save_proposals(_sample_proposals(), "paper", None, ppath)
    assert count_pending(ppath) == 1


def test_unfilled_opinion_is_skipped(tmp_path):
    ppath = tmp_path / "proposals.json"
    rpath = tmp_path / "review.json"
    save_proposals(_sample_proposals(), "paper", None, ppath)
    export_review(ppath, rpath)  # opinion 未記入のまま

    applied, warnings = apply_review(rpath, ppath)

    assert applied == 0
    assert warnings == []  # 未記入は警告なしでスキップ
