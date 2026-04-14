from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import PaginationQuery


class InsightItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime | None = None
    container_id: str | None = None
    container_name: str | None = None
    status: str
    classification: str | None = None
    matched_keywords: str | None = None
    chunk_hash: str | None = None
    chunk_excerpt: str | None = None
    summary: str | None = None
    root_cause_hypothesis: str | None = None
    fix_suggestion: str | None = None
    confidence: float | None = None
    input_chars: int | None = None
    estimated_input_tokens: int | None = None
    latency_ms: int | None = None
    model: str | None = None
    prompt_version: int | None = None
    llm_error: str | None = None
    parse_error: str | None = None
    alert_sent: bool
    alert_error: str | None = None


class InsightsQuery(PaginationQuery):
    container: str | None = None
    classification: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    sort: Literal["created_at", "-created_at"] = Field(default="-created_at")


class InsightListResponse(BaseModel):
    items: list[InsightItem]
    offset: int = 0
    limit: int = 100
