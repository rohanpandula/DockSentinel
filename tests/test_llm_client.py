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
