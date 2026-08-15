from __future__ import annotations

import dataclasses
from urllib.parse import urlsplit

import httpx
from flask import Blueprint, current_app, jsonify, request

from app.config_objects import LLMConfig
from app.extensions import db
from app.models import LocalIssueStatus

bp = Blueprint("issues_api", __name__, url_prefix="/api")


def _is_http_url(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _ollama_root(base_url: str) -> str:
    """Strip /v1 suffix so Ollama's /api/tags + /api/ps endpoints resolve."""
    trimmed = (base_url or "").rstrip("/")
    if trimmed.endswith("/v1"):
        trimmed = trimmed[:-3]
    return trimmed.rstrip("/")


@bp.get("/ollama/models")
def list_ollama_models():
    services = current_app.extensions["services"]
    settings = services.settings_repo.get()
    base_url = (request.args.get("base_url") or settings.llm_base_url or "").strip()
    root = _ollama_root(base_url)
    if not root:
        return jsonify({"ok": False, "error": "base_url not configured"}), 400
    if not _is_http_url(root):
        return jsonify({"ok": False, "error": "base_url must be an http(s) URL"}), 400

    models: list[dict] = []
    loaded_names: set[str] = set()
    try:
        with httpx.Client(timeout=5) as client:
            tags = client.get(f"{root}/api/tags").json()
            ps = client.get(f"{root}/api/ps").json()
        for m in (ps.get("models") or []):
            name = m.get("name")
            if name:
                loaded_names.add(name)
        for m in (tags.get("models") or []):
            name = m.get("name")
            if not name:
                continue
            models.append({
                "name": name,
                "size": m.get("size"),
                "modified_at": m.get("modified_at"),
                "loaded": name in loaded_names,
            })
    except Exception:
        # Deliberately generic: this endpoint fetches operator-supplied URLs and
        # must not act as a host/port probing oracle via detailed error text.
        return jsonify({"ok": False, "error": "could not reach an Ollama server at that base_url"}), 502

    models.sort(key=lambda m: (not m["loaded"], m["name"].lower()))
    return jsonify({
        "ok": True,
        "base_url": root,
        "loaded": sorted(loaded_names),
        "models": models,
    }), 200

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
    if "base_url" in overrides:
        if not _is_http_url(str(overrides["base_url"])):
            return jsonify({"error": "base_url must be an http(s) URL"}), 400
        # Never send the STORED api key to a caller-chosen host: an override
        # base_url only ever gets the api_key supplied in the same request.
        if overrides["base_url"].rstrip("/") != (base.base_url or "").rstrip("/"):
            overrides.setdefault("api_key", "")
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
