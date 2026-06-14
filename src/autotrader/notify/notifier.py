"""スマホ通知（Discord Webhook / Telegram Bot / コンソール）。

設定で channel を選び、秘密情報（Webhook URL・Botトークン）は環境変数から読む。
未設定ならコンソール出力にフォールバックする。
"""

from __future__ import annotations

import abc

import requests

from ..config import Config
from ..logging_setup import get_logger

log = get_logger(__name__)


class Notifier(abc.ABC):
    @abc.abstractmethod
    def send(self, text: str) -> bool:
        """メッセージを送信。成功で True。"""


class ConsoleNotifier(Notifier):
    """フォールバック: 標準出力に表示するだけ。"""

    def send(self, text: str) -> bool:
        print(f"[通知] {text}")
        return True


class DiscordNotifier(Notifier):
    def __init__(self, webhook_url: str, timeout: float = 10.0):
        self._url = webhook_url
        self._timeout = timeout

    def send(self, text: str) -> bool:
        try:
            resp = requests.post(
                self._url, json={"content": text[:1900]}, timeout=self._timeout
            )
            resp.raise_for_status()
            return True
        except requests.RequestException as exc:  # pragma: no cover - ネットワーク依存
            log.warning("Discord通知に失敗: %s", exc)
            return False


class TelegramNotifier(Notifier):
    def __init__(self, bot_token: str, chat_id: str, timeout: float = 10.0):
        self._url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self._chat_id = chat_id
        self._timeout = timeout

    def send(self, text: str) -> bool:
        try:
            resp = requests.post(
                self._url,
                json={"chat_id": self._chat_id, "text": text[:4000]},
                timeout=self._timeout,
            )
            resp.raise_for_status()
            return True
        except requests.RequestException as exc:  # pragma: no cover - ネットワーク依存
            log.warning("Telegram通知に失敗: %s", exc)
            return False


def build_notifier(cfg: Config) -> Notifier:
    """設定と秘密情報から適切な Notifier を構築。未設定はコンソール。"""
    if not cfg.notify.enabled:
        return ConsoleNotifier()

    s = cfg.secrets
    channel = cfg.notify.channel
    if channel == "discord" and s.discord_webhook_url:
        return DiscordNotifier(s.discord_webhook_url)
    if channel == "telegram" and s.telegram_bot_token and s.telegram_chat_id:
        return TelegramNotifier(s.telegram_bot_token, s.telegram_chat_id)

    if channel in ("discord", "telegram"):
        log.warning(
            "通知チャネル=%s ですが認証情報が未設定のためコンソールにフォールバック",
            channel,
        )
    return ConsoleNotifier()
