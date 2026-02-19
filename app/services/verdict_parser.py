from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ValidationError, field_validator


class LLMVerdict(BaseModel):
    classification: str
    summary: str
    root_cause_hypothesis: str
    fix_suggestion: str
    confidence: float

    @field_validator("classification")
    @classmethod
    def validate_classification(cls, value: str) -> str:
        allowed = {"noise", "warning", "critical"}
        lowered = value.lower()
        if lowered not in allowed:
            raise ValueError("classification must be one of noise|warning|critical")
        return lowered

    @field_validator("confidence")
    @classmethod
    def validate_confidence(cls, value: float) -> float:
        if not (0.0 <= value <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0")
        return value


class VerdictParser:
    def parse(self, payload: str | dict[str, Any]) -> LLMVerdict:
        parsed: dict[str, Any]
        if isinstance(payload, str):
            parsed = json.loads(payload)
        else:
            parsed = payload
        return LLMVerdict.model_validate(parsed)

    def safe_parse(self, payload: str | dict[str, Any]) -> tuple[LLMVerdict | None, str | None]:
        try:
            verdict = self.parse(payload)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
            return None, str(exc)
        return verdict, None
