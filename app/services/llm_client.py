from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.services.cli_backends import CLIBackendRunner


@dataclass(slots=True)
class LLMResult:
    content: str
    model: str
    latency_ms: int
    usage: dict[str, Any]


class LLMClient:
    def __init__(self, cli_runner: CLIBackendRunner | None = None) -> None:
        self.cli_runner = cli_runner

    def complete(
        self,
        *,
        transport: str,
        cli_backend: str,
        base_url: str,
        api_key: str,
        model: str,
        messages: list[dict[str, str]],
        timeout_seconds: int,
        max_retries: int,
        max_tokens: int,
        temperature: float = 0.1,
    ) -> LLMResult:
        if transport == "cli":
            return self.chat_completion_cli(
                backend=cli_backend,
                model=model,
                messages=messages,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
                max_tokens=max_tokens,
                temperature=temperature,
            )

        return self.chat_completion(
            base_url=base_url,
            api_key=api_key,
            model=model,
            messages=messages,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    def chat_completion(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        messages: list[dict[str, str]],
        timeout_seconds: int,
        max_retries: int,
        max_tokens: int,
        temperature: float = 0.1,
    ) -> LLMResult:
        endpoint = f"{base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        backoff_seconds = 0.5
        last_error: str | None = None

        for attempt in range(max_retries + 1):
            start = time.monotonic()
            try:
                with httpx.Client(timeout=timeout_seconds) as client:
                    response = client.post(endpoint, headers=headers, json=payload)
                latency_ms = int((time.monotonic() - start) * 1000)

                if response.status_code >= 500 or response.status_code == 429:
                    last_error = f"temporary status code {response.status_code}"
                    if attempt < max_retries:
                        time.sleep(backoff_seconds)
                        backoff_seconds *= 2
                        continue

                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                return LLMResult(content=content, model=data.get("model", model), latency_ms=latency_ms, usage=usage)
            except (KeyError, IndexError, ValueError, httpx.HTTPError) as exc:
                last_error = str(exc)
                if attempt < max_retries:
                    time.sleep(backoff_seconds)
                    backoff_seconds *= 2
                    continue

        raise RuntimeError(last_error or "unknown llm error")

    @staticmethod
    def _render_cli_prompt(
        *,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> str:
        sections = [
            "You are being called by DockSentinel via a CLI backend.",
            f"Target model label: {model}",
            f"Response token budget: {max_tokens}",
            f"Temperature hint: {temperature}",
            "Use the conversation below and respond to the latest user instruction.",
        ]

        for message in messages:
            role = message.get("role", "user").upper()
            content = message.get("content", "")
            sections.append(f"{role}:\n{content}")

        return "\n\n".join(sections)

    def chat_completion_cli(
        self,
        *,
        backend: str,
        model: str,
        messages: list[dict[str, str]],
        timeout_seconds: int,
        max_retries: int,
        max_tokens: int,
        temperature: float = 0.1,
    ) -> LLMResult:
        if self.cli_runner is None:
            raise RuntimeError("cli backend runner is not configured")

        prompt = self._render_cli_prompt(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        response = self.cli_runner.run(
            backend=backend,
            prompt=prompt,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
        )
        return LLMResult(
            content=response.content,
            model=f"cli:{response.backend}",
            latency_ms=response.latency_ms,
            usage={},
        )
