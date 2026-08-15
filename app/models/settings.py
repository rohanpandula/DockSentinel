from __future__ import annotations

from app.extensions import db
from app.time_utils import utcnow_naive


class Settings(db.Model):
    __tablename__ = "settings"

    id = db.Column(db.Integer, primary_key=True, default=1)
    llm_base_url = db.Column(db.String(255), nullable=False, default="http://host.docker.internal:11434/v1")
    llm_api_key = db.Column(db.String(255), nullable=False, default="ollama")
    llm_model = db.Column(db.String(255), nullable=False, default="llama3")
    llm_provider = db.Column(db.String(64), nullable=False, default="generic")
    llm_transport = db.Column(db.String(16), nullable=False, default="api")
    cli_backend = db.Column(db.String(64), nullable=False, default="codex")
    cli_timeout_seconds = db.Column(db.Integer, nullable=False, default=120)
    cli_max_retries = db.Column(db.Integer, nullable=False, default=1)

    telegram_token = db.Column(db.String(255), nullable=True)
    telegram_chat_id = db.Column(db.String(255), nullable=True)

    nightly_hour = db.Column(db.Integer, nullable=False, default=0)
    nightly_minute = db.Column(db.Integer, nullable=False, default=5)

    max_input_chars = db.Column(db.Integer, nullable=False, default=16000)
    max_input_tokens = db.Column(db.Integer, nullable=False, default=4000)
    reserved_output_tokens = db.Column(db.Integer, nullable=False, default=600)
    token_estimation_strategy = db.Column(db.String(32), nullable=False, default="chars")

    keyword_list = db.Column(
        db.Text,
        nullable=False,
        default="error,exception,fatal,panic,critical,refused,timeout",
    )

    alert_cooldown_minutes = db.Column(db.Integer, nullable=False, default=10)
    alert_rate_limit_count = db.Column(db.Integer, nullable=False, default=20)
    alert_rate_limit_window_seconds = db.Column(db.Integer, nullable=False, default=300)
    alert_min_classification = db.Column(db.String(16), nullable=False, default="critical")
    event_retention_days = db.Column(db.Integer, nullable=False, default=14)

    llm_timeout_seconds = db.Column(db.Integer, nullable=False, default=20)
    llm_max_retries = db.Column(db.Integer, nullable=False, default=2)

    # --- LLM call reduction settings ---
    dedup_window_seconds = db.Column(db.Integer, nullable=False, default=300)
    container_rate_limit_count = db.Column(db.Integer, nullable=False, default=10)
    container_rate_limit_window_seconds = db.Column(db.Integer, nullable=False, default=3600)
    keyword_flush_delay_lines = db.Column(db.Integer, nullable=False, default=5)

    # --- Coalescing (batch chunks per container before LLM call) ---
    chunk_coalesce_window_seconds = db.Column(db.Integer, nullable=False, default=0)

    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)

    @classmethod
    def singleton(cls) -> "Settings":
        row = db.session.get(cls, 1)
        if row is None:
            row = cls(id=1)
            db.session.add(row)
            db.session.commit()
        return row

    def as_dict(self) -> dict[str, object]:
        return {
            "llm_base_url": self.llm_base_url,
            "llm_api_key": self.llm_api_key,
            "llm_model": self.llm_model,
            "llm_provider": self.llm_provider,
            "llm_transport": self.llm_transport,
            "cli_backend": self.cli_backend,
            "cli_timeout_seconds": self.cli_timeout_seconds,
            "cli_max_retries": self.cli_max_retries,
            "telegram_token": self.telegram_token,
            "telegram_chat_id": self.telegram_chat_id,
            "nightly_hour": self.nightly_hour,
            "nightly_minute": self.nightly_minute,
            "max_input_chars": self.max_input_chars,
            "max_input_tokens": self.max_input_tokens,
            "reserved_output_tokens": self.reserved_output_tokens,
            "token_estimation_strategy": self.token_estimation_strategy,
            "keyword_list": self.keyword_list,
            "alert_cooldown_minutes": self.alert_cooldown_minutes,
            "alert_rate_limit_count": self.alert_rate_limit_count,
            "alert_rate_limit_window_seconds": self.alert_rate_limit_window_seconds,
            "alert_min_classification": self.alert_min_classification,
            "event_retention_days": self.event_retention_days,
            "llm_timeout_seconds": self.llm_timeout_seconds,
            "llm_max_retries": self.llm_max_retries,
            "dedup_window_seconds": self.dedup_window_seconds,
            "container_rate_limit_count": self.container_rate_limit_count,
            "container_rate_limit_window_seconds": self.container_rate_limit_window_seconds,
            "keyword_flush_delay_lines": self.keyword_flush_delay_lines,
            "chunk_coalesce_window_seconds": self.chunk_coalesce_window_seconds,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
