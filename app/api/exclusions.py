from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from app.extensions import db
from app.models import ExclusionRule

bp = Blueprint("exclusions_api", __name__, url_prefix="/api")


@bp.get("/exclusions")
def list_exclusions() -> tuple[dict, int]:
    container = current_app.extensions["services"]
    rules = container.exclusion_repo.list_all()
    return jsonify({"items": [rule.as_dict() for rule in rules]}), 200


@bp.post("/exclusions")
def create_exclusion() -> tuple[dict, int]:
    container = current_app.extensions["services"]
    payload = request.get_json(silent=True) or {}
    pattern = (payload.get("container_pattern") or "").strip()
    if not pattern:
        return jsonify({"error": "container_pattern is required"}), 400

    existing = container.exclusion_repo.find_by_pattern(pattern)
    if existing:
        return jsonify(existing.as_dict()), 200

    rule = ExclusionRule(container_pattern=pattern, enabled=bool(payload.get("enabled", True)))
    container.exclusion_repo.add(rule)
    db.session.commit()

    container.coordinator.trigger_reconcile()
    return jsonify(rule.as_dict()), 201


@bp.delete("/exclusions/<int:rule_id>")
def delete_exclusion(rule_id: int) -> tuple[dict, int]:
    container = current_app.extensions["services"]
    rule = container.exclusion_repo.get(rule_id)
    if rule is None:
        return jsonify({"error": "rule not found"}), 404

    container.exclusion_repo.delete(rule)
    db.session.commit()
    container.coordinator.trigger_reconcile()
    return jsonify({"deleted": True}), 200
