from __future__ import annotations

import json
import re
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


_FENCE_RE = re.compile(r"^\s*```(?:json|JSON)?\s*\n?(.*?)\n?\s*```\s*$", re.DOTALL)


def extract_json_object(text: str) -> str:
    """Return the JSON object embedded in an LLM reply.

    Models — CLI backends especially — routinely wrap JSON in ``` fences or
    add a sentence of prose before/after despite the JSON-only guard prompt.
    Strategy: strip a whole-message fence, else take the outermost balanced
    ``{...}`` (tracking strings so braces inside values don't confuse it).
    Returns the original text if no object is found (json.loads then reports
    the real error).
    """
    stripped = text.strip()
    m = _FENCE_RE.match(stripped)
    if m:
        stripped = m.group(1).strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    start = stripped.find("{")
    if start == -1:
        return text
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(stripped)):
        ch = stripped[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return stripped[start : i + 1]
    return text


class VerdictParser:
    def parse(self, payload: str | dict[str, Any]) -> LLMVerdict:
        parsed: dict[str, Any]
        if isinstance(payload, str):
            parsed = json.loads(extract_json_object(payload))
        else:
            parsed = payload
        return LLMVerdict.model_validate(parsed)

    def safe_parse(self, payload: str | dict[str, Any]) -> tuple[LLMVerdict | None, str | None]:
        try:
            verdict = self.parse(payload)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
            return None, str(exc)
        return verdict, None
