"""ローカルに保存したヒストリカルOHLCV（SBI等のツールで書き出したCSV）を読む。

証券会社ツールで「全銘柄・上場来」の日足CSVを書き出しておけば、yfinanceの
レート制限・期間制限・銘柄欠損に縛られずバックテストの土台を厚くできる。

想定: 1銘柄1ファイル。ディレクトリに `7203.csv` のように置く。
ヘッダは日本語/英語どちらでも可（始値/Open など）。文字コードはUTF-8/cp932を吸収。
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from ..logging_setup import get_logger

log = get_logger(__name__)

# 正準カラム名 -> 受け付けるヘッダ別名（小文字・前後空白除去で比較）
_ALIASES: dict[str, tuple[str, ...]] = {
    "date": ("date", "日付", "年月日", "日時", "datetime"),
    "open": ("open", "始値", "寄付", "始"),
    "high": ("high", "高値", "高"),
    "low": ("low", "安値", "安"),
    "close": ("close", "終値", "調整後終値", "引け", "終", "adj close", "adjclose"),
    "volume": ("volume", "出来高", "出来高(株)", "vol", "売買高"),
}

_REQUIRED = ("date", "open", "high", "low", "close")


class LocalStore:
    def __init__(
        self,
        directory: str | Path,
        filename_template: str = "{code}.csv",
        columns: dict[str, str] | None = None,
        date_format: str | None = None,
    ) -> None:
        self.directory = Path(directory)
        self.filename_template = filename_template
        self.columns = columns or {}   # 正準名 -> 実ヘッダ（明示指定で別名解決を上書き）
        self.date_format = date_format

    # -- 公開API ---------------------------------------------------------
    def path_for(self, ticker: str) -> Path | None:
        """ティッカーに対応するCSVパスを探す。見つからなければ None。"""
        code = _code(ticker)
        candidates = [
            self.filename_template.format(code=code),
            self.filename_template.format(code=f"{code}.T"),
            f"{code}.csv",
            f"{code}.T.csv",
        ]
        for name in candidates:
            p = self.directory / name
            if p.exists():
                return p
        return None

    def available(self, ticker: str) -> bool:
        return self.path_for(ticker) is not None

    def load(
        self,
        ticker: str,
        period: str = "max",
        start: str | None = None,
        end: str | None = None,
    ) -> pd.DataFrame:
        p = self.path_for(ticker)
        if p is None:
            return pd.DataFrame()
        try:
            df = self._read_normalized(p)
        except Exception as exc:  # noqa: BLE001 - 壊れたCSVは欠損扱い
            log.warning("ローカルCSVの読み込みに失敗 %s: %s", p, exc)
            return pd.DataFrame()
        if df.empty:
            return df
        return _slice(df, period=period, start=start, end=end)

    def coverage(self, ticker: str) -> tuple[int, str, str] | None:
        """(行数, 開始日, 終了日) を返す。データが無ければ None。"""
        df = self.load(ticker, period="max")
        if df.empty:
            return None
        return len(df), str(df.index[0].date()), str(df.index[-1].date())

    # -- 内部 ------------------------------------------------------------
    def _read_normalized(self, path: Path) -> pd.DataFrame:
        raw = _read_csv_tolerant(path)
        if raw.empty:
            return raw

        # ヘッダ -> 正準名の対応を作る
        lookup = {str(c).strip().lower(): c for c in raw.columns}
        resolved: dict[str, str] = {}
        for canon in _ALIASES:
            # config明示指定を最優先
            override = self.columns.get(canon)
            if override and override in raw.columns:
                resolved[canon] = override
                continue
            for alias in _ALIASES[canon]:
                if alias in lookup:
                    resolved[canon] = lookup[alias]
                    break

        missing = [c for c in _REQUIRED if c not in resolved]
        if missing:
            log.warning("%s: 必要カラムが見つかりません %s", path.name, missing)
            return pd.DataFrame()

        out = pd.DataFrame()
        dates = pd.to_datetime(
            raw[resolved["date"]], format=self.date_format, errors="coerce"
        )
        for canon in ("open", "high", "low", "close", "volume"):
            if canon in resolved:
                out[canon] = _to_num(raw[resolved[canon]])
            elif canon == "volume":
                out[canon] = 0.0  # 出来高なしは0で許容

        out.index = dates
        out = out[out.index.notna()].dropna(subset=["close"])
        out = out[~out.index.duplicated(keep="last")].sort_index()
        return out


def _code(ticker: str) -> str:
    return ticker.split(".")[0].strip()


def _to_num(s: pd.Series) -> pd.Series:
    # "1,234" のようなカンマ区切りや空白を除去して数値化
    cleaned = (
        s.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("　", "", regex=False)
        .str.strip()
    )
    return pd.to_numeric(cleaned, errors="coerce")


def _read_csv_tolerant(path: Path) -> pd.DataFrame:
    for enc in ("utf-8-sig", "cp932", "utf-8"):
        try:
            return pd.read_csv(path, encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return pd.read_csv(path, encoding="utf-8", encoding_errors="replace")


_PERIOD_RE = re.compile(r"^\s*(\d+)\s*(d|wk|mo|y)\s*$", re.IGNORECASE)


def _slice(
    df: pd.DataFrame, period: str = "max", start: str | None = None, end: str | None = None
) -> pd.DataFrame:
    if start or end:
        lo = pd.to_datetime(start) if start else None
        hi = pd.to_datetime(end) if end else None
        if lo is not None:
            df = df[df.index >= lo]
        if hi is not None:
            df = df[df.index <= hi]
        return df

    if not period or period.lower() in ("max", "all"):
        return df

    m = _PERIOD_RE.match(period)
    if not m:
        return df
    n, unit = int(m.group(1)), m.group(2).lower()
    offsets = {
        "d": pd.DateOffset(days=n),
        "wk": pd.DateOffset(weeks=n),
        "mo": pd.DateOffset(months=n),
        "y": pd.DateOffset(years=n),
    }
    cutoff = df.index[-1] - offsets[unit]
    return df[df.index >= cutoff]
