from __future__ import annotations

from app.extensions import db
from app.time_utils import utcnow_naive


class ExclusionRule(db.Model):
    __tablename__ = "exclusion_rules"

    id = db.Column(db.Integer, primary_key=True)
    container_pattern = db.Column(db.String(255), nullable=False, unique=True)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "container_pattern": self.container_pattern,
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
