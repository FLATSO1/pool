"""完全自動運用の安全ガード（暴走防止）。

1日の損失上限・最大取引数・最大新規建て数を超えたら新規買いを止める。
緊急停止はファイル（HALT）を置くだけ＝スマホから共有フォルダ等で止められる。
日次の状態は data/state/daily.json に永続化する。
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import SafetyConfig
from .logging_setup import get_logger

log = get_logger(__name__)

DEFAULT_STATE = "data/state/daily.json"
DEFAULT_HALT = "data/state/HALT"


@dataclass
class DailyState:
    date: str
    start_equity: float
    trades: int = 0
    new_positions: int = 0


class SafetyGuard:
    def __init__(
        self,
        cfg: SafetyConfig,
        state_path: str | Path = DEFAULT_STATE,
        halt_path: str | Path = DEFAULT_HALT,
        today: str | None = None,
    ):
        self.cfg = cfg
        self._state_path = Path(state_path)
        self._halt_path = Path(halt_path)
        self._today = today or dt.date.today().isoformat()
        self._state: DailyState | None = None

    # --- 1日の開始 ---

    def begin_day(self, equity: float) -> None:
        """その日の最初の呼び出しで開始時資産を記録（日付が変われば自動リセット）。"""
        loaded = self._load()
        if loaded is not None and loaded.date == self._today:
            self._state = loaded
        else:
            self._state = DailyState(date=self._today, start_equity=equity)
            self._save()

    @property
    def state(self) -> DailyState:
        assert self._state is not None, "begin_day() を先に呼んでください"
        return self._state

    # --- 判定 ---

    def kill_switch_active(self) -> bool:
        return self._halt_path.exists()

    def loss_limit_hit(self, equity: float) -> bool:
        s = self.state
        if s.start_equity <= 0:
            return False
        drawdown = (s.start_equity - equity) / s.start_equity
        return drawdown >= self.cfg.daily_loss_limit_pct

    def new_buy_blocked(self, equity: float) -> tuple[bool, str]:
        """新規買いを止めるべきか（理由つき）。"""
        if self.kill_switch_active():
            return True, "緊急停止スイッチ(HALT)が有効"
        if self.loss_limit_hit(equity):
            return True, (
                f"当日損失が上限 {self.cfg.daily_loss_limit_pct * 100:.0f}% に到達"
            )
        if self.state.trades >= self.cfg.max_trades_per_day:
            return True, f"当日の取引数が上限 {self.cfg.max_trades_per_day} に到達"
        if self.state.new_positions >= self.cfg.max_new_positions_per_day:
            return True, (
                f"当日の新規建てが上限 {self.cfg.max_new_positions_per_day} に到達"
            )
        return False, ""

    # --- 記録 ---

    def record_trade(self, is_new_position: bool = False) -> None:
        self.state.trades += 1
        if is_new_position:
            self.state.new_positions += 1
        self._save()

    # --- 永続化 ---

    def _load(self) -> DailyState | None:
        if not self._state_path.exists():
            return None
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            return DailyState(**data)
        except (json.JSONDecodeError, TypeError) as exc:
            log.warning("daily状態の読込に失敗（初期化）: %s", exc)
            return None

    def _save(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(
            json.dumps(asdict(self.state), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
