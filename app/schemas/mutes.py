from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ContainerMuteSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    container_name: str
    until: datetime | None = None
    reason: str | None = None
    created_at: datetime | None = None


class MuteListResponse(BaseModel):
    items: list[ContainerMuteSchema]


class PutMuteBody(BaseModel):
    """`hours` null/omitted = mute indefinitely."""

    hours: int | None = Field(default=None, ge=1, le=8760)
    reason: str | None = Field(default=None, max_length=255)
