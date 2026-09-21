from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_

from app.extensions import db
from app.models.container_mute import ContainerMute


class ContainerMuteRepository:
    def get(self, name: str) -> ContainerMute | None:
        return ContainerMute.query.filter_by(container_name=name).first()

    def get_active(self, name: str, now: datetime) -> ContainerMute | None:
        if not name:
            return None
        mute = self.get(name)
        if mute is None or not mute.is_active(now):
            return None
        return mute

    def upsert(self, name: str, until: datetime | None, reason: str | None = None) -> ContainerMute:
        """Create or replace the mute for `name`. Does NOT commit."""
        mute = self.get(name)
        if mute is None:
            mute = ContainerMute(container_name=name)
            db.session.add(mute)
        mute.until = until
        mute.reason = reason
        return mute

    def list_active(self, now: datetime) -> list[ContainerMute]:
        return (
            ContainerMute.query.filter(or_(ContainerMute.until.is_(None), ContainerMute.until > now))
            .order_by(ContainerMute.container_name.asc())
            .all()
        )

    def delete(self, name: str) -> bool:
        """Remove the mute for `name`. Returns True if a row existed. Does NOT commit."""
        mute = self.get(name)
        if mute is None:
            return False
        db.session.delete(mute)
        return True
