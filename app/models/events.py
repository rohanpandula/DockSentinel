from __future__ import annotations

from app.extensions import db
from app.time_utils import utcnow_naive


class AnalysisEvent(db.Model):
    __tablename__ = "analysis_events"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive, index=True)

    container_id = db.Column(db.String(128), nullable=True, index=True)
    container_name = db.Column(db.String(255), nullable=True, index=True)

    status = db.Column(db.String(32), nullable=False, index=True)
    classification = db.Column(db.String(32), nullable=True, index=True)

    matched_keywords = db.Column(db.String(512), nullable=True)
    chunk_hash = db.Column(db.String(64), nullable=True, index=True)
    chunk_excerpt = db.Column(db.Text, nullable=True)

    summary = db.Column(db.Text, nullable=True)
    root_cause_hypothesis = db.Column(db.Text, nullable=True)
    fix_suggestion = db.Column(db.Text, nullable=True)
    confidence = db.Column(db.Float, nullable=True)

    input_chars = db.Column(db.Integer, nullable=True)
    estimated_input_tokens = db.Column(db.Integer, nullable=True)
    latency_ms = db.Column(db.Integer, nullable=True)

    model = db.Column(db.String(255), nullable=True)
    prompt_version = db.Column(db.Integer, nullable=True)

    llm_error = db.Column(db.Text, nullable=True)
    parse_error = db.Column(db.Text, nullable=True)

    alert_sent = db.Column(db.Boolean, nullable=False, default=False)
    alert_error = db.Column(db.Text, nullable=True)

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "container_id": self.container_id,
            "container_name": self.container_name,
            "status": self.status,
            "classification": self.classification,
            "matched_keywords": self.matched_keywords,
            "chunk_hash": self.chunk_hash,
            "chunk_excerpt": self.chunk_excerpt,
            "summary": self.summary,
            "root_cause_hypothesis": self.root_cause_hypothesis,
            "fix_suggestion": self.fix_suggestion,
            "confidence": self.confidence,
            "input_chars": self.input_chars,
            "estimated_input_tokens": self.estimated_input_tokens,
            "latency_ms": self.latency_ms,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "llm_error": self.llm_error,
            "parse_error": self.parse_error,
            "alert_sent": self.alert_sent,
            "alert_error": self.alert_error,
        }
