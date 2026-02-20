from __future__ import annotations

from app import create_app


def _build_app(tmp_path, monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("START_COORDINATOR", "false")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    monkeypatch.setenv("RUNTIME_LOCK_PATH", str(tmp_path / "runtime.lock"))
    return create_app()


class _LLMOk:
    def chat_completion(self, **kwargs):
        return {"ok": True}

    def complete(self, **kwargs):
        return {"ok": True}


class _LLMFail:
    def chat_completion(self, **kwargs):
        raise RuntimeError("llm connection failed")

    def complete(self, **kwargs):
        raise RuntimeError("llm connection failed")


def test_core_api_endpoints(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    client = app.test_client()

    response = client.get("/api/health")
    assert response.status_code == 200

    response = client.get("/api/settings")
    assert response.status_code == 200

    response = client.put("/api/settings", json={"llm_model": "gpt-4o-mini", "nightly_hour": 2})
    assert response.status_code == 200
    assert response.get_json()["llm_model"] == "gpt-4o-mini"

    response = client.get("/api/exclusions")
    assert response.status_code == 200

    response = client.post("/api/exclusions", json={"container_pattern": "redis"})
    assert response.status_code in {200, 201}
    rule_id = response.get_json()["id"]

    response = client.get("/api/prompts")
    assert response.status_code == 200
    key = response.get_json()["items"][0]["key"]

    response = client.put(f"/api/prompts/{key}", json={"content": "updated prompt"})
    assert response.status_code == 200

    response = client.post(f"/api/prompts/{key}/reset")
    assert response.status_code == 200

    response = client.post("/api/sentinel/toggle", json={"enabled": True})
    assert response.status_code == 200
    response = client.get("/api/sentinel/status")
    assert response.status_code == 200

    response = client.get("/api/insights")
    assert response.status_code == 200

    response = client.delete(f"/api/exclusions/{rule_id}")
    assert response.status_code == 200

    response = client.post("/api/telegram/test")
    assert response.status_code == 400

    response = client.post("/api/reports/generate")
    assert response.status_code == 201

    report_id = response.get_json()["id"]
    response = client.get(f"/api/reports/{report_id}")
    assert response.status_code == 200


def test_settings_test_llm_success(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    app.extensions["services"]["llm_client"] = _LLMOk()
    client = app.test_client()

    response = client.post("/api/settings/test-llm")
    assert response.status_code == 200
    assert response.get_json()["ok"] is True


def test_settings_test_llm_failure(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    app.extensions["services"]["llm_client"] = _LLMFail()
    client = app.test_client()

    response = client.post("/api/settings/test-llm")
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_settings_include_call_reduction_fields(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    client = app.test_client()

    response = client.get("/api/settings")
    data = response.get_json()
    assert "dedup_window_seconds" in data
    assert "container_rate_limit_count" in data
    assert "container_rate_limit_window_seconds" in data
    assert "keyword_flush_delay_lines" in data

    # Test updating new fields via API
    response = client.put("/api/settings", json={
        "dedup_window_seconds": 600,
        "container_rate_limit_count": 5,
    })
    assert response.status_code == 200
    assert response.get_json()["dedup_window_seconds"] == 600
    assert response.get_json()["container_rate_limit_count"] == 5
