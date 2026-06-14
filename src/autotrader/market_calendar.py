"""東証の営業日（取引日）判定。

土日・年末年始（12/31〜1/3）を除外し、祝日は jpholiday があれば判定する。
jpholiday 未導入時は祝日チェックをスキップ（土日・年末年始のみ）。
"""

from __future__ import annotations

import datetime as dt

from .logging_setup import get_logger

log = get_logger(__name__)

_warned_no_jpholiday = False


def is_trading_day(d: dt.date | None = None) -> bool:
    """東証の取引日なら True。"""
    d = d or dt.date.today()
    if d.weekday() >= 5:           # 5=土, 6=日
        return False
    if _is_year_end_holiday(d):
        return False
    if _is_national_holiday(d):
        return False
    return True


def describe_non_trading(d: dt.date | None = None) -> str:
    """非取引日の理由を返す（取引日なら空文字）。"""
    d = d or dt.date.today()
    if d.weekday() == 5:
        return "土曜日"
    if d.weekday() == 6:
        return "日曜日"
    if _is_year_end_holiday(d):
        return "年末年始休場"
    if _is_national_holiday(d):
        return "祝日"
    return ""


def _is_year_end_holiday(d: dt.date) -> bool:
    # 東証は 12/31 と 1/1〜1/3 が休場
    return (d.month == 12 and d.day == 31) or (d.month == 1 and d.day <= 3)


def _is_national_holiday(d: dt.date) -> bool:
    global _warned_no_jpholiday
    try:
        import jpholiday
    except ImportError:
        if not _warned_no_jpholiday:
            log.warning(
                "jpholiday 未導入のため祝日判定をスキップします"
                "（`pip install jpholiday` 推奨）"
            )
            _warned_no_jpholiday = True
        return False
    return bool(jpholiday.is_holiday(d))
