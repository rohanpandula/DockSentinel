"""The incident layer.

Design rule: incidents change only HOW we notify, never WHETHER something is
alert-worthy. Every existing gate (alert_min_classification, alert_min_confidence,
mutes, rejected-issue suppression, global rate limit, per-container cooldown,
persistent-warning escalation, restart storm) still decides alert-worthiness and
stays exactly where it is. This layer sits at the single point where AlertService
would have called ``strategy.send`` and decides between:

  * a brand-new Telegram message (first occurrence, severity escalation, reminder), or
  * a silent in-place edit of the message that is already in the chat (recurrence),

plus an auto-resolve pass that closes quiet incidents and says so.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Optional, TYPE_CHECKING

from app.config_objects import AlertConfig, IncidentConfig
from app.models.incident import Incident
from app.time_utils import utcnow_naive

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models import AnalysisEvent
    from app.repositories.incidents import IncidentRepository

LOGGER = logging.getLogger(__name__)

# Canonical severity ranking. Lives here (rather than in sentinel.py) so both the
# analysis pipeline and the incident layer share one definition; sentinel.py
# re-exports ``classification_rank`` for its existing importers.
CLASSIFICATION_RANK = {"noise": 0, "warning": 1, "critical": 2}


def classification_rank(value: str | None) -> int:
    return CLASSIFICATION_RANK.get((value or "").strip().lower(), -1)


# --- signature normalisation ------------------------------------------------

_ISO_TIMESTAMP_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:z|[+-]\d{2}:?\d{2})?"
)
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_CLOCK_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?\b")
_UUID_RE = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
# A 6+ char hex-looking token containing at least one digit: container ids, sha
# digests, pointers. The digit requirement keeps English words ("facade") intact.
_HEXISH_RE = re.compile(r"\b(?:0x)?(?=[0-9a-f]*\d)[0-9a-f]{6,}\b")
_DIGIT_RUN_RE = re.compile(r"\d+")

SIGNATURE_SUMMARY_CHARS = 120
SIGNATURE_LENGTH = 32


def normalize_summary(summary: str | None) -> str:
    """Collapse a verdict summary down to its stable shape.

    Lowercase; drop ISO timestamps/dates and clock times; replace uuid-,
    hex- and digit-looking tokens with ``#``; collapse whitespace; keep the
    first 120 characters. Two reports of the same failure that differ only in
    numbers, ids or timestamps normalise to the same string.
    """
    text = (summary or "").lower()
    text = _ISO_TIMESTAMP_RE.sub(" ", text)
    text = _ISO_DATE_RE.sub(" ", text)
    text = _CLOCK_TIME_RE.sub(" ", text)
    text = _UUID_RE.sub("#", text)
    # Hex-looking blobs (container ids, sha digests, pointers) before plain digits,
    # otherwise the digit pass would shred them into unrecognisable fragments.
    text = _HEXISH_RE.sub("#", text)
    text = _DIGIT_RUN_RE.sub("#", text)
    text = " ".join(text.split())
    return text[:SIGNATURE_SUMMARY_CHARS]


def incident_signature(
    container_name: str | None, classification: str | None, summary: str | None
) -> str:
    """Stable identity of a problem: sha256 of container + severity + normalised
    summary, truncated to 32 hex chars. Pure function — no I/O, no clock."""
    key = "|".join(
        (
            (container_name or "").strip().lower(),
            (classification or "").strip().lower(),
            normalize_summary(summary),
        )
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:SIGNATURE_LENGTH]


def format_duration(delta: timedelta) -> str:
    """Human duration for resolve notices: '3d 4h', '2h 15m', '45m', '30s'."""
    seconds = int(max(0, delta.total_seconds()))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m"
    return f"{secs}s"


def _marker(incident_id: int | None) -> str:
    return f"incident #{incident_id}"


def _first_line(text: str) -> str:
    return (text or "").splitlines()[0] if (text or "").strip() else ""


class IncidentService:
    """Turns a stream of alert-worthy events into one message per problem.

    Public API:
        incident_signature(container_name, classification, summary)  (module level)
        IncidentService(repo, notifier=None, strategy=None, settings_provider=None)
        .notify(event, config, message, reply_markup, strategy, notifier) -> (sent, error, message_id)
        .notify_for(container_name, classification, summary, config, message, ...) -> (sent, error, message_id)
        .resolve_stale(now=None) -> list[Incident]
    """

    def __init__(
        self,
        repo: "IncidentRepository",
        notifier: Any = None,
        strategy: Any = None,
        settings_provider: Any = None,
    ) -> None:
        self.repo = repo
        self.notifier = notifier
        self.strategy = strategy
        self._settings_provider = settings_provider

    # -- settings ----------------------------------------------------------

    def _settings(self):
        if self._settings_provider is not None:
            return self._settings_provider()
        from app.models import Settings

        return Settings.singleton()

    def _incident_config(self) -> IncidentConfig:
        return IncidentConfig.from_settings(self._settings())

    # -- message bodies ----------------------------------------------------

    @staticmethod
    def _with_marker(message: str, incident_id: int | None) -> str:
        """Every message body carries a trailing 'incident #<id>' marker line."""
        return f"{message}\n{_marker(incident_id)}"

    @staticmethod
    def _recurrence_body(message: str, incident: Incident, now: datetime) -> str:
        """Same body, ' ×N' on the first line, 'last seen …' as the final line."""
        lines = (message or "").splitlines() or [""]
        lines[0] = f"{lines[0]} ×{incident.occurrence_count}"
        lines.append(
            f"last seen {now.strftime('%H:%M:%S')} UTC · {_marker(incident.id)}"
        )
        return "\n".join(lines)

    @staticmethod
    def _resolved_body(incident: Incident, duration: str) -> str:
        title = incident.title or f"{incident.container_name}"
        return (
            f"✅ RESOLVED · {title}\n"
            f"resolved after {duration}, ×{incident.occurrence_count} · {_marker(incident.id)}"
        )

    # -- dispatch ----------------------------------------------------------

    def _edit(self, notifier: Any, config: AlertConfig, incident: Incident, text: str) -> None:
        if notifier is None or not incident.telegram_message_id:
            return
        chat_id = incident.telegram_chat_id or config.telegram_chat_id or ""
        try:
            notifier.edit_message_text(
                token=config.telegram_token or "",
                chat_id=chat_id,
                message_id=incident.telegram_message_id,
                text=text,
            )
        except Exception:  # pragma: no cover - notifier is best effort
            LOGGER.warning("incident %s message edit failed", incident.id, exc_info=True)

    def _send_new(
        self,
        strategy: Any,
        config: AlertConfig,
        incident: Incident,
        message: str,
        reply_markup: Optional[dict[str, Any]],
        now: datetime,
    ) -> tuple[bool, Optional[str], Optional[int]]:
        sent, error, message_id = strategy.send(
            self._with_marker(message, incident.id), config, reply_markup=reply_markup
        )
        if sent:
            incident.notify_count = (incident.notify_count or 0) + 1
            incident.last_notified_at = now
            if message_id is not None:
                incident.telegram_message_id = message_id
            incident.telegram_chat_id = config.telegram_chat_id
        return sent, error, message_id

    # -- entry points ------------------------------------------------------

    def notify(
        self,
        event: "AnalysisEvent",
        config: AlertConfig,
        message: str,
        reply_markup: Optional[dict[str, Any]] = None,
        strategy: Any = None,
        notifier: Any = None,
    ) -> tuple[bool, Optional[str], Optional[int]]:
        """Called by AlertService *instead of* ``strategy.send`` once the event
        has already passed every alert-worthiness gate."""
        return self.notify_for(
            container_name=event.container_name,
            classification=event.classification,
            summary=event.summary,
            config=config,
            message=message,
            reply_markup=reply_markup,
            strategy=strategy,
            notifier=notifier,
        )

    def notify_for(
        self,
        container_name: str | None,
        classification: str | None,
        summary: str | None,
        config: AlertConfig,
        message: str,
        reply_markup: Optional[dict[str, Any]] = None,
        strategy: Any = None,
        notifier: Any = None,
        now: datetime | None = None,
    ) -> tuple[bool, Optional[str], Optional[int]]:
        """Signature-keyed variant for alerts that have no AnalysisEvent
        (restart storms). Returns (sent, error, telegram_message_id)."""
        strategy = strategy or self.strategy
        notifier = notifier or self.notifier
        if strategy is None:  # pragma: no cover - misconfiguration guard
            return False, "no alert strategy configured", None

        now = now or utcnow_naive()
        signature = incident_signature(container_name, classification, summary)
        incident = self.repo.find_open_by_signature(signature)

        # 1. Brand-new problem → one fresh message.
        if incident is None:
            incident = Incident(
                signature=signature,
                container_name=container_name or "",
                classification=(classification or "critical"),
                title=_first_line(message)[:500] or None,
                status="open",
                first_seen_at=now,
                last_seen_at=now,
                occurrence_count=1,
                notify_count=0,
            )
            self.repo.add(incident)
            return self._send_new(strategy, config, incident, message, reply_markup, now)

        incident.occurrence_count = (incident.occurrence_count or 0) + 1
        incident.last_seen_at = now

        # 2. The problem got worse → a NEW message, because this must ping.
        if classification_rank(classification) > classification_rank(incident.classification):
            incident.classification = (classification or incident.classification)
            incident.title = _first_line(message)[:500] or incident.title
            return self._send_new(strategy, config, incident, message, reply_markup, now)

        # 3. Still open and still going after the reminder window → ping again.
        reminder_hours = self._incident_config().reminder_hours
        if reminder_hours > 0:
            last = incident.last_notified_at
            if last is None or (now - last) >= timedelta(hours=reminder_hours):
                return self._send_new(strategy, config, incident, message, reply_markup, now)

        # 4. Same problem, same severity, inside the window → stay quiet and
        #    fold this occurrence into the message already in the chat.
        self._edit(notifier, config, incident, self._recurrence_body(message, incident, now))
        return (
            False,
            f"incident #{incident.id} updated (×{incident.occurrence_count})",
            None,
        )

    # -- auto-resolve ------------------------------------------------------

    def resolve_stale(
        self,
        now: datetime | None = None,
        config: AlertConfig | None = None,
        strategy: Any = None,
        notifier: Any = None,
    ) -> list[Incident]:
        """Close open incidents that have gone quiet, edit their message to say
        so, and (optionally) post a short resolve notice. Commits."""
        from app.extensions import db

        now = now or utcnow_naive()
        settings = self._settings()
        incident_config = IncidentConfig.from_settings(settings)
        config = config or AlertConfig.from_settings(settings)
        strategy = strategy or self.strategy
        notifier = notifier or self.notifier

        cutoff = now - timedelta(minutes=incident_config.resolve_after_minutes)
        stale = self.repo.list_stale_open(cutoff)
        if not stale:
            return []

        notify_on_resolve = incident_config.notify_on_resolve
        for incident in stale:
            incident.status = "resolved"
            incident.resolved_at = now
            duration = format_duration(now - (incident.first_seen_at or now))
            self._edit(notifier, config, incident, self._resolved_body(incident, duration))
            if notify_on_resolve and strategy is not None:
                text = (
                    f"✅ RESOLVED · {incident.container_name} · was open {duration}"
                    f" · ×{incident.occurrence_count} · {_marker(incident.id)}"
                )
                try:
                    strategy.send(text, config, reply_markup=None)
                except Exception:  # pragma: no cover - best effort
                    LOGGER.warning(
                        "incident %s resolve notice failed", incident.id, exc_info=True
                    )
        db.session.commit()
        return stale
