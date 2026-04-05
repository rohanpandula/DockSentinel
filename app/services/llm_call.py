from __future__ import annotations

from typing import Any

from app.config_objects import LLMConfig
from app.services.llm_client import LLMResult


class LLMCallService:
    def __init__(self, llm_client: Any) -> None:
        self._client = llm_client

    def call(
        self,
        *,
        config: LLMConfig,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float | None = None,
    ) -> LLMResult:
        resolved_timeout = config.cli_timeout_seconds if config.transport == "cli" else config.timeout_seconds
        resolved_retries = config.cli_max_retries if config.transport == "cli" else config.max_retries

        call_kwargs: dict[str, Any] = dict(
            transport=config.transport,
            cli_backend=config.cli_backend,
            base_url=config.base_url,
            api_key=config.api_key,
            model=config.model,
            messages=messages,
            timeout_seconds=resolved_timeout,
            max_retries=resolved_retries,
            max_tokens=max_tokens,
        )
        if temperature is not None:
            call_kwargs["temperature"] = temperature

        if hasattr(self._client, "complete"):
            return self._client.complete(**call_kwargs)

        # Compatibility path for test doubles that only implement chat_completion.
        call_kwargs.pop("transport", None)
        call_kwargs.pop("cli_backend", None)
        return self._client.chat_completion(**call_kwargs)
