from __future__ import annotations

import os

from app import create_app
from app.models import ExclusionRule, PromptTemplate, SchemaVersion, SentinelState, Settings


def _build_app(tmp_path, monkeypatch, name: str):
    db_path = tmp_path / f"{name}.db"
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("START_COORDINATOR", "false")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("RUNTIME_LOCK_PATH", str(tmp_path / "runtime.lock"))
    return create_app()


def test_seed_data_created_once(tmp_path, monkeypatch):
    app1 = _build_app(tmp_path, monkeypatch, "seed")
    with app1.app_context():
        assert Settings.query.count() == 1
        assert SentinelState.query.count() == 1
        assert SchemaVersion.query.count() == 1
        assert ExclusionRule.query.count() == 4
        assert PromptTemplate.query.count() == 5

    app2 = _build_app(tmp_path, monkeypatch, "seed")
    with app2.app_context():
        assert Settings.query.count() == 1
        assert SentinelState.query.count() == 1
        assert SchemaVersion.query.count() == 1
        assert ExclusionRule.query.count() == 4
        assert PromptTemplate.query.count() == 5
