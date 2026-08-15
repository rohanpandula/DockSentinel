import dataclasses

from flask import Blueprint, current_app, jsonify
from flask_pydantic import validate

from app.config_objects import LLMConfig
from app.schemas.settings import ALLOWED_SETTINGS_FIELDS, MASK, SECRET_FIELDS, SettingsSchema, TestLLMResponse, UpdateSettingsBody

bp = Blueprint("settings_api", __name__, url_prefix="/api")

_ALLOWED_FIELDS = ALLOWED_SETTINGS_FIELDS


@bp.get("/settings")
def get_settings():
    services = current_app.extensions["services"]
    settings = services.settings_repo.get()
    return SettingsSchema.model_validate(settings).model_dump(), 200


@bp.put("/settings")
@validate(body=UpdateSettingsBody)
def update_settings(body: UpdateSettingsBody):
    services = current_app.extensions["services"]
    settings = services.settings_repo.get()

    for key, value in body.model_dump(exclude_unset=True).items():
        if key not in _ALLOWED_FIELDS:
            continue
        # Secrets are never echoed back (masked), so a masked/blank value on
        # write means "keep the current secret". An explicit JSON null clears it.
        if key in SECRET_FIELDS:
            if value is None:
                value = ""
            elif value.strip() in {"", MASK}:
                continue
        setattr(settings, key, value)

    services.settings_repo.save()
    services.coordinator.refresh_schedule()

    return SettingsSchema.model_validate(settings).model_dump(), 200


@bp.post("/settings/test-llm")
def test_llm_connection():
    services = current_app.extensions["services"]
    settings = services.settings_repo.get()
    llm_call = services.llm_call

    try:
        config = dataclasses.replace(LLMConfig.from_settings(settings), max_retries=0, cli_max_retries=0)
        llm_call.call(
            config=config,
            messages=[{"role": "user", "content": "Respond with the single word: pong"}],
            max_tokens=8,
            temperature=0.0,
        )
    except Exception as exc:  # pragma: no cover - network dependent
        return TestLLMResponse(ok=False, error=str(exc)).model_dump(), 400

    return TestLLMResponse(ok=True).model_dump(), 200
