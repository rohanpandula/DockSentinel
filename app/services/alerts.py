from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional, Protocol, TYPE_CHECKING
from urllib.parse import quote

from app.config_objects import AlertConfig
from app.services.telegram import TelegramNotifier
from app.time_utils import utcnow_naive

if TYPE_CHECKING:
    from app.models import AnalysisEvent
    from app.repositories.analysis_events import AnalysisEventRepository
    from app.repositories.local_issues import LocalIssueRepository

REJECTED_ISSUE_SUPPRESS_HOURS = 24


class AlertStrategy(Protocol):
    def send(
        self,
        message: str,
        config: AlertConfig,
        reply_markup: Optional[dict[str, Any]] = None,
    ) -> tuple[bool, Optional[str], Optional[int]]: ...


class TelegramAlertStrategy:
    """Concrete AlertStrategy that delegates HTTP dispatch to TelegramNotifier."""

    def __init__(self, notifier: TelegramNotifier) -> None:
        self.notifier = notifier

    def send(
        self,
        message: str,
        config: AlertConfig,
        reply_markup: Optional[dict[str, Any]] = None,
    ) -> tuple[bool, Optional[str], Optional[int]]:
        return self.notifier.send_message(
            token=config.telegram_token or "",
            chat_id=config.telegram_chat_id or "",
            text=message,
            reply_markup=reply_markup,
        )


class AlertService:
    """Owns the alert gating + dispatch pipeline."""

    def __init__(
        self,
        strategy: AlertStrategy,
        event_repo: "AnalysisEventRepository",
        issue_repo: "LocalIssueRepository | None" = None,
    ) -> None:
        self.strategy = strategy
        self.event_repo = event_repo
        self.issue_repo = issue_repo

    def maybe_send(
        self, event: "AnalysisEvent", config: AlertConfig
    ) -> tuple[bool, Optional[str], Optional[int]]:
        """Returns (sent, error, telegram_message_id). Does NOT commit."""
        now = utcnow_naive()
        if config.cooldown_minutes > 0:
            cooldown_since = now - timedelta(minutes=config.cooldown_minutes)
            duplicate = self.event_repo.find_recent_alert_for_container(
                event.container_id, event.classification, cooldown_since
            )
            if duplicate is not None and duplicate.id != event.id:
                return False, "duplicate alert suppressed by cooldown", None

        if self.issue_repo is not None and event.container_name:
            rejected_since = now - timedelta(hours=REJECTED_ISSUE_SUPPRESS_HOURS)
            if self.issue_repo.has_recent_rejected(event.container_name, rejected_since):
                return False, "suppressed: recently rejected", None

        window_since = utcnow_naive() - timedelta(seconds=config.rate_limit_window_seconds)
        recent_alerts = self.event_repo.count_recent_alerts(window_since)

        if recent_alerts >= config.rate_limit_count:
            return False, "global rate limit exceeded", None

        message = self._format_message(event)
        reply_markup = self._build_keyboard(event.id)
        return self.strategy.send(message, config, reply_markup=reply_markup)

    def send_plain(self, text: str, config: AlertConfig) -> tuple[bool, Optional[str], Optional[int]]:
        """Send a keyboard-less text alert through the same strategy, honouring
        the global rate limit (but not the per-chunk cooldown). Does NOT commit."""
        window_since = utcnow_naive() - timedelta(seconds=config.rate_limit_window_seconds)
        if self.event_repo.count_recent_alerts(window_since) >= config.rate_limit_count:
            return False, "global rate limit exceeded", None
        return self.strategy.send(text, config, reply_markup=None)

    @staticmethod
    def _format_message(event: "AnalysisEvent") -> str:
        severity = (event.classification or "critical").upper()
        confidence = event.confidence
        lines = [
            f"🚨 {severity} · {event.container_name}",
            "━━━━━━━━━━━━━━━━",
        ]
        if event.summary:
            lines.append(event.summary)
        if event.root_cause_hypothesis:
            lines.append("")
            lines.append("ROOT CAUSE")
            lines.append(event.root_cause_hypothesis)
        if event.fix_suggestion:
            lines.append("")
            lines.append("SUGGESTED FIX (model-generated — verify before running)")
            lines.append(event.fix_suggestion)
        excerpt_lines = [ln.strip() for ln in (event.chunk_excerpt or "").splitlines() if ln.strip()]
        if excerpt_lines:
            lines.append("")
            lines.append("LOG EXCERPT")
            for ln in excerpt_lines[-5:]:
                lines.append(ln if len(ln) <= 160 else ln[:157] + "...")
        lines.append("")
        if confidence is not None:
            lines.append(f"Confidence: {confidence:.2f}")
        if event.id is not None:
            lines.append(f"Event ID: {event.id}")
        if event.container_name:
            lines.append(f"Dashboard: /insights?container={quote(event.container_name, safe='')}")
        return "\n".join(lines)

    @staticmethod
    def _build_keyboard(event_id: Optional[int]) -> Optional[dict[str, Any]]:
        if event_id is None:
            return None
        return {
            "inline_keyboard": [
                [
                    {"text": "✕ Reject", "callback_data": f"reject:{event_id}"},
                    {"text": "✓ Approve", "callback_data": f"approve:{event_id}"},
                    {"text": "💬 Discuss", "callback_data": f"discuss:{event_id}"},
                ]
            ]
        }
