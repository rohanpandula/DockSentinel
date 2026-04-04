from __future__ import annotations

from typing import Any

from app.services.llm_client import LLMResult


class LLMCallService:
    def __init__(self, llm_client: Any) -> None:
        self._client = llm_client

    def call(
        self,
        *,
        messages: list[dict[str, str]],
        max_tokens: int,
        base_url: str,
        api_key: str,
        model: str,
        transport: str,
        cli_backend: str,
        timeout_seconds: int,
        max_retries: int,
        cli_timeout_seconds: int,
        cli_max_retries: int,
        temperature: float | None = None,
    ) -> LLMResult:
        resolved_timeout = cli_timeout_seconds if transport == "cli" else timeout_seconds
        resolved_retries = cli_max_retries if transport == "cli" else max_retries

        call_kwargs: dict[str, Any] = dict(
            transport=transport,
            cli_backend=cli_backend,
            base_url=base_url,
            api_key=api_key,
            model=model,
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
