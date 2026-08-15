from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.services.cli_backends import CLIBackendRunner


# Hosts / models known to accept OpenAI-style ``response_format: {"type": "json_object"}``
# on /chat/completions. Ollama's OpenAI-compatible endpoint supports it too. When the
# base_url or model matches and the conversation asks for JSON, we send it once and
# fall back to a plain request if the server rejects the parameter with HTTP 400.
JSON_MODE_HOST_ALLOWLIST: tuple[str, ...] = (
    "api.openai.com",
    "openai.azure.com",
    "openrouter.ai",
    "api.groq.com",
    "api.together.xyz",
    "api.deepseek.com",
    "api.mistral.ai",
    "api.fireworks.ai",
    ":11434",  # ollama
    "localhost",
    "127.0.0.1",
    "host.docker.internal",
)
JSON_MODE_MODEL_PREFIXES: tuple[str, ...] = ("gpt-", "o1", "o3", "o4", "llama", "qwen", "mistral", "deepseek", "gemma", "phi")

_JSON_HINT = re.compile(r"\bJSON\b", re.IGNORECASE)


def json_mode_supported(base_url: str, model: str) -> bool:
    url = (base_url or "").lower()
    name = (model or "").lower()
    if any(host in url for host in JSON_MODE_HOST_ALLOWLIST):
        return True
    return any(name.startswith(prefix) for prefix in JSON_MODE_MODEL_PREFIXES)


def wants_json(messages: list[dict[str, str]]) -> bool:
    """True when the prompt explicitly asks for a JSON reply (sentinel triage does; briefings don't)."""
    return any(_JSON_HINT.search(m.get("content", "") or "") for m in messages)


def _mentions_response_format(response: Any) -> bool:
    try:
        return "response_format" in (response.text or "")
    except Exception:
        return False


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
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        use_json_mode = json_mode_supported(base_url, model) and wants_json(messages)
        if use_json_mode:
            payload["response_format"] = {"type": "json_object"}

        backoff_seconds = 0.5
        last_error: str | None = None

        for attempt in range(max_retries + 1):
            start = time.monotonic()
            try:
                with httpx.Client(timeout=timeout_seconds) as client:
                    response = client.post(endpoint, headers=headers, json=payload)
                    if (
                        use_json_mode
                        and response.status_code == 400
                        and _mentions_response_format(response)
                    ):
                        # Server doesn't support json mode: retry once without it
                        # (and don't send it again on later retries).
                        payload.pop("response_format", None)
                        use_json_mode = False
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
