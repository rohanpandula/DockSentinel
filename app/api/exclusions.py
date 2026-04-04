from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from app.extensions import db
from app.models import ExclusionRule

bp = Blueprint("exclusions_api", __name__, url_prefix="/api")


@bp.get("/exclusions")
def list_exclusions() -> tuple[dict, int]:
    rules = ExclusionRule.query.order_by(ExclusionRule.container_pattern.asc()).all()
    return jsonify({"items": [rule.as_dict() for rule in rules]}), 200


@bp.post("/exclusions")
def create_exclusion() -> tuple[dict, int]:
    payload = request.get_json(silent=True) or {}
    pattern = (payload.get("container_pattern") or "").strip()
    if not pattern:
        return jsonify({"error": "container_pattern is required"}), 400

    existing = ExclusionRule.query.filter_by(container_pattern=pattern).first()
    if existing:
        return jsonify(existing.as_dict()), 200

    rule = ExclusionRule(container_pattern=pattern, enabled=bool(payload.get("enabled", True)))
    db.session.add(rule)
    db.session.commit()

    current_app.extensions["services"].coordinator.trigger_reconcile()
    return jsonify(rule.as_dict()), 201


@bp.delete("/exclusions/<int:rule_id>")
def delete_exclusion(rule_id: int) -> tuple[dict, int]:
    rule = db.session.get(ExclusionRule, rule_id)
    if rule is None:
        return jsonify({"error": "rule not found"}), 404

    db.session.delete(rule)
    db.session.commit()
    current_app.extensions["services"].coordinator.trigger_reconcile()
    return jsonify({"deleted": True}), 200
