from __future__ import annotations

import dataclasses

from flask import Blueprint, current_app, jsonify, request

from app.config_objects import LLMConfig
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


@bp.post("/issues/<int:issue_id>/try-llm")
def try_llm_on_issue(issue_id: int):
    services = current_app.extensions["services"]
    issue = services.issue_repo.get(issue_id)
    if issue is None:
        return jsonify({"error": "not found"}), 404

    body = request.get_json(silent=True) or {}
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400

    settings = services.settings_repo.get()
    base = LLMConfig.from_settings(settings)

    overrides: dict[str, object] = {}
    for field in ("base_url", "api_key", "model", "transport", "provider", "cli_backend"):
        val = body.get(field)
        if val is not None and str(val).strip() != "":
            overrides[field] = str(val).strip()
    overrides.setdefault("max_retries", 0)
    overrides.setdefault("cli_max_retries", 0)
    config = dataclasses.replace(base, **overrides)

    messages = [
        {
            "role": "system",
            "content": (
                "You are an SRE assistant. The operator is experimenting with different LLMs "
                "against the same issue context. Answer concisely and suggest concrete, "
                "executable remediation steps."
            ),
        },
        {
            "role": "user",
            "content": f"Issue context:\n{issue.body}\n\nOperator prompt:\n{prompt}",
        },
    ]

    try:
        result = services.llm_call.call(
            config=config,
            messages=messages,
            max_tokens=settings.reserved_output_tokens,
        )
    except Exception as exc:  # pragma: no cover - network dependent
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({
        "ok": True,
        "content": (result.content or "").strip(),
        "model": result.model,
        "latency_ms": result.latency_ms,
    }), 200


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
