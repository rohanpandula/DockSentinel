from __future__ import annotations

from flask import Blueprint, current_app, jsonify

from app.models import Settings

bp = Blueprint("telegram_api", __name__, url_prefix="/api")


@bp.post("/telegram/test")
def test_telegram() -> tuple[dict, int]:
    settings = Settings.singleton()
    notifier = current_app.extensions["services"]["telegram"]

    sent, error = notifier.send_message(
        settings.telegram_token or "",
        settings.telegram_chat_id or "",
        "DockSentinel test message",
    )
    if not sent:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True}), 200
