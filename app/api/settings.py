from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from app.extensions import db
from app.models import Settings

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
    settings = Settings.singleton()
    return jsonify(settings.as_dict()), 200


@bp.put("/settings")
def update_settings() -> tuple[dict, int]:
    payload = request.get_json(silent=True) or {}
    settings = Settings.singleton()

    for key, value in payload.items():
        if key in _ALLOWED_FIELDS:
            setattr(settings, key, value)

    db.session.commit()

    coordinator = current_app.extensions["services"].coordinator
    coordinator.refresh_schedule()

    return jsonify(settings.as_dict()), 200


@bp.post("/settings/test-llm")
def test_llm_connection() -> tuple[dict, int]:
    settings = Settings.singleton()
    llm_call = current_app.extensions["services"].llm_call

    try:
        llm_call.call(
            messages=[{"role": "user", "content": "Respond with the single word: pong"}],
            max_tokens=8,
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            transport=(settings.llm_transport or "api").strip().lower(),
            cli_backend=settings.cli_backend,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=0,
            cli_timeout_seconds=settings.cli_timeout_seconds,
            cli_max_retries=0,
            temperature=0.0,
        )
    except Exception as exc:  # pragma: no cover - network dependent
        return jsonify({"ok": False, "error": str(exc)}), 400

    return jsonify({"ok": True}), 200
