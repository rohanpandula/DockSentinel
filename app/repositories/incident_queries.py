"""Extra incident queries the surface layer needs.

Deliberately a separate module from `app.repositories.incidents` so the
incident-engine repository stays owned by one place and this file can grow
view-specific helpers without merge friction.
"""
from __future__ import annotations

from app.extensions import db
from app.models.incident import Incident


def count_open() -> int:
    return db.session.query(db.func.count(Incident.id)).filter(Incident.status == "open").scalar() or 0


def count_by_status() -> dict[str, int]:
    rows = (
        db.session.query(Incident.status, db.func.count(Incident.id))
        .group_by(Incident.status)
        .all()
    )
    return {status: count for status, count in rows}


def open_for_container(container_name: str, limit: int = 20) -> list[Incident]:
    return (
        db.session.query(Incident)
        .filter(Incident.container_name == container_name)
        .filter(Incident.status == "open")
        .order_by(Incident.last_seen_at.desc())
        .limit(limit)
        .all()
    )
