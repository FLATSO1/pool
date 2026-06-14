"""入口タイミングの需給判定（ライブ時のみ使用・バックテスト不可）。

「日足で買うと決めた銘柄」を発注する直前に、短期の買い/売り圧を確認するための
ヘルパー。2系統:
  - intraday_pressure: 直近の1分足から出来高ベースの売買圧を近似（yfinance）
  - board_imbalance:   kabuステーションの板から買い板/売り板の偏りを算出

過去データが揃わずバックテストできないため、戦略シグナルではなく
「発注直前の最終チェック（情報表示／任意のフィルタ）」として使う。
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class PressureResult:
    source: str          # "intraday" | "board"
    buy_ratio: float     # 0.0(売り一色)〜1.0(買い一色)。0.5が拮抗
    label: str           # "buy" | "neutral" | "sell"
    detail: str

    @property
    def is_buy_pressure(self) -> bool:
        return self.label == "buy"


def _label(buy_ratio: float, hi: float = 0.55, lo: float = 0.45) -> str:
    if buy_ratio >= hi:
        return "buy"
    if buy_ratio <= lo:
        return "sell"
    return "neutral"


def intraday_pressure(df_1m: pd.DataFrame) -> PressureResult | None:
    """直近の1分足OHLCVから売買圧を近似する。

    上昇足の出来高 vs 下落足の出来高（ボリュームデルタ近似）。
    出来高が無い場合は、足の陽陰の本数で代替する。
    """
    if df_1m is None or df_1m.empty or "close" not in df_1m.columns:
        return None

    up = df_1m["close"] > df_1m["open"]
    down = df_1m["close"] < df_1m["open"]

    if "volume" in df_1m.columns and df_1m["volume"].fillna(0).sum() > 0:
        up_vol = float(df_1m.loc[up, "volume"].fillna(0).sum())
        down_vol = float(df_1m.loc[down, "volume"].fillna(0).sum())
        total = up_vol + down_vol
        if total <= 0:
            return None
        buy_ratio = up_vol / total
        detail = f"上昇足出来高{up_vol:,.0f} / 下落足{down_vol:,.0f}（直近{len(df_1m)}分）"
    else:
        up_n, down_n = int(up.sum()), int(down.sum())
        total = up_n + down_n
        if total <= 0:
            return None
        buy_ratio = up_n / total
        detail = f"陽線{up_n}本 / 陰線{down_n}本（直近{len(df_1m)}分・出来高なし）"

    return PressureResult("intraday", round(buy_ratio, 3), _label(buy_ratio), detail)


def board_imbalance(board: dict | None) -> PressureResult | None:
    """kabuステーションの板情報から買い/売りの厚みの偏りを算出する。

    Buy{n}Qty / Sell{n}Qty（1〜10本）の合計、無ければ
    UnderBuyQty / OverSellQty を使う。
    """
    if not board:
        return None

    bid = sum(_num(board.get(f"Buy{i}", {}).get("Qty")) for i in range(1, 11))
    ask = sum(_num(board.get(f"Sell{i}", {}).get("Qty")) for i in range(1, 11))

    # 板の各気配が取れない場合は総量フィールドで代替
    if bid <= 0 and ask <= 0:
        bid = _num(board.get("UnderBuyQty"))
        ask = _num(board.get("OverSellQty"))

    total = bid + ask
    if total <= 0:
        return None
    buy_ratio = bid / total
    detail = f"買い板{bid:,.0f} / 売り板{ask:,.0f}"
    return PressureResult("board", round(buy_ratio, 3), _label(buy_ratio), detail)


def _num(v) -> float:
    try:
        if v is None:
            return 0.0
        f = float(v)
        return 0.0 if f != f else f  # NaN除外
    except (TypeError, ValueError):
        return 0.0
