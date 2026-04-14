from flask import Blueprint, current_app, jsonify
from flask_pydantic import validate

from app.extensions import db
from app.models import ExclusionRule
from app.schemas.exclusions import CreateExclusionBody, ExclusionListResponse, ExclusionRuleSchema

bp = Blueprint("exclusions_api", __name__, url_prefix="/api")


@bp.get("/exclusions")
def list_exclusions():
    services = current_app.extensions["services"]
    rules = services.exclusion_repo.list_all()
    return ExclusionListResponse(items=[ExclusionRuleSchema.model_validate(r) for r in rules]).model_dump(), 200


@bp.post("/exclusions")
@validate(body=CreateExclusionBody)
def create_exclusion(body: CreateExclusionBody):
    services = current_app.extensions["services"]

    existing = services.exclusion_repo.find_by_pattern(body.container_pattern)
    if existing:
        return ExclusionRuleSchema.model_validate(existing).model_dump(), 200

    rule = ExclusionRule(container_pattern=body.container_pattern, enabled=body.enabled)
    services.exclusion_repo.add(rule)
    db.session.commit()

    services.coordinator.trigger_reconcile()
    return ExclusionRuleSchema.model_validate(rule).model_dump(), 201


@bp.delete("/exclusions/<int:rule_id>")
def delete_exclusion(rule_id: int):
    services = current_app.extensions["services"]
    rule = services.exclusion_repo.get(rule_id)
    if rule is None:
        return jsonify({"error": "rule not found"}), 404

    services.exclusion_repo.delete(rule)
    db.session.commit()
    services.coordinator.trigger_reconcile()
    return jsonify({"deleted": True}), 200
