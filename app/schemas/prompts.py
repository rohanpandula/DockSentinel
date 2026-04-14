from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PromptSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    content: str
    default_content: str
    version: int
    is_default: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PromptListResponse(BaseModel):
    items: list[PromptSchema]


class UpdatePromptBody(BaseModel):
    content: str = Field(min_length=1)

    @field_validator("content", mode="before")
    @classmethod
    def strip_content(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip()
        return v
