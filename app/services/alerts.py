from __future__ import annotations

from datetime import timedelta
from typing import Protocol, TYPE_CHECKING

from app.config_objects import AlertConfig
from app.services.telegram import TelegramNotifier
from app.time_utils import utcnow_naive

if TYPE_CHECKING:
    from app.models import AnalysisEvent
    from app.repositories.analysis_events import AnalysisEventRepository


class AlertStrategy(Protocol):
    def send(self, message: str, config: AlertConfig) -> tuple[bool, str | None]: ...


class TelegramAlertStrategy:
    """Concrete AlertStrategy that delegates HTTP dispatch to TelegramNotifier."""

    def __init__(self, notifier: TelegramNotifier) -> None:
        self.notifier = notifier

    def send(self, message: str, config: AlertConfig) -> tuple[bool, str | None]:
        return self.notifier.send_message(
            token=config.telegram_token or "",
            chat_id=config.telegram_chat_id or "",
            text=message,
        )


class AlertService:
    """Owns the alert gating + dispatch pipeline.

    Responsibilities (in order):
      1. Cooldown check (suppress duplicate chunk_hash within window).
      2. Global rate-limit check.
      3. Format the alert message.
      4. Delegate dispatch to the injected strategy.
    """

    def __init__(
        self,
        strategy: AlertStrategy,
        event_repo: "AnalysisEventRepository",
    ) -> None:
        self.strategy = strategy
        self.event_repo = event_repo

    def maybe_send(
        self, event: "AnalysisEvent", config: AlertConfig
    ) -> tuple[bool, str | None]:
        """Gate -> format -> dispatch. Does NOT commit; caller owns transaction."""
        cooldown_since = utcnow_naive() - timedelta(minutes=config.cooldown_minutes)
        duplicate = self.event_repo.find_alert_duplicate(event.chunk_hash, cooldown_since)
        if duplicate:
            return False, "duplicate alert suppressed by cooldown"

        window_since = utcnow_naive() - timedelta(seconds=config.rate_limit_window_seconds)
        recent_alerts = self.event_repo.count_recent_alerts(window_since)

        if recent_alerts >= config.rate_limit_count:
            return False, "global rate limit exceeded"

        message = self._format_message(event)
        return self.strategy.send(message, config)

    @staticmethod
    def _format_message(event: "AnalysisEvent") -> str:
        return (
            f"DockSentinel Critical Alert\n"
            f"Container: {event.container_name}\n"
            f"Summary: {event.summary or 'N/A'}\n"
            f"Fix: {event.fix_suggestion or 'N/A'}"
        )
