from __future__ import annotations

import dataclasses

from flask import Blueprint, current_app, jsonify, request

from app.config_objects import LLMConfig

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
def get_settings() -> tuple[dict, int]:
    container = current_app.extensions["services"]
    settings = container.settings_repo.get()
    return jsonify(settings.as_dict()), 200


@bp.put("/settings")
def update_settings() -> tuple[dict, int]:
    payload = request.get_json(silent=True) or {}
    container = current_app.extensions["services"]
    settings = container.settings_repo.get()

    for key, value in payload.items():
        if key in _ALLOWED_FIELDS:
            setattr(settings, key, value)

    container.settings_repo.save()

    container.coordinator.refresh_schedule()

    return jsonify(settings.as_dict()), 200


@bp.post("/settings/test-llm")
def test_llm_connection() -> tuple[dict, int]:
    container = current_app.extensions["services"]
    settings = container.settings_repo.get()
    llm_call = container.llm_call

    try:
        config = dataclasses.replace(LLMConfig.from_settings(settings), max_retries=0, cli_max_retries=0)
        llm_call.call(
            config=config,
            messages=[{"role": "user", "content": "Respond with the single word: pong"}],
            max_tokens=8,
            temperature=0.0,
        )
    except Exception as exc:  # pragma: no cover - network dependent
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({"ok": True}), 200
