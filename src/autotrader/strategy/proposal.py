"""売買提案（propose）の表現と永続化。

propose で生成した提案を JSON に保存し、execute で読み込んで
承認された分だけ発注する。
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_PATH = "data/state/proposals.json"


@dataclass
class Proposal:
    ticker: str
    action: str                       # "BUY" | "SELL"
    quantity: int
    price: float | None
    combined_score: float
    reason: str = ""                  # SELL理由（risk/ signal）など
    fundamental_reasons: list[str] = field(default_factory=list)
    technical_reasons: list[str] = field(default_factory=list)
    sentiment_summary: str = ""
    advisor: dict | None = None       # AdvisorOpinion.to_dict()


@dataclass
class ProposalSet:
    created_at: str
    mode: str                         # "paper" | "live"
    regime: dict | None
    proposals: list[Proposal]

    def to_json(self) -> str:
        return json.dumps(
            {
                "created_at": self.created_at,
                "mode": self.mode,
                "regime": self.regime,
                "proposals": [asdict(p) for p in self.proposals],
            },
            ensure_ascii=False,
            indent=2,
        )


def save_proposals(
    proposals: list[Proposal],
    mode: str,
    regime: dict | None,
    path: str | Path = DEFAULT_PATH,
) -> Path:
    ps = ProposalSet(
        created_at=dt.datetime.now().isoformat(timespec="seconds"),
        mode=mode,
        regime=regime,
        proposals=proposals,
    )
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(ps.to_json(), encoding="utf-8")
    return p


def load_proposals(path: str | Path = DEFAULT_PATH) -> ProposalSet | None:
    p = Path(path)
    if not p.exists():
        return None
    data = json.loads(p.read_text(encoding="utf-8"))
    proposals = [Proposal(**d) for d in data.get("proposals", [])]
    return ProposalSet(
        created_at=data.get("created_at", ""),
        mode=data.get("mode", "paper"),
        regime=data.get("regime"),
        proposals=proposals,
    )
