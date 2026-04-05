from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from app.extensions import db

bp = Blueprint("prompts_api", __name__, url_prefix="/api")


@bp.get("/prompts")
def list_prompts() -> tuple[dict, int]:
    container = current_app.extensions["services"]
    prompts = container.prompt_repo.list_all()
    return jsonify({"items": [prompt.as_dict() for prompt in prompts]}), 200


@bp.put("/prompts/<string:key>")
def update_prompt(key: str) -> tuple[dict, int]:
    container = current_app.extensions["services"]
    prompt = container.prompt_repo.get_by_key(key)
    if prompt is None:
        return jsonify({"error": "prompt not found"}), 404

    payload = request.get_json(silent=True) or {}
    content = (payload.get("content") or "").strip()
    if not content:
        return jsonify({"error": "content is required"}), 400

    prompt.content = content
    prompt.version += 1
    prompt.is_default = content == prompt.default_content
    db.session.commit()
    return jsonify(prompt.as_dict()), 200


@bp.post("/prompts/<string:key>/reset")
def reset_prompt(key: str) -> tuple[dict, int]:
    container = current_app.extensions["services"]
    prompt = container.prompt_repo.get_by_key(key)
    if prompt is None:
        return jsonify({"error": "prompt not found"}), 404

    prompt.content = prompt.default_content
    prompt.version += 1
    prompt.is_default = True
    db.session.commit()
    return jsonify(prompt.as_dict()), 200
