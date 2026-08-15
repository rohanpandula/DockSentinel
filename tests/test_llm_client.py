from __future__ import annotations

import httpx

from app.services.llm_client import LLMClient


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("bad status", request=None, response=None)


class _FakeClient:
    calls = 0

    def __init__(self, timeout):
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, endpoint, headers, json):
        _FakeClient.calls += 1
        if _FakeClient.calls == 1:
            return _FakeResponse(500, {})
        return _FakeResponse(
            200,
            {
                "model": json["model"],
                "choices": [{"message": {"content": '{"classification":"noise","summary":"ok","root_cause_hypothesis":"none","fix_suggestion":"none","confidence":0.2}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 8},
            },
        )


def test_llm_client_retries(monkeypatch):
    monkeypatch.setattr("app.services.llm_client.httpx.Client", _FakeClient)

    client = LLMClient()
    result = client.chat_completion(
        base_url="http://localhost:11434/v1",
        api_key="x",
        model="demo",
        messages=[{"role": "user", "content": "ping"}],
        timeout_seconds=5,
        max_retries=1,
        max_tokens=32,
    )

    assert _FakeClient.calls == 2
    assert "classification" in result.content
    assert result.model == "demo"


class _JsonModeClient:
    """Rejects response_format with HTTP 400 once; records payloads."""

    payloads: list = []

    def __init__(self, timeout):
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, endpoint, headers, json):
        _JsonModeClient.payloads.append(dict(json))
        if "response_format" in json:
            resp = _FakeResponse(400, {"error": "unknown field response_format"})
            resp.text = '{"error": "unknown field response_format"}'
            return resp
        return _FakeResponse(
            200,
            {"model": json["model"], "choices": [{"message": {"content": "{}"}}], "usage": {}},
        )


def test_llm_client_json_mode_sent_then_dropped_on_400(monkeypatch):
    monkeypatch.setattr("app.services.llm_client.httpx.Client", _JsonModeClient)
    _JsonModeClient.payloads = []

    client = LLMClient()
    result = client.chat_completion(
        base_url="http://host.docker.internal:11434/v1",
        api_key="x",
        model="llama3",
        messages=[{"role": "user", "content": "Reply with ONLY one JSON object"}],
        timeout_seconds=5,
        max_retries=0,
        max_tokens=32,
    )

    assert result.content == "{}"
    assert len(_JsonModeClient.payloads) == 2
    assert _JsonModeClient.payloads[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in _JsonModeClient.payloads[1]


def test_llm_client_no_json_mode_for_markdown_prompt(monkeypatch):
    monkeypatch.setattr("app.services.llm_client.httpx.Client", _JsonModeClient)
    _JsonModeClient.payloads = []

    LLMClient().chat_completion(
        base_url="http://host.docker.internal:11434/v1",
        api_key="x",
        model="llama3",
        messages=[{"role": "user", "content": "Generate markdown sections"}],
        timeout_seconds=5,
        max_retries=0,
        max_tokens=32,
    )
    assert len(_JsonModeClient.payloads) == 1
    assert "response_format" not in _JsonModeClient.payloads[0]


def test_json_mode_supported_heuristic():
    from app.services.llm_client import json_mode_supported

    assert json_mode_supported("https://api.openai.com/v1", "gpt-4o")
    assert json_mode_supported("http://ollama:11434/v1", "whatever")
    assert json_mode_supported("http://example.com/v1", "qwen2.5")
    assert not json_mode_supported("http://example.com/v1", "custom-model")
