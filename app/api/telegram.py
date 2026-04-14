from __future__ import annotations

from flask import Blueprint, current_app

from app.models import Settings
from app.schemas.telegram import TelegramTestResponse

bp = Blueprint("telegram_api", __name__, url_prefix="/api")


@bp.post("/telegram/test")
def test_telegram():
    settings = Settings.singleton()
    notifier = current_app.extensions["services"].telegram_notifier

    sent, error = notifier.send_message(
        settings.telegram_token or "",
        settings.telegram_chat_id or "",
        "DockSentinel test message",
    )
    if not sent:
        return TelegramTestResponse(ok=False, error=error).model_dump(), 400
    return TelegramTestResponse(ok=True).model_dump(), 200
