from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.extensions import db
from app.models import LocalIssue


class LocalIssueRepository:
    def add(self, issue: LocalIssue) -> LocalIssue:
        db.session.add(issue)
        db.session.flush()
        return issue

    def get(self, issue_id: int) -> Optional[LocalIssue]:
        return db.session.get(LocalIssue, issue_id)

    def get_by_telegram_message(self, message_id: int, chat_id: Optional[str] = None) -> Optional[LocalIssue]:
        # Telegram message ids are only unique per chat, so scope by chat when known.
        query = db.session.query(LocalIssue).filter(LocalIssue.telegram_message_id == message_id)
        if chat_id is not None:
            query = query.filter(LocalIssue.telegram_chat_id == str(chat_id))
        return query.order_by(LocalIssue.created_at.desc()).first()

    def get_latest_discussing_for_chat(self, chat_id: str) -> Optional[LocalIssue]:
        return (
            db.session.query(LocalIssue)
            .filter(LocalIssue.telegram_chat_id == chat_id)
            .filter(LocalIssue.status == "discussing")
            .order_by(LocalIssue.updated_at.desc())
            .first()
        )

    def has_recent_rejected(self, container_name: str, since: datetime) -> bool:
        return (
            db.session.query(LocalIssue.id)
            .filter(LocalIssue.container_name == container_name)
            .filter(LocalIssue.status == "rejected")
            .filter(LocalIssue.created_at >= since)
            .first()
            is not None
        )

    def list_all(self, limit: int = 100, status: Optional[str] = None) -> list[LocalIssue]:
        q = db.session.query(LocalIssue)
        if status:
            q = q.filter(LocalIssue.status == status)
        return q.order_by(LocalIssue.created_at.desc()).limit(limit).all()

    def count_by_status(self) -> dict[str, int]:
        rows = (
            db.session.query(LocalIssue.status, db.func.count(LocalIssue.id))
            .group_by(LocalIssue.status)
            .all()
        )
        return {status: count for status, count in rows}
