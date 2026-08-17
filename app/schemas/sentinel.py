from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.insights import InsightItem


class SentinelStateSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    enabled: bool
    runtime_status: str
    started_at: datetime | None = None
    last_error: str | None = None
    llm_failure_count: int
    llm_last_test_ok_at: datetime | None = None
    llm_last_failure_at: datetime | None = None
    updated_at: datetime | None = None


class SentinelStatusResponse(BaseModel):
    state: SentinelStateSchema
    active_containers: list[str]


class ToggleBody(BaseModel):
    enabled: bool | None = None


class AnalyzeBody(BaseModel):
    container: str = Field(min_length=1)

    @field_validator("container", mode="before")
    @classmethod
    def strip_container(cls, v: str) -> str:
        if isinstance(v, str):
            return v.strip()
        return v


class AnalyzeResponse(BaseModel):
    event: InsightItem
