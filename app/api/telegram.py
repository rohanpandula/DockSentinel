from __future__ import annotations

from flask import Blueprint, current_app, jsonify

from app.models import Settings
from app.schemas.telegram import TelegramTestResponse

bp = Blueprint("telegram_api", __name__, url_prefix="/api")


@bp.post("/telegram/test")
def test_telegram():
    settings = Settings.singleton()
    notifier = current_app.extensions["services"].telegram_notifier

    sent, error, _ = notifier.send_message(
        settings.telegram_token or "",
        settings.telegram_chat_id or "",
        "DockSentinel test message",
    )
    if not sent:
        return TelegramTestResponse(ok=False, error=error).model_dump(), 400
    return TelegramTestResponse(ok=True).model_dump(), 200


@bp.get("/telegram/detect-chat")
def detect_chat():
    """Chat-id discovery for the setup wizard: the bot poller remembers the last
    chat that messaged it. Operator sends /start to the bot, then presses Detect."""
    services = current_app.extensions["services"]
    bot = getattr(services, "telegram_bot", None)
    seen = getattr(bot, "last_seen_chat", None) if bot is not None else None
    settings = Settings.singleton()
    if not (settings.telegram_token or "").strip():
        return jsonify({"ok": False, "error": "save a bot token first"}), 400
    if not seen:
        return jsonify({"ok": False, "error": "no message seen yet — send /start to your bot, then try again"}), 404
    return jsonify({"ok": True, **seen}), 200
