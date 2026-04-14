from __future__ import annotations

from pydantic import BaseModel


class TelegramTestResponse(BaseModel):
    ok: bool
    error: str | None = None
