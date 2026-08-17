from __future__ import annotations

from app.extensions import db
from app.time_utils import utcnow_naive


class SentinelState(db.Model):
    __tablename__ = "sentinel_state"

    id = db.Column(db.Integer, primary_key=True, default=1)
    enabled = db.Column(db.Boolean, nullable=False, default=False)
    runtime_status = db.Column(db.String(32), nullable=False, default="stopped")
    started_at = db.Column(db.DateTime, nullable=True)

    last_error = db.Column(db.Text, nullable=True)
    llm_failure_count = db.Column(db.Integer, nullable=False, default=0)
    llm_last_failure_at = db.Column(db.DateTime, nullable=True)
    llm_last_test_ok_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)

    @classmethod
    def singleton(cls) -> "SentinelState":
        row = db.session.get(cls, 1)
        if row is None:
            row = cls(id=1)
            db.session.add(row)
            db.session.commit()
        return row

    def as_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "runtime_status": self.runtime_status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_error": self.last_error,
            "llm_failure_count": self.llm_failure_count,
            "llm_last_test_ok_at": self.llm_last_test_ok_at.isoformat() if self.llm_last_test_ok_at else None,
            "llm_last_failure_at": self.llm_last_failure_at.isoformat() if self.llm_last_failure_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
