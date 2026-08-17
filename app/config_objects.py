from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.settings import Settings


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    provider: str
    transport: str
    timeout_seconds: int
    max_retries: int
    cli_backend: str
    cli_timeout_seconds: int
    cli_max_retries: int
    extra_request_json: str = ""

    @classmethod
    def from_settings(cls, s: "Settings") -> "LLMConfig":
        return cls(
            base_url=s.llm_base_url,
            api_key=s.llm_api_key,
            model=s.llm_model,
            provider=s.llm_provider,
            transport=(s.llm_transport or "api").strip().lower(),
            timeout_seconds=s.llm_timeout_seconds,
            max_retries=s.llm_max_retries,
            cli_backend=s.cli_backend,
            cli_timeout_seconds=s.cli_timeout_seconds,
            cli_max_retries=s.cli_max_retries,
            extra_request_json=(getattr(s, "llm_extra_request_json", "") or ""),
        )


@dataclass(frozen=True)
class AlertConfig:
    cooldown_minutes: int
    rate_limit_count: int
    rate_limit_window_seconds: int
    telegram_token: str | None
    telegram_chat_id: str | None
    min_classification: str = "critical"
    min_confidence: float = 0.0

    @classmethod
    def from_settings(cls, s: "Settings") -> "AlertConfig":
        return cls(
            min_classification=(getattr(s, "alert_min_classification", None) or "critical"),
            min_confidence=float(getattr(s, "alert_min_confidence", 0.0) or 0.0),
            cooldown_minutes=s.alert_cooldown_minutes,
            rate_limit_count=s.alert_rate_limit_count,
            rate_limit_window_seconds=s.alert_rate_limit_window_seconds,
            telegram_token=s.telegram_token,
            telegram_chat_id=s.telegram_chat_id,
        )


@dataclass(frozen=True)
class IncidentConfig:
    """How the incident layer notifies. Never affects alert-worthiness."""

    resolve_after_minutes: int = 30
    reminder_hours: int = 0
    notify_on_resolve: bool = True

    @classmethod
    def from_settings(cls, s: "Settings") -> "IncidentConfig":
        return cls(
            resolve_after_minutes=max(1, int(getattr(s, "incident_resolve_after_minutes", 30) or 30)),
            reminder_hours=max(0, int(getattr(s, "incident_reminder_hours", 0) or 0)),
            notify_on_resolve=bool(getattr(s, "incident_notify_on_resolve", True)),
        )


@dataclass(frozen=True)
class CallReductionConfig:
    dedup_window_seconds: int
    container_rate_limit_count: int
    container_rate_limit_window_seconds: int
    keyword_flush_delay_lines: int

    @classmethod
    def from_settings(cls, s: "Settings") -> "CallReductionConfig":
        return cls(
            dedup_window_seconds=s.dedup_window_seconds,
            container_rate_limit_count=s.container_rate_limit_count,
            container_rate_limit_window_seconds=s.container_rate_limit_window_seconds,
            keyword_flush_delay_lines=s.keyword_flush_delay_lines,
        )


@dataclass(frozen=True)
class TelegramConfig:
    token: str | None
    chat_id: str | None

    @classmethod
    def from_settings(cls, s: "Settings") -> "TelegramConfig":
        return cls(token=s.telegram_token, chat_id=s.telegram_chat_id)


@dataclass(frozen=True)
class CLIConfig:
    backend: str
    timeout_seconds: int
    max_retries: int

    @classmethod
    def from_settings(cls, s: "Settings") -> "CLIConfig":
        return cls(
            backend=s.cli_backend,
            timeout_seconds=s.cli_timeout_seconds,
            max_retries=s.cli_max_retries,
        )
