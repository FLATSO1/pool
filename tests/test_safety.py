"""安全ガードと通知のテスト。"""

from __future__ import annotations

from autotrader.config import Config, NotifyConfig, SafetyConfig
from autotrader.notify import ConsoleNotifier, build_notifier
from autotrader.safety import SafetyGuard


def _guard(tmp_path, cfg=None, today="2026-06-14"):
    return SafetyGuard(
        cfg or SafetyConfig(),
        state_path=tmp_path / "daily.json",
        halt_path=tmp_path / "HALT",
        today=today,
    )


def test_loss_limit_blocks_new_buys(tmp_path):
    g = _guard(tmp_path, SafetyConfig(daily_loss_limit_pct=0.03))
    g.begin_day(equity=1_000_000)
    # -2% ではまだOK
    assert not g.new_buy_blocked(980_000)[0]
    # -3% で停止
    blocked, reason = g.new_buy_blocked(970_000)
    assert blocked and "損失" in reason


def test_max_trades_blocks(tmp_path):
    g = _guard(tmp_path, SafetyConfig(max_trades_per_day=2))
    g.begin_day(equity=1_000_000)
    g.record_trade()
    g.record_trade()
    blocked, reason = g.new_buy_blocked(1_000_000)
    assert blocked and "取引数" in reason


def test_max_new_positions_blocks(tmp_path):
    g = _guard(tmp_path, SafetyConfig(max_new_positions_per_day=1))
    g.begin_day(equity=1_000_000)
    g.record_trade(is_new_position=True)
    blocked, reason = g.new_buy_blocked(1_000_000)
    assert blocked and "新規建て" in reason


def test_kill_switch(tmp_path):
    g = _guard(tmp_path)
    g.begin_day(equity=1_000_000)
    assert not g.kill_switch_active()
    (tmp_path / "HALT").write_text("stop", encoding="utf-8")
    assert g.kill_switch_active()
    assert g.new_buy_blocked(1_000_000)[0]


def test_daily_state_persists_within_day(tmp_path):
    g1 = _guard(tmp_path, today="2026-06-14")
    g1.begin_day(equity=1_000_000)
    g1.record_trade(is_new_position=True)
    # 同日に再起動 → 状態を引き継ぐ
    g2 = _guard(tmp_path, today="2026-06-14")
    g2.begin_day(equity=1_500_000)  # 別の値を渡しても開始時資産は維持
    assert g2.state.trades == 1
    assert g2.state.start_equity == 1_000_000


def test_daily_state_resets_next_day(tmp_path):
    g1 = _guard(tmp_path, today="2026-06-14")
    g1.begin_day(equity=1_000_000)
    g1.record_trade()
    g2 = _guard(tmp_path, today="2026-06-15")
    g2.begin_day(equity=1_200_000)
    assert g2.state.trades == 0
    assert g2.state.start_equity == 1_200_000


def test_build_notifier_falls_back_to_console():
    cfg = Config()
    cfg.notify = NotifyConfig(enabled=True, channel="discord")
    # Webhook未設定 → コンソールにフォールバック
    assert isinstance(build_notifier(cfg), ConsoleNotifier)


def test_console_notifier_send(capsys):
    assert ConsoleNotifier().send("テスト") is True
    assert "テスト" in capsys.readouterr().out
