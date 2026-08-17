from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from app.models.incident import INCIDENT_STATUSES
from app.repositories.incidents import IncidentRepository
from app.services.incident_actions import resolve_incident

bp = Blueprint("incidents_api", __name__, url_prefix="/api")

_repo = IncidentRepository()


def incident_repo() -> IncidentRepository:
    """Prefer a repo wired into the service container (track-g), else a local one."""
    services = current_app.extensions.get("services")
    return getattr(services, "incident_repo", None) or _repo


@bp.get("/incidents")
def list_incidents():
    status = request.args.get("status")
    if status and status not in INCIDENT_STATUSES:
        return jsonify({"error": "invalid status"}), 400

    raw_limit = request.args.get("limit", "100")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid limit"}), 400
    if not 1 <= limit <= 500:
        return jsonify({"error": "invalid limit"}), 400

    rows = incident_repo().list(status=status, limit=limit)
    return jsonify({"items": [r.as_dict() for r in rows]}), 200


@bp.get("/incidents/<int:incident_id>")
def get_incident(incident_id: int):
    incident = incident_repo().get(incident_id)
    if incident is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(incident.as_dict()), 200


@bp.post("/incidents/<int:incident_id>/resolve")
def resolve(incident_id: int):
    incident = incident_repo().get(incident_id)
    if incident is None:
        return jsonify({"error": "not found"}), 404
    if not resolve_incident(incident):
        return jsonify({"error": "already resolved"}), 409
    return jsonify(incident.as_dict()), 200
