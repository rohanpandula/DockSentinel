from __future__ import annotations

import json

from app.services.llm_client import LLMResult


class _LLMStub:
    """Deterministic LLM that returns a critical classification as LLMResult."""

    _CONTENT = json.dumps(
        {
            "classification": "critical",
            "summary": "disk full",
            "root_cause_hypothesis": "out of space",
            "fix_suggestion": "df -h",
            "confidence": 0.9,
        }
    )

    def complete(self, **kwargs):
        return LLMResult(
            content=self._CONTENT,
            model="stub",
            latency_ms=1,
            usage={},
        )

    def chat_completion(self, **kwargs):
        return self.complete(**kwargs)


class _FakeAlertStrategy:
    def __init__(self):
        self.calls: list[str] = []

    def send(self, message, config, reply_markup=None):
        self.calls.append(message)
        return True, None, 42


def test_full_sentinel_pipeline_persists_event_and_exposes_via_api(client, container, db_session):
    """Prefilter → dedup → rate-limit → LLM → alert → repo → DB → HTTP."""
    fake = _FakeAlertStrategy()
    container.sentinel.llm_call_service._client = _LLMStub()
    container.sentinel.alert_service.strategy = fake
    container.sentinel.set_enabled(True)

    event = container.sentinel.process_chunk(
        container_id="abc123",
        container_name="postgres",
        chunk_text="ERROR: disk full at /data (fatal)",
    )

    assert event.status == "analyzed"
    assert event.classification == "critical"
    assert event.alert_sent is True
    assert len(fake.calls) == 1

    resp = client.get("/api/insights?limit=10")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["items"], "persisted event should surface via /api/insights"
    first = body["items"][0]
    assert first["classification"] == "critical"
    assert first["alert_sent"] is True
    assert first["container_name"] == "postgres"
