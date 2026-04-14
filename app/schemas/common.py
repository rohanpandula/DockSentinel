from __future__ import annotations

from pydantic import BaseModel, Field


class PaginationQuery(BaseModel):
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=500)


class ErrorResponse(BaseModel):
    error: str
