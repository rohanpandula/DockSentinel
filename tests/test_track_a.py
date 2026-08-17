from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from app import create_app
from app.extensions import db
from app.models import AnalysisEvent, ExclusionRule, Settings
from app.models.local_issue import LocalIssue
from app.services.llm_client import LLMResult
from app.time_utils import utcnow_naive


def _llm(classification: str):
    class _LLM:
        def chat_completion(self, **kwargs):
            return LLMResult(
                content=(
                    f'{{"classification":"{classification}","summary":"s","root_cause_hypothesis":"r",'
                    '"fix_suggestion":"f","confidence":0.9}'
                ),
                model="demo",
                latency_ms=1,
                usage={},
            )

    return _LLM()


class _Strategy:
    def __init__(self):
        self.sent = []

    def send(self, message, config, reply_markup=None):
        self.sent.append(message)
        return True, None, 7


def _build_app(tmp_path, monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("START_COORDINATOR", "false")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'a.db'}")
    monkeypatch.setenv("RUNTIME_LOCK_PATH", str(tmp_path / "runtime.lock"))
    return create_app()


def _prep(app, classification="critical"):
    sentinel = app.extensions["services"].sentinel
    sentinel.llm_call_service._client = _llm(classification)
    strategy = _Strategy()
    sentinel.alert_service.strategy = strategy
    sentinel.set_enabled(True)
    settings = Settings.singleton()
    settings.dedup_window_seconds = 0
    db.session.commit()
    return sentinel, strategy


# --- item 9: analyze_container_now ---------------------------------------------------------


class _FakeDockerClient:
    def __init__(self, name="excluded-svc"):
        self.closed = False
        container = SimpleNamespace(id="cid1", name=name, logs=lambda **kw: b"error: boom\n")
        self.containers = SimpleNamespace(get=lambda ident: container)

    def close(self):
        self.closed = True


