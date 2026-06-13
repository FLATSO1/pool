"""ユニバース・ローダーのテスト。"""

from __future__ import annotations

from pathlib import Path

from autotrader.config import Config
from autotrader.data.universe import load_from_csv, load_universe, normalize_ticker


def test_normalize_ticker():
    assert normalize_ticker("7203") == "7203.T"
    assert normalize_ticker("7203.T") == "7203.T"
    assert normalize_ticker(" 6758 ") == "6758.T"


def test_load_from_csv_with_header(tmp_path: Path):
    p = tmp_path / "u.csv"
    p.write_text("code,name\n7203,トヨタ\n6758,ソニー\n", encoding="utf-8")
    assert load_from_csv(p) == ["7203.T", "6758.T"]


def test_load_from_csv_skips_blanks_and_comments(tmp_path: Path):
    p = tmp_path / "u.csv"
    p.write_text("code,name\n7203,トヨタ\n\n# memo\n7203,dup\n", encoding="utf-8")
    # 空行・コメント・重複を除外
    assert load_from_csv(p) == ["7203.T"]


def test_load_from_csv_missing_file(tmp_path: Path):
    assert load_from_csv(tmp_path / "nope.csv") == []


def test_load_universe_manual():
    cfg = Config()
    cfg.universe_source = "manual"
    cfg.universe = ["7203.T", "6758"]
    # manual でも正規化される
    assert load_universe(cfg) == ["7203.T", "6758.T"]


def test_load_universe_file(tmp_path: Path):
    p = tmp_path / "u.csv"
    p.write_text("code,name\n9984,SBG\n", encoding="utf-8")
    cfg = Config()
    cfg.universe_source = "file"
    cfg.universe_file = str(p)
    assert load_universe(cfg) == ["9984.T"]


def test_load_universe_file_fallback_to_manual(tmp_path: Path):
    cfg = Config()
    cfg.universe_source = "file"
    cfg.universe_file = str(tmp_path / "missing.csv")
    cfg.universe = ["7203.T"]
    # ファイルが無ければ manual のリストにフォールバック
    assert load_universe(cfg) == ["7203.T"]


def test_bundled_nikkei225_csv_loads():
    # 同梱の日経225主要構成銘柄CSVが読めること
    tickers = load_from_csv("data/universe/nikkei225.csv")
    assert len(tickers) >= 50
    assert "7203.T" in tickers  # トヨタ
    assert all(t.endswith(".T") for t in tickers)
