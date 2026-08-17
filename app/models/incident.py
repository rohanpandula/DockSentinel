from __future__ import annotations

from app.extensions import db
from app.time_utils import utcnow_naive


class Incident(db.Model):
    """A deduplicated, long-lived problem.

    One incident groups every recurrence of the *same* problem (same container,
    same classification, same normalised summary — see
    ``app.services.incidents.incident_signature``). It exists purely so a
    persistent problem produces ONE Telegram message that is edited in place as
    it recurs, plus a resolve notice — instead of a new alert every cooldown.
    It never decides *whether* something is alert-worthy.
    """

    __tablename__ = "incidents"

    id = db.Column(db.Integer, primary_key=True)
    signature = db.Column(db.String(64), nullable=False, index=True)
    container_name = db.Column(db.String(255), nullable=False, index=True)
    classification = db.Column(db.String(16), nullable=False, default="critical")
    title = db.Column(db.String(500), nullable=True)
    status = db.Column(db.String(16), nullable=False, default="open", server_default="open", index=True)

    first_seen_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    last_seen_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    resolved_at = db.Column(db.DateTime, nullable=True)

    occurrence_count = db.Column(db.Integer, nullable=False, default=1, server_default="1")

    telegram_chat_id = db.Column(db.String(255), nullable=True)
    telegram_message_id = db.Column(db.Integer, nullable=True)
    last_notified_at = db.Column(db.DateTime, nullable=True)
    notify_count = db.Column(db.Integer, nullable=False, default=0, server_default="0")

    def is_open(self) -> bool:
        return (self.status or "open") == "open"

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "signature": self.signature,
            "container_name": self.container_name,
            "classification": self.classification,
            "title": self.title,
            "status": self.status,
            "first_seen_at": self.first_seen_at.isoformat() if self.first_seen_at else None,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "occurrence_count": self.occurrence_count,
            "telegram_chat_id": self.telegram_chat_id,
            "telegram_message_id": self.telegram_message_id,
            "last_notified_at": self.last_notified_at.isoformat() if self.last_notified_at else None,
            "notify_count": self.notify_count,
        }
