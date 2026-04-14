from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


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
    updated_at: datetime | None = None


class UpdateSettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    keyword_flush_delay_lines: str | None = None
    chunk_coalesce_window_seconds: int | None = None


class TestLLMResponse(BaseModel):
    ok: bool
    error: str | None = None
