from __future__ import annotations

from typing import Optional

from app.extensions import db
from app.models.incident import Incident


class IncidentRepository:
    """Reads/writes for the incident layer.

    Kept deliberately thin: `list`, `get` and `find_open_by_signature` are the
    contract the surface (API / web / Telegram) relies on. Extra queries live in
    `app.repositories.incident_queries`.
    """

    def add(self, incident: Incident) -> Incident:
        db.session.add(incident)
        db.session.flush()
        return incident

    def list(self, status: Optional[str] = None, limit: int = 100) -> list[Incident]:
        q = db.session.query(Incident)
        if status:
            q = q.filter(Incident.status == status)
        return q.order_by(Incident.last_seen_at.desc(), Incident.id.desc()).limit(limit).all()

    def get(self, incident_id: int) -> Optional[Incident]:
        return db.session.get(Incident, incident_id)

    def find_open_by_signature(self, signature: str) -> Optional[Incident]:
        return (
            db.session.query(Incident)
            .filter(Incident.signature == signature)
            .filter(Incident.status == "open")
            .order_by(Incident.last_seen_at.desc())
            .first()
        )