def test_analyze_now_refuses_excluded_and_closes_client(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    with app.app_context():
        sentinel, _ = _prep(app)
        db.session.add(ExclusionRule(container_pattern="excluded", enabled=True))
        db.session.commit()
        fake = _FakeDockerClient()
        monkeypatch.setattr("app.services.sentinel.docker.from_env", lambda: fake)
        with pytest.raises(ValueError, match="exclusion rule"):
            sentinel.analyze_container_now("excluded-svc")
        assert fake.closed is True
        assert AnalysisEvent.query.count() == 0


def test_analyze_now_api_returns_400_and_ui_surfaces_error(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    with app.app_context():
        _prep(app)
        db.session.add(ExclusionRule(container_pattern="excluded", enabled=True))
        db.session.commit()
    monkeypatch.setattr("app.services.sentinel.docker.from_env", lambda: _FakeDockerClient())
    client = app.test_client()
    resp = client.post("/api/sentinel/analyze-now", json={"container": "excluded-svc"})
    assert resp.status_code == 400
    assert "exclusion rule" in resp.get_json()["error"]

    resp = client.post("/sentinel/analyze", data={"container": "excluded-svc"})
    assert resp.status_code == 302
    assert "analyze_error=" in resp.headers["Location"]
    assert "exclusion" in resp.headers["Location"]


def test_analyze_now_happy_path_closes_client(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    with app.app_context():
        sentinel, _ = _prep(app)
        fake = _FakeDockerClient(name="postgres")
        monkeypatch.setattr("app.services.sentinel.docker.from_env", lambda: fake)
        event = sentinel.analyze_container_now("postgres")
        assert event.status == "analyzed"
        assert fake.closed is True


# --- item 11: cooldown keyed on (container_id, classification) ------------------------------


def test_cooldown_suppresses_different_chunk_same_container(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    with app.app_context():
        sentinel, strategy = _prep(app)
        first = sentinel.process_chunk(container_id="c1", container_name="api", chunk_text="fatal error 1 pid=1")
        second = sentinel.process_chunk(container_id="c1", container_name="api", chunk_text="fatal error 2 pid=2")
        assert first.alert_sent is True
        assert second.alert_sent is False
        assert second.alert_error == "duplicate alert suppressed by cooldown"
        assert len(strategy.sent) == 1


def test_cooldown_does_not_cross_containers_or_expired_window(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    with app.app_context():
        sentinel, strategy = _prep(app)
        sentinel.process_chunk(container_id="c1", container_name="api", chunk_text="fatal error 1")
        other = sentinel.process_chunk(container_id="c2", container_name="db", chunk_text="fatal error 1")
        assert other.alert_sent is True
        # Age the previous alerts beyond the cooldown window.
        for e in AnalysisEvent.query.all():
            e.created_at = utcnow_naive() - timedelta(minutes=60)
        db.session.commit()
        again = sentinel.process_chunk(container_id="c1", container_name="api", chunk_text="fatal error 3")
        # The cooldown gate is what this test guards, and it no longer suppresses:
        # had it still been in force the error would read "duplicate alert
        # suppressed by cooldown". Instead the event reaches the incident layer,
        # which recognises the still-open "api" incident and folds this
        # occurrence into the message already in the chat rather than pinging again.
        assert again.alert_sent is False
        assert again.alert_error.startswith("incident #")
        assert "×2" in again.alert_error
        assert len(strategy.sent) == 2


def test_repo_find_recent_alert_for_container_ignores_unsent(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    with app.app_context():
        repo = app.extensions["services"].event_repo
        db.session.add(AnalysisEvent(container_id="c1", container_name="n", status="analyzed", classification="critical", alert_sent=False))
        db.session.add(AnalysisEvent(container_id="c1", container_name="n", status="analyzed", classification="warning", alert_sent=True))
        db.session.commit()
        since = utcnow_naive() - timedelta(minutes=10)
        assert repo.find_recent_alert_for_container("c1", "critical", since) is None
        assert repo.find_recent_alert_for_container("c1", "warning", since) is not None


# --- close the loop: recently rejected issue -----------------------------------------------


def test_recently_rejected_issue_suppresses_alert(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    with app.app_context():
        sentinel, strategy = _prep(app)
        db.session.add(
            LocalIssue(container_name="api", title="t", body="b", status="rejected", action="reject")
        )
        db.session.commit()
        event = sentinel.process_chunk(container_id="c1", container_name="api", chunk_text="fatal error")
        assert event.alert_sent is False
        assert event.alert_error == "suppressed: recently rejected"
        assert strategy.sent == []


def test_old_rejected_issue_does_not_suppress(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    with app.app_context():
        sentinel, strategy = _prep(app)
        issue = LocalIssue(container_name="api", title="t", body="b", status="rejected", action="reject")
        db.session.add(issue)
        db.session.commit()
        issue.created_at = utcnow_naive() - timedelta(hours=25)
        db.session.commit()
        event = sentinel.process_chunk(container_id="c1", container_name="api", chunk_text="fatal error")
        assert event.alert_sent is True


# --- alert_min_classification -------------------------------------------------------------


def test_warning_alerts_when_threshold_lowered(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    with app.app_context():
        sentinel, strategy = _prep(app, classification="warning")
        event = sentinel.process_chunk(container_id="c1", container_name="api", chunk_text="error thing")
        assert event.classification == "warning"
        assert event.alert_sent is None or event.alert_sent is False
        Settings.singleton().alert_min_classification = "warning"
        db.session.commit()
        event2 = sentinel.process_chunk(container_id="c1", container_name="api", chunk_text="timeout waiting for upstream")
        assert event2.alert_sent is True
        assert len(strategy.sent) == 1


def test_settings_api_validates_min_classification(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    client = app.test_client()
    resp = client.put("/api/settings", json={"alert_min_classification": "bogus"})
    assert resp.status_code == 400
    resp = client.put("/api/settings", json={"alert_min_classification": "warning", "event_retention_days": 3})
    assert resp.status_code == 200
    data = client.get("/api/settings").get_json()
    assert data["alert_min_classification"] == "warning"
    assert data["event_retention_days"] == 3
    resp = client.put("/api/settings", json={"event_retention_days": 0})
    assert resp.status_code == 400


# --- item 15: prune ---------------------------------------------------------------------------


def test_prune_deletes_only_low_value_old_rows(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    with app.app_context():
        repo = app.extensions["services"].event_repo
        old = utcnow_naive() - timedelta(days=30)
        for status in ["skipped", "dedup_skipped", "rate_limited", "queued", "excluded", "analyzed", "parse_error", "llm_error"]:
            db.session.add(AnalysisEvent(container_id="c", container_name="n", status=status, created_at=old))
        db.session.add(AnalysisEvent(container_id="c", container_name="n", status="skipped"))
        db.session.commit()
        deleted = repo.prune(utcnow_naive() - timedelta(days=14))
        assert deleted == 5
        remaining = sorted(e.status for e in AnalysisEvent.query.all())
        assert remaining == ["analyzed", "llm_error", "parse_error", "skipped"]
        # explicit status list is intersected with the safe set
        assert repo.prune(utcnow_naive(), statuses={"analyzed"}) == 0
        assert AnalysisEvent.query.filter_by(status="analyzed").count() == 1


def test_coordinator_prune_job_and_schedule(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    with app.app_context():
        svc = app.extensions["services"]
        Settings.singleton().event_retention_days = 2
        db.session.commit()
        db.session.add(AnalysisEvent(container_id="c", container_name="n", status="skipped", created_at=utcnow_naive() - timedelta(days=3)))
        db.session.commit()
    coord = svc.coordinator
    coord._run_prune_job()
    with app.app_context():
        assert AnalysisEvent.query.count() == 0

    from apscheduler.schedulers.background import BackgroundScheduler

    sched = BackgroundScheduler()
    coord._scheduler = sched
    with app.app_context():
        coord.refresh_schedule()
    job = sched.get_job("prune-events")
    assert job is not None
    assert job.max_instances == 1
    assert "hour='3'" in str(job.trigger) and "minute='15'" in str(job.trigger)
    coord._scheduler = None


# --- migration 0006 -----------------------------------------------------------------------------


def test_migration_0006_ids():
    import importlib.util, pathlib

    path = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0006_alert_threshold_retention.py"
    spec = importlib.util.spec_from_file_location("m0006", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.revision == "a1b2c3d4e5f6"
    assert mod.down_revision == "c9a0d7f2e411"


# --- nightly briefing -> telegram ---------------------------------------------------------------


class _Notifier:
    def __init__(self):
        self.calls = []

    def send_message(self, token, chat_id, text, **kw):
        self.calls.append((token, chat_id, text))
        return True, None, 1


def test_nightly_job_pushes_briefing_to_telegram(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    svc = app.extensions["services"]
    coord = svc.coordinator
    notifier = _Notifier()
    coord.telegram_notifier = notifier
    report = SimpleNamespace(status="generated", markdown_content="# Report\n" + "x" * 5000)
    coord.briefing_service = SimpleNamespace(generate_report=lambda: report)

    with app.app_context():
        s = Settings.singleton()
        s.telegram_token = "tok"
        s.telegram_chat_id = "123"
        db.session.commit()
    coord._run_nightly_job()
    assert len(notifier.calls) == 1
    token, chat, text = notifier.calls[0]
    assert (token, chat) == ("tok", "123")
    assert len(text) <= 3900
    assert text.startswith("📋 DockSentinel nightly briefing")


def test_nightly_job_skips_telegram_when_unconfigured_or_failed(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)
    coord = app.extensions["services"].coordinator
    notifier = _Notifier()
    coord.telegram_notifier = notifier
    coord.briefing_service = SimpleNamespace(
        generate_report=lambda: SimpleNamespace(status="generated", markdown_content="hi")
    )
    coord._run_nightly_job()  # no token/chat configured
    assert notifier.calls == []

    with app.app_context():
        s = Settings.singleton()
        s.telegram_token = "tok"
        s.telegram_chat_id = "123"
        db.session.commit()
    coord.briefing_service = SimpleNamespace(
        generate_report=lambda: SimpleNamespace(status="llm_error", markdown_content="fallback")
    )
    coord._run_nightly_job()
    assert notifier.calls == []


def test_analyze_now_forces_llm_even_without_keywords(app, container, monkeypatch):
    """Manual 'Analyze now' promises to bypass the prefilter — a quiet log must still reach the LLM."""
    import types
    from app.models import SentinelState

    class _R:
        content = '{"classification":"noise","summary":"all quiet","root_cause_hypothesis":"n/a","fix_suggestion":"none","confidence":0.9}'
        model = "m"
        latency_ms = 1

    class _Cont:
        id = "abc"
        name = "quiet"
        def logs(self, **kw):
            return b"INFO started\nINFO ready\n"

    class _Client:
        containers = types.SimpleNamespace(get=lambda name: _Cont())
        def close(self):
            pass

    with app.app_context():
        SentinelState.singleton()
        monkeypatch.setattr("app.services.sentinel.docker.from_env", lambda: _Client())
        monkeypatch.setattr(container.sentinel.llm_call_service, "call", lambda **kw: _R())
        ev = container.sentinel.analyze_container_now("quiet")
        assert ev.status == "analyzed", ev.status
        assert ev.classification == "noise"
