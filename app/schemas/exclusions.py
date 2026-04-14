from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExclusionRuleSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    container_pattern: str
    enabled: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ExclusionListResponse(BaseModel):
    items: list[ExclusionRuleSchema]


class CreateExclusionBody(BaseModel):
    container_pattern: str = Field(min_length=1)
    enabled: bool = True

    @field_validator("container_pattern", mode="before")
    @classmethod
    def strip_pattern(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip()
        return v
