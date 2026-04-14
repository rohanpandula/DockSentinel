import dataclasses

from flask import Blueprint, current_app, jsonify
from flask_pydantic import validate

from app.config_objects import LLMConfig
from app.schemas.settings import SettingsSchema, TestLLMResponse, UpdateSettingsBody

bp = Blueprint("settings_api", __name__, url_prefix="/api")

_ALLOWED_FIELDS = {
    "llm_base_url",
    "llm_api_key",
    "llm_model",
    "llm_provider",
    "llm_transport",
    "cli_backend",
    "cli_timeout_seconds",
    "cli_max_retries",
    "telegram_token",
    "telegram_chat_id",
    "nightly_hour",
    "nightly_minute",
    "max_input_chars",
    "max_input_tokens",
    "reserved_output_tokens",
    "token_estimation_strategy",
    "keyword_list",
    "alert_cooldown_minutes",
    "alert_rate_limit_count",
    "alert_rate_limit_window_seconds",
    "llm_timeout_seconds",
    "llm_max_retries",
    "dedup_window_seconds",
    "container_rate_limit_count",
    "container_rate_limit_window_seconds",
    "keyword_flush_delay_lines",
}


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
        if key in _ALLOWED_FIELDS:
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
