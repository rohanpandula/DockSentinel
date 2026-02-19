from __future__ import annotations

from enum import StrEnum

from app.extensions import db
from app.time_utils import utcnow_naive


class PromptKey(StrEnum):
    SENTINEL_SYSTEM = "SENTINEL_SYSTEM"
    SENTINEL_ANALYSIS = "SENTINEL_ANALYSIS"
    JSON_OUTPUT_GUARD = "JSON_OUTPUT_GUARD"
    NIGHTLY_SYSTEM = "NIGHTLY_SYSTEM"
    NIGHTLY_REPORT = "NIGHTLY_REPORT"


DEFAULT_PROMPTS: dict[PromptKey, str] = {
    PromptKey.SENTINEL_SYSTEM: (
        "You are an SRE log triage assistant. Prioritize operational risk, use direct evidence "
        "from logs, avoid speculation, and keep recommendations actionable."
    ),
    PromptKey.SENTINEL_ANALYSIS: (
        "You receive Docker container logs. Respond with ONLY one JSON object using keys: "
        "classification, summary, root_cause_hypothesis, fix_suggestion, confidence. "
        "classification must be one of noise, warning, critical. confidence must be between 0.0 and 1.0."
    ),
    PromptKey.JSON_OUTPUT_GUARD: (
        "Output must be strict JSON only. Do not include markdown, code fences, or extra text. "
        "Do not include keys outside the required schema."
    ),
    PromptKey.NIGHTLY_SYSTEM: (
        "You are generating a concise operator-focused daily health briefing for container operations. "
        "Summarize critical incidents, trends, and practical next actions."
    ),
    PromptKey.NIGHTLY_REPORT: (
        "Generate markdown using sections exactly in this order: Executive Summary, Critical Incidents, "
        "Warnings and Trends, Container Restarts, Recommended Actions (Next 24h)."
    ),
}


class PromptTemplate(db.Model):
    __tablename__ = "prompt_templates"

    key = db.Column(db.String(64), primary_key=True)
    content = db.Column(db.Text, nullable=False)
    default_content = db.Column(db.Text, nullable=False)
    version = db.Column(db.Integer, nullable=False, default=1)
    is_default = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "content": self.content,
            "default_content": self.default_content,
            "version": self.version,
            "is_default": self.is_default,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
