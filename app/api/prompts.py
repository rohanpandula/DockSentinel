from flask import Blueprint, current_app, jsonify
from flask_pydantic import validate

from app.extensions import db
from app.schemas.prompts import PromptListResponse, PromptSchema, UpdatePromptBody

bp = Blueprint("prompts_api", __name__, url_prefix="/api")


@bp.get("/prompts")
def list_prompts():
    services = current_app.extensions["services"]
    prompts = services.prompt_repo.list_all()
    return PromptListResponse(items=[PromptSchema.model_validate(p) for p in prompts]).model_dump(), 200


@bp.put("/prompts/<string:key>")
@validate(body=UpdatePromptBody)
def update_prompt(key: str, body: UpdatePromptBody):
    services = current_app.extensions["services"]
    prompt = services.prompt_repo.get_by_key(key)
    if prompt is None:
        return jsonify({"error": "prompt not found"}), 404

    prompt.content = body.content.strip()
    prompt.version += 1
    prompt.is_default = prompt.content == prompt.default_content
    db.session.commit()
    return PromptSchema.model_validate(prompt).model_dump(), 200


@bp.post("/prompts/<string:key>/reset")
def reset_prompt(key: str):
    services = current_app.extensions["services"]
    prompt = services.prompt_repo.get_by_key(key)
    if prompt is None:
        return jsonify({"error": "prompt not found"}), 404

    prompt.content = prompt.default_content
    prompt.version += 1
    prompt.is_default = True
    db.session.commit()
    return PromptSchema.model_validate(prompt).model_dump(), 200
