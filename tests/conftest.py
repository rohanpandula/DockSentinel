from __future__ import annotations

import pytest

from app import create_app
from app.extensions import db as _db


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("START_COORDINATOR", "false")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("RUNTIME_LOCK_PATH", str(tmp_path / "runtime.lock"))
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    app = create_app()
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def container(app):
    return app.extensions["services"]


@pytest.fixture
def db_session(app):
    with app.app_context():
        yield _db.session
