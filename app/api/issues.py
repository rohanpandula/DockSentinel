from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from app.extensions import db
from app.models import LocalIssueStatus

bp = Blueprint("issues_api", __name__, url_prefix="/api")

_VALID_STATUSES = {s.value for s in LocalIssueStatus}


@bp.get("/issues")
def list_issues():
    services = current_app.extensions["services"]
    status = request.args.get("status")
    if status and status not in _VALID_STATUSES:
        return jsonify({"error": "invalid status"}), 400
    limit = min(int(request.args.get("limit", 100)), 500)
    rows = services.issue_repo.list_all(limit=limit, status=status)
    return jsonify([r.as_dict() for r in rows]), 200


@bp.get("/issues/<int:issue_id>")
def get_issue(issue_id: int):
    services = current_app.extensions["services"]
    issue = services.issue_repo.get(issue_id)
    if issue is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(issue.as_dict()), 200


@bp.patch("/issues/<int:issue_id>")
def patch_issue(issue_id: int):
    services = current_app.extensions["services"]
    issue = services.issue_repo.get(issue_id)
    if issue is None:
        return jsonify({"error": "not found"}), 404
    body = request.get_json(silent=True) or {}
    new_status = body.get("status")
    if new_status and new_status in _VALID_STATUSES:
        issue.status = new_status
    db.session.commit()
    return jsonify(issue.as_dict()), 200
