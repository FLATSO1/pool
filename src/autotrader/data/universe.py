"""ユニバース（監視銘柄リスト）の供給。

config の universe_source に応じて、
  - "manual": config.yaml の universe リストをそのまま使う
  - "file":   CSV（code列）から読み込む（例: 日経225構成銘柄）
を切り替える。CSVを差し替えるだけで日経225/TOPIX500などに拡張できる。
"""

from __future__ import annotations

import csv
from pathlib import Path

from ..config import Config
from ..logging_setup import get_logger

log = get_logger(__name__)


def load_universe(cfg: Config) -> list[str]:
    """設定に従って監視銘柄のティッカー一覧（".T"付き）を返す。"""
    if cfg.universe_source == "file":
        tickers = load_from_csv(cfg.universe_file)
        if tickers:
            return tickers
        log.warning(
            "ユニバースCSVが空/未取得のため、config.yaml の universe を使用します: %s",
            cfg.universe_file,
        )
    return [normalize_ticker(t) for t in cfg.universe]


def load_from_csv(path: str | Path) -> list[str]:
    """CSVから銘柄コードを読み、".T"付きティッカーの一覧を返す。

    想定フォーマット: ヘッダに `code`（任意で `name`）を含むCSV。
    例:
        code,name
        7203,トヨタ自動車
        6758,ソニーグループ
    `#` で始まる行・空行は無視する。
    """
    p = Path(path)
    if not p.exists():
        log.warning("ユニバースCSVが見つかりません: %s", p)
        return []

    tickers: list[str] = []
    seen: set[str] = set()
    with open(p, "r", encoding="utf-8-sig", newline="") as f:
        sample = f.readline()
        f.seek(0)
        has_header = "code" in sample.lower()
        reader = csv.DictReader(f) if has_header else csv.reader(f)
        for row in reader:
            code = (
                str(row.get("code", "")).strip()
                if isinstance(row, dict)
                else (row[0].strip() if row else "")
            )
            if not code or code.startswith("#"):
                continue
            ticker = normalize_ticker(code)
            if ticker not in seen:
                seen.add(ticker)
                tickers.append(ticker)
    log.info("ユニバースを読み込みました: %d銘柄 (%s)", len(tickers), p)
    return tickers


def normalize_ticker(code: str) -> str:
    """ "7203" -> "7203.T"。既に ".T" 等のサフィックスがあればそのまま。"""
    code = code.strip()
    if "." in code:
        return code
    return f"{code}.T"
