"""戦略エンジン: ファンダメンタル・テクニカル・センチメントの統合。

判断ロジック:
  1. ファンダメンタルの足切りを通過しない銘柄は新規買いしない（HOLD/SELLのみ）。
  2. テクニカルスコアとセンチメントスコアを重み付き平均して総合スコアを算出。
        combined = technical * (1 - w) + sentiment * w
  3. 総合スコアを買い/売り閾値と比較してアクションを決定。
  4. アクションが BUY のとき、資金配分から発注株数を決める（100株単位）。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ..analysis.fundamental import FundamentalScore, score_fundamentals
from ..analysis.sentiment import SentimentResult, analyze_sentiment
from ..analysis.technical import TechnicalSignal, generate_signal
from ..config import Config
from ..data.fundamentals import Fundamentals
from ..data.news import Headline

LOT_SIZE = 100  # 日本株の標準売買単位


@dataclass
class Decision:
    ticker: str
    action: str                 # "BUY" | "SELL" | "HOLD"
    combined_score: float       # -1.0 〜 +1.0
    price: float | None
    quantity: int               # 推奨発注株数（BUY時）
    fundamental: FundamentalScore | None
    technical: TechnicalSignal | None
    sentiment: SentimentResult | None
    reasons: list[str]


class StrategyEngine:
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def evaluate(
        self,
        ticker: str,
        ohlcv: pd.DataFrame,
        fundamentals: Fundamentals | None,
        headlines: list[Headline] | None,
        equity: float,
    ) -> Decision:
        reasons: list[str] = []

        # 1) ファンダメンタル
        fund = (
            score_fundamentals(fundamentals, self.cfg.fundamental)
            if fundamentals is not None
            else None
        )
        if fund is not None:
            reasons.append(
                f"ファンダ: スコア{fund.score:.2f} "
                f"{'通過' if fund.passed else '不通過'}"
            )

        # 2) テクニカル
        tech = generate_signal(ticker, ohlcv, self.cfg.technical)
        reasons.append(f"テクニカル: スコア{tech.score:+.2f} ({tech.action})")

        # 3) センチメント
        sent: SentimentResult | None = None
        if self.cfg.sentiment.enabled:
            sent = analyze_sentiment(
                ticker,
                headlines or [],
                self.cfg.sentiment,
                self.cfg.secrets.anthropic_api_key,
            )
            reasons.append(
                f"センチメント: スコア{sent.score:+.2f} "
                f"({sent.label}/{sent.source})"
            )

        # 4) 統合スコア
        w = self.cfg.sentiment.weight if sent is not None else 0.0
        sent_score = sent.score if sent is not None else 0.0
        combined = tech.score * (1.0 - w) + sent_score * w
        combined = round(max(-1.0, min(1.0, combined)), 4)

        # 5) アクション決定
        price = tech.indicators.get("close")
        action = self._decide_action(combined, fund)
        qty = 0
        if action == "BUY" and price:
            qty = self._position_size(equity, price)
            if qty == 0:
                action = "HOLD"
                reasons.append("資金配分が1単元に満たないためHOLD")

        return Decision(
            ticker=ticker,
            action=action,
            combined_score=combined,
            price=price,
            quantity=qty,
            fundamental=fund,
            technical=tech,
            sentiment=sent,
            reasons=reasons,
        )

    # --- 内部 ---

    def _decide_action(
        self, combined: float, fund: FundamentalScore | None
    ) -> str:
        t = self.cfg.trading
        # 売りシグナルはファンダに関わらず有効（保有銘柄の利確/損切り含む）
        if combined <= t.sell_score_threshold:
            return "SELL"
        # 新規買いはファンダ足切りを通過している場合のみ
        if combined >= t.buy_score_threshold:
            if fund is None or fund.passed:
                return "BUY"
        return "HOLD"

    def _position_size(self, equity: float, price: float) -> int:
        budget = equity * self.cfg.trading.position_pct
        lots = int(budget // (price * LOT_SIZE))
        return lots * LOT_SIZE
