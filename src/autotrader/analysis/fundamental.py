"""ファンダメンタルによる銘柄選定（スコアリングと足切り）。"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import FundamentalConfig
from ..data.fundamentals import Fundamentals


@dataclass
class FundamentalScore:
    ticker: str
    score: float          # 0.0–1.0
    passed: bool          # 足切り通過したか
    reasons: list[str]


def score_fundamentals(
    f: Fundamentals, cfg: FundamentalConfig
) -> FundamentalScore:
    """指標から 0–1 の総合スコアを計算し、閾値で選別する。

    各指標を 0–1 に正規化して平均。欠損指標は評価から除外（中立扱い）。
    ハードな足切り条件（PER上限・ROE下限・D/E上限）も併用する。
    """
    parts: list[float] = []
    reasons: list[str] = []

    # PER: 低いほど良い（15以下を満点、それ以上は逓減、>max_perで0）
    if f.per is not None and f.per > 0:
        per_score = max(0.0, min(1.0, (cfg.max_per - f.per) / cfg.max_per))
        parts.append(per_score)
        reasons.append(f"PER={f.per:.1f}")

    # ROE: 高いほど良い（20%で満点）
    if f.roe is not None:
        roe_score = max(0.0, min(1.0, f.roe / 0.20))
        parts.append(roe_score)
        reasons.append(f"ROE={f.roe * 100:.1f}%")

    # 純利益率: 高いほど良い（15%で満点）
    if f.profit_margin is not None:
        pm_score = max(0.0, min(1.0, f.profit_margin / 0.15))
        parts.append(pm_score)
        reasons.append(f"利益率={f.profit_margin * 100:.1f}%")

    # 売上成長率: 高いほど良い（10%で満点、マイナス成長は0）
    if f.revenue_growth is not None:
        rg_score = max(0.0, min(1.0, f.revenue_growth / 0.10))
        parts.append(rg_score)
        reasons.append(f"売上成長={f.revenue_growth * 100:.1f}%")

    # D/E: 低いほど良い（max_debt_to_equity を0点とする）
    if f.debt_to_equity is not None and cfg.max_debt_to_equity > 0:
        de_score = max(
            0.0, min(1.0, 1.0 - f.debt_to_equity / cfg.max_debt_to_equity)
        )
        parts.append(de_score)
        reasons.append(f"D/E={f.debt_to_equity:.2f}")

    score = sum(parts) / len(parts) if parts else 0.0

    # ハード足切り
    passed = score >= cfg.min_score
    if f.per is not None and f.per > cfg.max_per:
        passed = False
        reasons.append(f"PER {f.per:.1f} > 上限 {cfg.max_per}")
    if f.roe is not None and f.roe < cfg.min_roe:
        passed = False
        reasons.append(f"ROE {f.roe * 100:.1f}% < 下限 {cfg.min_roe * 100:.1f}%")
    if (
        f.debt_to_equity is not None
        and f.debt_to_equity > cfg.max_debt_to_equity
    ):
        passed = False
        reasons.append(
            f"D/E {f.debt_to_equity:.2f} > 上限 {cfg.max_debt_to_equity}"
        )

    return FundamentalScore(
        ticker=f.ticker, score=round(score, 4), passed=passed, reasons=reasons
    )
