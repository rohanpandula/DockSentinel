"""Operator-driven incident actions shared by the API, the web UI and the bot.

The incident *engine* (grouping, notification, auto-resolve) lives in
`app.services.incidents`; this module only holds the manual "I fixed it"
transition so all three surfaces behave identically.
"""
from __future__ import annotations

from app.extensions import db
from app.models.incident import Incident
from app.time_utils import utcnow_naive


def resolve_incident(incident: Incident) -> bool:
    """Mark `incident` resolved. Returns False if it already was (idempotent no-op)."""
    if incident.status == "resolved":
        return False
    incident.status = "resolved"
    incident.resolved_at = utcnow_naive()
    db.session.commit()
    return True
