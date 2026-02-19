from __future__ import annotations

from app.extensions import db
from app.time_utils import utcnow_naive


class DailyReport(db.Model):
    __tablename__ = "daily_reports"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive, index=True)
    period_start = db.Column(db.DateTime, nullable=False)
    period_end = db.Column(db.DateTime, nullable=False)

    status = db.Column(db.String(32), nullable=False, default="generated")
    markdown_content = db.Column(db.Text, nullable=False)

    model = db.Column(db.String(255), nullable=True)
    prompt_version = db.Column(db.Integer, nullable=True)
    error = db.Column(db.Text, nullable=True)

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "status": self.status,
            "markdown_content": self.markdown_content,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "error": self.error,
        }
