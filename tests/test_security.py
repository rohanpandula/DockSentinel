"""Regression tests for the review fixes: secret masking, CSRF/origin guard,
settings-form allowlist, optional basic auth, try-llm key exfil guard."""
from __future__ import annotations

import base64

from app import create_app
from app.models import LocalIssue, LocalIssueAction, LocalIssueStatus, Settings
from app.extensions import db


def _basic(user: str, pw: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


# ── secrets never echoed ─────────────────────────────────────────────


def test_settings_api_masks_secrets_and_keeps_them_on_masked_write(client):
    r = client.put("/api/settings", json={"llm_api_key": "sk-real", "telegram_token": "123:abc"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["llm_api_key"] == "********"
    assert body["telegram_token"] == "********"
    assert "sk-real" not in r.get_data(as_text=True)

    # Round-tripping the masked value (or blank) must not clobber the secret.
    r = client.put("/api/settings", json={"llm_api_key": "********", "telegram_token": ""})
    assert r.status_code == 200
    with client.application.app_context():
        s = Settings.singleton()
        assert s.llm_api_key == "sk-real"
        assert s.telegram_token == "123:abc"


def test_settings_page_does_not_render_secrets(client):
    client.put("/api/settings", json={"llm_api_key": "sk-render-me", "telegram_token": "999:tok"})
    html = client.get("/settings").get_data(as_text=True)
    assert "sk-render-me" not in html
    assert "999:tok" not in html


# ── web settings form: allowlist + validation + keep secrets ─────────


def test_settings_form_ignores_non_allowlisted_and_blank_secret(client):
    client.put("/api/settings", json={"llm_api_key": "sk-keep"})
    r = client.post("/settings", data={"id": "42", "llm_model": "llama3", "llm_api_key": "", "nightly_hour": "3"})
    assert r.status_code == 302
    with client.application.app_context():
        s = Settings.singleton()
        assert s.id == 1
        assert s.llm_model == "llama3"
        assert s.llm_api_key == "sk-keep"
        assert s.nightly_hour == 3


def test_settings_form_rejects_bad_values_with_400(client):
    r = client.post("/settings", data={"nightly_hour": "abc"})
    assert r.status_code == 400
    r = client.post("/settings", data={"nightly_hour": "99"})
    assert r.status_code == 400


def test_settings_api_keyword_flush_delay_accepts_int(client):
    r = client.put("/api/settings", json={"keyword_flush_delay_lines": 7})
    assert r.status_code == 200
    assert r.get_json()["keyword_flush_delay_lines"] == 7


# ── cross-site write rejection ───────────────────────────────────────


def test_cross_site_post_rejected(client):
    r = client.post("/settings", data={"llm_model": "evil"}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    r = client.put("/api/settings", json={"llm_model": "evil"}, headers={"Origin": "http://evil.example"})
    assert r.status_code == 403
    r = client.post("/api/sentinel/toggle", json={"enabled": True}, headers={"Referer": "http://evil.example/x"})
    assert r.status_code == 403


def test_same_origin_and_no_origin_posts_allowed(client):
    r = client.put("/api/settings", json={"llm_model": "ok1"}, headers={"Origin": "http://localhost"})
    assert r.status_code == 200
    r = client.put("/api/settings", json={"llm_model": "ok2"})
    assert r.status_code == 200
    # GETs are never blocked by the origin guard.
    r = client.get("/api/settings", headers={"Origin": "http://evil.example"})
    assert r.status_code == 200


def test_exclusion_delete_requires_post(client):
    r = client.post("/api/exclusions", json={"container_pattern": "redis"})
    rule_id = r.get_json()["id"]
    assert client.get(f"/exclusions/delete/{rule_id}").status_code == 405
    assert client.post(f"/exclusions/delete/{rule_id}").status_code == 302
    remaining = client.get("/api/exclusions").get_json()
    ids = [e["id"] for e in (remaining if isinstance(remaining, list) else remaining.get("items", []))]
    assert rule_id not in ids


# ── optional basic auth ──────────────────────────────────────────────


def test_basic_auth_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("START_COORDINATOR", "false")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'auth.db'}")
    monkeypatch.setenv("RUNTIME_LOCK_PATH", str(tmp_path / "runtime.lock"))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("BASIC_AUTH_USER", "admin")
    monkeypatch.setenv("BASIC_AUTH_PASSWORD", "hunter22")
    client = create_app().test_client()

    assert client.get("/api/health").status_code == 200  # healthcheck stays open
    r = client.get("/api/settings")
    assert r.status_code == 401
    assert "Basic" in r.headers["WWW-Authenticate"]
    assert client.get("/api/settings", headers=_basic("admin", "wrong")).status_code == 401
    assert client.get("/api/settings", headers=_basic("admin", "hunter22")).status_code == 200
    assert client.get("/dashboard").status_code == 401


# ── try-llm must not leak stored key to caller-chosen host ──────────


def test_try_llm_override_base_url_does_not_use_stored_key(client, monkeypatch):
    client.put("/api/settings", json={"llm_api_key": "sk-stored", "llm_base_url": "http://ollama:11434/v1"})
    with client.application.app_context():
        issue = LocalIssue(
            event_id=None,
            container_name="web",
            title="t",
            body="b",
            action=LocalIssueAction.APPROVE.value,
            status=LocalIssueStatus.OPEN.value,
        )
        db.session.add(issue)
        db.session.commit()
        issue_id = issue.id
        services = client.application.extensions["services"]

    seen: dict[str, object] = {}

    class _FakeResult:
        content = "ok"
        model = "m"
        latency_ms = 1

    def _fake_call(*, config, messages, max_tokens, **kw):
        seen["api_key"] = config.api_key
        seen["base_url"] = config.base_url
        return _FakeResult()

    monkeypatch.setattr(services.llm_call, "call", _fake_call)

    r = client.post(f"/api/issues/{issue_id}/try-llm", json={"prompt": "hi", "base_url": "http://attacker.example/v1"})
    assert r.status_code == 200, r.get_json()
    assert seen["base_url"] == "http://attacker.example/v1"
    assert seen["api_key"] == ""  # stored key withheld

    r = client.post(f"/api/issues/{issue_id}/try-llm", json={"prompt": "hi"})
    assert r.status_code == 200
    assert seen["api_key"] == "sk-stored"  # stored host still gets stored key

    r = client.post(f"/api/issues/{issue_id}/try-llm", json={"prompt": "hi", "base_url": "file:///etc/passwd"})
    assert r.status_code == 400


def test_ollama_models_rejects_non_http(client):
    r = client.get("/api/ollama/models?base_url=file:///etc")
    assert r.status_code == 400
