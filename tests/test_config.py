"""設定読み込みの文字コード耐性テスト。"""

from __future__ import annotations

from autotrader.config import Config


def test_load_utf8_config(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(
        "# 日本語コメント\nuniverse_source: \"manual\"\nuniverse:\n  - \"7203.T\"\n",
        encoding="utf-8",
    )
    cfg = Config.load(p)
    assert cfg.universe_source == "manual"
    assert cfg.universe == ["7203.T"]


def test_load_cp932_config(tmp_path):
    # WindowsのSet-Content等でShift-JIS保存されても読めること
    p = tmp_path / "config.yaml"
    p.write_text(
        "# 日本語コメント（Shift-JIS）\ntrading:\n  cash: 500000\n",
        encoding="cp932",
    )
    cfg = Config.load(p)
    assert cfg.trading.cash == 500000


def test_load_utf8_bom_config(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("trading:\n  max_positions: 7\n", encoding="utf-8-sig")
    cfg = Config.load(p)
    assert cfg.trading.max_positions == 7


def test_load_corrupted_control_char(tmp_path):
    # 破損で混入した制御文字(U+0080)があっても読めること
    p = tmp_path / "config.yaml"
    p.write_bytes(
        "# \x80 corrupted comment\ntrading:\n  cash: 300000\n".encode("utf-8")
    )
    cfg = Config.load(p)
    assert cfg.trading.cash == 300000
