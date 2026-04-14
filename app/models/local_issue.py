from __future__ import annotations

from enum import StrEnum

from app.extensions import db
from app.time_utils import utcnow_naive


class LocalIssueStatus(StrEnum):
    OPEN = "open"
    DISCUSSING = "discussing"
    REJECTED = "rejected"
    CLOSED = "closed"


class LocalIssueAction(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    DISCUSS = "discuss"


class LocalIssue(db.Model):
    __tablename__ = "local_issues"

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey("analysis_events.id"), nullable=True, index=True)
    container_name = db.Column(db.String(255), nullable=False)
    title = db.Column(db.String(500), nullable=False)
    body = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(32), nullable=False, default=LocalIssueStatus.OPEN.value, index=True)
    action = db.Column(db.String(32), nullable=False)
    confidence = db.Column(db.Float, nullable=True)
    telegram_chat_id = db.Column(db.String(255), nullable=True)
    telegram_message_id = db.Column(db.Integer, nullable=True, index=True)
    llm_model = db.Column(db.String(255), nullable=True)
    discussion = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)

    def append_discussion(self, role: str, text: str) -> None:
        stamp = utcnow_naive().strftime("%Y-%m-%d %H:%M:%S")
        block = f"\n\n[{stamp}] {role.upper()}:\n{text.strip()}\n"
        self.discussion = (self.discussion or "") + block

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "event_id": self.event_id,
            "container_name": self.container_name,
            "title": self.title,
            "body": self.body,
            "status": self.status,
            "action": self.action,
            "confidence": self.confidence,
            "discussion": self.discussion,
            "telegram_chat_id": self.telegram_chat_id,
            "telegram_message_id": self.telegram_message_id,
            "llm_model": self.llm_model,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
