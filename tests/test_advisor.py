"""アドバイザー・地合い・提案の永続化テスト（ネットワーク/LLM不要部分）。"""

from __future__ import annotations

from autotrader.analysis.advisor import review_candidate
from autotrader.analysis.market_regime import assess_market
from autotrader.config import AdvisorConfig
from autotrader.strategy.proposal import Proposal, load_proposals, save_proposals


def test_advisor_fallback_without_api_key():
    cfg = AdvisorConfig(enabled=True)
    op = review_candidate(
        "7203.T", "BUY", 0.8, ["ROE=18%"], ["ゴールデンクロス"], "",
        headlines=[], cfg=cfg, api_key=None,
    )
    assert op.source == "fallback"
    assert op.recommendation == "go"  # 高スコアは go


def test_advisor_fallback_low_score_skips():
    cfg = AdvisorConfig(enabled=True)
    op = review_candidate(
        "7203.T", "BUY", 0.3, [], [], "", headlines=[], cfg=cfg, api_key=None
    )
    assert op.recommendation == "skip"


def test_advisor_disabled():
    cfg = AdvisorConfig(enabled=False)
    op = review_candidate(
        "7203.T", "BUY", 0.9, [], [], "", headlines=[], cfg=cfg, api_key=None
    )
    assert op.source == "fallback"


def test_market_regime_disabled_is_neutral():
    cfg = AdvisorConfig(enabled=True, regime_enabled=False)
    r = assess_market(cfg, api_key=None)
    assert r.regime == "neutral"
    assert not r.blocks_new_buys()


def test_proposal_round_trip(tmp_path):
    path = tmp_path / "proposals.json"
    proposals = [
        Proposal(
            ticker="7203.T", action="BUY", quantity=100, price=2800.0,
            combined_score=0.72, technical_reasons=["ゴールデンクロス"],
            advisor={"recommendation": "go", "confidence": 0.7, "rationale": "x",
                     "risks": [], "source": "fallback"},
        ),
        Proposal(
            ticker="6758.T", action="SELL", quantity=100, price=3000.0,
            combined_score=-0.4, reason="stop_loss（損益 -7.2%）",
        ),
    ]
    save_proposals(proposals, mode="paper", regime={"regime": "neutral"}, path=path)
    loaded = load_proposals(path)
    assert loaded is not None
    assert loaded.mode == "paper"
    assert len(loaded.proposals) == 2
    assert loaded.proposals[0].ticker == "7203.T"
    assert loaded.proposals[0].advisor["recommendation"] == "go"


def test_load_proposals_missing(tmp_path):
    assert load_proposals(tmp_path / "none.json") is None
