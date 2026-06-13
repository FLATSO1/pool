"""ファンダメンタル・スコアリングのテスト。"""

from __future__ import annotations

from autotrader.analysis.fundamental import score_fundamentals
from autotrader.config import FundamentalConfig
from autotrader.data.fundamentals import Fundamentals


def test_strong_company_passes():
    f = Fundamentals(
        ticker="GOOD.T",
        per=12.0,
        roe=0.18,
        profit_margin=0.12,
        revenue_growth=0.08,
        debt_to_equity=0.5,
    )
    s = score_fundamentals(f, FundamentalConfig())
    assert s.passed
    assert s.score > 0.5


def test_high_per_fails_hard_cutoff():
    f = Fundamentals(ticker="EXP.T", per=50.0, roe=0.20, debt_to_equity=0.3)
    s = score_fundamentals(f, FundamentalConfig(max_per=30.0))
    assert not s.passed


def test_low_roe_fails():
    f = Fundamentals(ticker="LOW.T", per=10.0, roe=0.02, debt_to_equity=0.3)
    s = score_fundamentals(f, FundamentalConfig(min_roe=0.08))
    assert not s.passed


def test_high_debt_fails():
    f = Fundamentals(ticker="DEBT.T", per=10.0, roe=0.15, debt_to_equity=3.0)
    s = score_fundamentals(f, FundamentalConfig(max_debt_to_equity=2.0))
    assert not s.passed


def test_missing_data_neutral():
    f = Fundamentals(ticker="NA.T")
    s = score_fundamentals(f, FundamentalConfig())
    # 指標が全て欠損ならスコア0、min_score=0.5 を下回り不通過
    assert s.score == 0.0
    assert not s.passed
