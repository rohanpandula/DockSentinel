from __future__ import annotations

from app.extensions import db
from app.time_utils import utcnow_naive

INCIDENT_STATUSES: tuple[str, ...] = ("open", "resolved")


class Incident(db.Model):
    """A group of repeated alerts about the same problem.

    One incident == one Telegram message that is edited in place as
    occurrences accumulate, then auto-resolved after a quiet window.
    """

    __tablename__ = "incidents"

    id = db.Column(db.Integer, primary_key=True)
    signature = db.Column(db.String(255), nullable=False, index=True)
    container_name = db.Column(db.String(255), nullable=True, index=True)
    classification = db.Column(db.String(32), nullable=True)
    title = db.Column(db.String(500), nullable=True)
    status = db.Column(db.String(16), nullable=False, default="open", index=True)
    first_seen_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    last_seen_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    resolved_at = db.Column(db.DateTime, nullable=True)
    occurrence_count = db.Column(db.Integer, nullable=False, default=1)
    telegram_chat_id = db.Column(db.String(64), nullable=True)
    telegram_message_id = db.Column(db.Integer, nullable=True)
    last_notified_at = db.Column(db.DateTime, nullable=True)
    notify_count = db.Column(db.Integer, nullable=False, default=0)

    # ── derived ────────────────────────────────────────────────
    def duration_seconds(self) -> int:
        if not self.first_seen_at or not self.last_seen_at:
            return 0
        return max(0, int((self.last_seen_at - self.first_seen_at).total_seconds()))

    def duration_label(self) -> str:
        return human_duration(self.duration_seconds())

    def as_dict(self) -> dict[str, object]:
        def iso(value):
            return value.isoformat() if value else None

        return {
            "id": self.id,
            "signature": self.signature,
            "container_name": self.container_name,
            "classification": self.classification,
            "title": self.title,
            "status": self.status,
            "first_seen_at": iso(self.first_seen_at),
            "last_seen_at": iso(self.last_seen_at),
            "resolved_at": iso(self.resolved_at),
            "occurrence_count": self.occurrence_count,
            "duration_seconds": self.duration_seconds(),
            "telegram_chat_id": self.telegram_chat_id,
            "telegram_message_id": self.telegram_message_id,
            "last_notified_at": iso(self.last_notified_at),
            "notify_count": self.notify_count,
        }


def human_duration(seconds: int) -> str:
    """`42m`, `3h 05m`, `2d 04h` — compact enough for a Telegram list row."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes:02d}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours:02d}h"
