from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_serializer

SECRET_FIELDS = ("llm_api_key", "telegram_token")
MASK = "********"

# Fields an operator may change through the API or web form. Anything else on
# the Settings row (id, updated_at, ...) is server-managed.
ALLOWED_SETTINGS_FIELDS = frozenset({
    "llm_base_url", "llm_api_key", "llm_model", "llm_provider", "llm_transport",
    "cli_backend", "cli_timeout_seconds", "cli_max_retries",
    "telegram_token", "telegram_chat_id", "nightly_hour", "nightly_minute",
    "max_input_chars", "max_input_tokens", "reserved_output_tokens",
    "token_estimation_strategy", "keyword_list", "alert_cooldown_minutes",
    "alert_rate_limit_count", "alert_rate_limit_window_seconds",
    "llm_timeout_seconds", "llm_max_retries", "dedup_window_seconds",
    "container_rate_limit_count", "container_rate_limit_window_seconds",
    "keyword_flush_delay_lines", "chunk_coalesce_window_seconds",
    "restart_alert_count", "restart_alert_window_minutes",
})


def mask_secret(value: str | None) -> str | None:
    """Never echo secrets back; only reveal whether one is set."""
    if value is None or value == "":
        return value
    return MASK



class SettingsSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_provider: str | None = None
    llm_transport: str | None = None
    cli_backend: str | None = None
    cli_timeout_seconds: int | None = None
    cli_max_retries: int | None = None
    telegram_token: str | None = None
    telegram_chat_id: str | None = None
    nightly_hour: int | None = None
    nightly_minute: int | None = None
    max_input_chars: int | None = None
    max_input_tokens: int | None = None
    reserved_output_tokens: int | None = None
    token_estimation_strategy: str | None = None
    keyword_list: str | None = None
    alert_cooldown_minutes: int | None = None
    alert_rate_limit_count: int | None = None
    alert_rate_limit_window_seconds: int | None = None
    llm_timeout_seconds: int | None = None
    llm_max_retries: int | None = None
    dedup_window_seconds: int | None = None
    container_rate_limit_count: int | None = None
    container_rate_limit_window_seconds: int | None = None
    keyword_flush_delay_lines: int | None = None
    chunk_coalesce_window_seconds: int | None = None
    restart_alert_count: int | None = None
    restart_alert_window_minutes: int | None = None
    updated_at: datetime | None = None

    @field_serializer("llm_api_key", "telegram_token")
    def _mask(self, value: str | None) -> str | None:
        return mask_secret(value)


class UpdateSettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    llm_provider: str | None = None
    llm_transport: str | None = None
    cli_backend: str | None = None
    cli_timeout_seconds: int | None = Field(default=None, ge=1)
    cli_max_retries: int | None = Field(default=None, ge=0)
    telegram_token: str | None = None
    telegram_chat_id: str | None = None
    nightly_hour: int | None = Field(default=None, ge=0, le=23)
    nightly_minute: int | None = Field(default=None, ge=0, le=59)
    max_input_chars: int | None = Field(default=None, ge=1)
    max_input_tokens: int | None = Field(default=None, ge=1)
    reserved_output_tokens: int | None = Field(default=None, ge=1)
    token_estimation_strategy: str | None = None
    keyword_list: str | None = None
    alert_cooldown_minutes: int | None = Field(default=None, ge=0)
    alert_rate_limit_count: int | None = Field(default=None, ge=0)
    alert_rate_limit_window_seconds: int | None = Field(default=None, ge=1)
    llm_timeout_seconds: int | None = Field(default=None, ge=1)
    llm_max_retries: int | None = Field(default=None, ge=0)
    dedup_window_seconds: int | None = Field(default=None, ge=0)
    container_rate_limit_count: int | None = Field(default=None, ge=0)
    container_rate_limit_window_seconds: int | None = Field(default=None, ge=1)
    keyword_flush_delay_lines: int | None = Field(default=None, ge=0)
    chunk_coalesce_window_seconds: int | None = Field(default=None, ge=0)
    restart_alert_count: int | None = Field(default=None, ge=1)
    restart_alert_window_minutes: int | None = Field(default=None, ge=1)


class TestLLMResponse(BaseModel):
    ok: bool
    error: str | None = None
