from __future__ import annotations

from app import create_app


def _build_app(tmp_path, monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("START_COORDINATOR", "false")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'ui.db'}")
    monkeypatch.setenv("RUNTIME_LOCK_PATH", str(tmp_path / "runtime.lock"))
    return create_app()


def test_ui_routes_smoke(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    client = app.test_client()

    routes = [
        "/",
        "/dashboard",
        "/settings",
        "/exclusions",
        "/insights",
        "/reports",
        "/prompts",
    ]

    for route in routes:
        response = client.get(route)
        assert response.status_code in {200, 302}, f"unexpected status for {route}: {response.status_code}"
