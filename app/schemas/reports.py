from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.common import PaginationQuery


class ReportItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    status: str
    markdown_content: str | None = None
    model: str | None = None
    prompt_version: int | None = None
    error: str | None = None


class ReportsQuery(PaginationQuery):
    pass


class ReportListResponse(BaseModel):
    items: list[ReportItem]
    offset: int = 0
    limit: int = 100


class ReportDetailResponse(ReportItem):
    pass
