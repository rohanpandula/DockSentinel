from __future__ import annotations

from pydantic import BaseModel

from app.schemas.sentinel import SentinelStateSchema


class HealthResponse(BaseModel):
    status: str = "ok"
    runtime: SentinelStateSchema
