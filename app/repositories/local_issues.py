from __future__ import annotations

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

    def get_by_telegram_message(self, message_id: int) -> Optional[LocalIssue]:
        return (
            db.session.query(LocalIssue)
            .filter(LocalIssue.telegram_message_id == message_id)
            .order_by(LocalIssue.created_at.desc())
            .first()
        )

    def get_latest_discussing_for_chat(self, chat_id: str) -> Optional[LocalIssue]:
        return (
            db.session.query(LocalIssue)
            .filter(LocalIssue.telegram_chat_id == chat_id)
            .filter(LocalIssue.status == "discussing")
            .order_by(LocalIssue.updated_at.desc())
            .first()
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
