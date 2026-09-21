from __future__ import annotations

from app.extensions import db
from app.time_utils import utcnow_naive


class ContainerMute(db.Model):
    """Per-container alert mute. `until` NULL means muted indefinitely."""

    __tablename__ = "container_mutes"

    id = db.Column(db.Integer, primary_key=True)
    container_name = db.Column(db.String(255), nullable=False, unique=True, index=True)
    until = db.Column(db.DateTime, nullable=True)
    reason = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)

    def is_active(self, now) -> bool:
        return self.until is None or self.until > now

    def until_label(self) -> str:
        return self.until.strftime("%Y-%m-%d %H:%M UTC") if self.until else "indefinitely"

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "container_name": self.container_name,
            "until": self.until.isoformat() if self.until else None,
            "reason": self.reason,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
