from __future__ import annotations

from datetime import datetime

from app.extensions import db
from app.models.incident import Incident


class IncidentRepository:
    """Data access for the incident layer. Nothing here commits except where
    the docstring says so — the alert path commits once, at the end."""

    def get(self, incident_id: int) -> Incident | None:
        return db.session.get(Incident, incident_id)

    def find_open_by_signature(self, signature: str) -> Incident | None:
        if not signature:
            return None
        return (
            Incident.query.filter_by(signature=signature, status="open")
            .order_by(Incident.id.desc())
            .first()
        )

    def add(self, incident: Incident) -> Incident:
        """Stage a new incident and flush so ``incident.id`` is usable in the
        message body. Does NOT commit."""
        db.session.add(incident)
        db.session.flush()
        return incident

    def list(self, status: str | None = None, limit: int = 100) -> list[Incident]:
        """Newest-activity-first listing, optionally filtered by status (surface/API)."""
        query = Incident.query
        if status:
            query = query.filter(Incident.status == status)
        return query.order_by(Incident.last_seen_at.desc(), Incident.id.desc()).limit(limit).all()

    def list_open(self) -> list[Incident]:
        return Incident.query.filter_by(status="open").order_by(Incident.id.asc()).all()

    def list_stale_open(self, cutoff: datetime) -> list[Incident]:
        """Open incidents whose last occurrence is older than ``cutoff``."""
        return (
            Incident.query.filter(Incident.status == "open", Incident.last_seen_at < cutoff)
            .order_by(Incident.id.asc())
            .all()
        )

    def list_for_container(self, container_name: str, limit: int = 50) -> list[Incident]:
        return (
            Incident.query.filter_by(container_name=container_name)
            .order_by(Incident.last_seen_at.desc())
            .limit(limit)
            .all()
        )
