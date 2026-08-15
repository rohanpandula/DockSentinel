from __future__ import annotations

from typing import Any, Optional

import httpx


class TelegramNotifier:
    """Thin wrapper around Telegram Bot API's send/edit/answer endpoints."""

    BASE = "https://api.telegram.org"

    def send_message(
        self,
        token: str,
        chat_id: str,
        text: str,
        reply_markup: Optional[dict[str, Any]] = None,
        reply_to_message_id: Optional[int] = None,
        parse_mode: Optional[str] = None,
    ) -> tuple[bool, Optional[str], Optional[int]]:
        """Returns (ok, error, message_id)."""
        if not token or not chat_id:
            return False, "telegram credentials are not configured", None
        url = f"{self.BASE}/bot{token}/sendMessage"
        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = reply_to_message_id
            payload["allow_sending_without_reply"] = True
        if parse_mode:
            payload["parse_mode"] = parse_mode
        try:
            with httpx.Client(timeout=10) as client:
                response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            message_id = data.get("result", {}).get("message_id")
            return True, None, message_id
        except httpx.HTTPError as exc:
            return False, str(exc), None

    def edit_message_reply_markup(
        self,
        token: str,
        chat_id: str,
        message_id: int,
        reply_markup: Optional[dict[str, Any]] = None,
    ) -> None:
        if not token:
            return
        url = f"{self.BASE}/bot{token}/editMessageReplyMarkup"
        payload: dict[str, Any] = {"chat_id": chat_id, "message_id": message_id}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        try:
            with httpx.Client(timeout=10) as client:
                client.post(url, json=payload)
        except httpx.HTTPError:
            pass

    def edit_message_text(
        self,
        token: str,
        chat_id: str,
        message_id: int,
        text: str,
    ) -> None:
        if not token:
            return
        url = f"{self.BASE}/bot{token}/editMessageText"
        payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
        try:
            with httpx.Client(timeout=10) as client:
                client.post(url, json=payload)
        except httpx.HTTPError:
            pass

    def answer_callback_query(self, token: str, callback_query_id: str, text: str = "") -> None:
        if not token:
            return
        url = f"{self.BASE}/bot{token}/answerCallbackQuery"
        payload: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        try:
            with httpx.Client(timeout=10) as client:
                client.post(url, json=payload)
        except httpx.HTTPError:
            pass

    def get_updates(
        self, token: str, offset: int, timeout: int = 30
    ) -> list[dict[str, Any]]:
        if not token:
            return []
        url = f"{self.BASE}/bot{token}/getUpdates"
        params = {
            "offset": offset,
            "timeout": timeout,
            "allowed_updates": '["message","callback_query"]',
        }
        try:
            with httpx.Client(timeout=timeout + 10) as client:
                response = client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            return data.get("result", []) or []
        except httpx.HTTPError as exc:
            # Let the poll loop back off; returning [] here made a bad token /
            # 409 conflict / DNS failure spin at full speed forever.
            raise RuntimeError(f"telegram getUpdates failed: {exc}") from exc
