from __future__ import annotations

import httpx


class TelegramNotifier:
    def send_message(self, token: str, chat_id: str, text: str) -> tuple[bool, str | None]:
        if not token or not chat_id:
            return False, "telegram credentials are not configured"
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        try:
            with httpx.Client(timeout=10) as client:
                response = client.post(url, json=payload)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            return False, str(exc)
        return True, None
