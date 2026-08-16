"""Container die/restart/OOM become first-class events and can alert."""
from __future__ import annotations

import json
from datetime import timedelta

from app.extensions import db
from app.models import AnalysisEvent, ExclusionRule, Settings
from app.services.docker_watcher import DockerWatcher
from app.time_utils import utcnow_naive


class _RecordingStrategy:
    def __init__(self, ok: bool = True):
        self.sent: list[str] = []
        self.ok = ok

    def send(self, message, config, reply_markup=None):
        self.sent.append(message)
        return (True, None, 7) if self.ok else (False, "boom", None)


def _sentinel(container, strategy=None):
    sentinel = container.sentinel
    sentinel.alert_service.strategy = strategy or _RecordingStrategy()
    sentinel.set_enabled(True)
    return sentinel


# --- classification -------------------------------------------------------


def test_die_nonzero_exit_is_critical_and_persisted(app, container):
    with app.app_context():
        sentinel = _sentinel(container)
        event = sentinel.handle_container_event("c1", "web", "die", {"exitCode": 137, "image": "nginx"})

        assert event.status == "container_event"
        assert event.classification == "critical"
        assert event.matched_keywords == "die"
        assert event.summary == "web exited with code 137 (OOM killed / SIGKILL)"
        assert json.loads(event.chunk_excerpt) == {"exitCode": 137, "image": "nginx"}
        assert event.llm_error is None and event.model is None  # no LLM call
        assert db.session.get(AnalysisEvent, event.id) is not None


def test_classification_matrix(app, container):
    with app.app_context():
        sentinel = _sentinel(container)
        cases = [
            ("oom", {}, "critical"),
            ("health_status: unhealthy", {}, "critical"),
            ("die", {"exitCode": 0}, "noise"),
            ("die", {"exitCode": 1}, "critical"),
            ("restart", {}, "warning"),
            ("kill", {"signal": "9"}, "noise"),
            ("die", {"exitCode": 137}, "critical"),  # SIGKILL is not an operator stop
            ("start", {}, "noise"),
            ("stop", {}, "noise"),
            ("kill", {"signal": "15"}, "noise"),
            ("die", {"exitCode": 143}, "noise"),  # die right after kill(TERM) = operator stop
            ("die", {"exitCode": 143}, "critical"),  # mark is consumed; a second die is real
        ]
        for status, attrs, expected in cases:
            event = sentinel.handle_container_event("c1", "web", status, attrs)
            assert event.classification == expected, (status, attrs)


def test_operator_stop_is_noise_and_not_counted_in_storm(app, container):
    with app.app_context():
        strategy = _RecordingStrategy()
        sentinel = _sentinel(container, strategy)
        settings = Settings.singleton()
        settings.restart_alert_count = 2
        settings.restart_alert_window_minutes = 10
        db.session.commit()

        # docker stop: kill(15) -> die(143) -> stop
        sentinel.handle_container_event("c1", "web", "kill", {"signal": "15"})
        die = sentinel.handle_container_event("c1", "web", "die", {"exitCode": 143})
        stop = sentinel.handle_container_event("c1", "web", "stop", {})
        assert die.classification == "noise"
        assert die.summary == "web stopped by operator (exit 143)"
        assert die.matched_keywords == "die:stopped"
        assert stop.classification == "noise" and stop.summary == "web stopping"

        # kill without a signal is also treated as TERM
        sentinel.handle_container_event("c1", "web", "kill", {})
        die2 = sentinel.handle_container_event("c1", "web", "die", {"exitCode": 0})
        assert die2.classification == "noise"
        assert die2.summary == "web stopped by operator (exit 0)"

        # Two operator stops did not trip the storm (threshold 2).
        assert strategy.sent == []
        # A real crash counts from zero: one more die is still under threshold.
        crash = sentinel.handle_container_event("c1", "web", "die", {"exitCode": 1})
        assert crash.classification == "critical"
        assert crash.alert_sent is not True and strategy.sent == []


def test_operator_stop_mark_expires_after_20s(app, container, monkeypatch):
    import app.services.sentinel as sentinel_mod

    with app.app_context():
        sentinel = _sentinel(container)
        clock = [1000.0]
        monkeypatch.setattr(sentinel_mod.time, "monotonic", lambda: clock[0])
        sentinel.handle_container_event("c1", "web", "kill", {"signal": "SIGTERM"})
        clock[0] += 25.0
        die = sentinel.handle_container_event("c1", "web", "die", {"exitCode": 143})
        assert die.classification == "critical"
        assert die.matched_keywords == "die"

        # Different container name is not affected by web's stop mark.
        sentinel.handle_container_event("c1", "web", "stop", {})
        other = sentinel.handle_container_event("c2", "db", "die", {"exitCode": 1})
        assert other.classification == "critical"


def test_disabled_or_excluded_records_nothing(app, container):
    with app.app_context():
        sentinel = _sentinel(container)
        sentinel.set_enabled(False)
        assert sentinel.handle_container_event("c1", "web", "die", {"exitCode": 1}) is None

        sentinel.set_enabled(True)
        db.session.add(ExclusionRule(container_pattern="web", enabled=True))
        db.session.commit()
        assert sentinel.handle_container_event("c1", "web-1", "die", {"exitCode": 1}) is None
        assert AnalysisEvent.query.filter_by(status="container_event").count() == 0


# --- restart storm ----------------------------------------------------------


def test_restart_storm_alerts_once_at_threshold_and_respects_cooldown(app, container):
    with app.app_context():
        strategy = _RecordingStrategy()
        sentinel = _sentinel(container, strategy)
        settings = Settings.singleton()
        settings.restart_alert_count = 3
        settings.restart_alert_window_minutes = 10
        settings.alert_cooldown_minutes = 10
        db.session.commit()

        e1 = sentinel.handle_container_event("c1", "web", "die", {"exitCode": 1})
        e2 = sentinel.handle_container_event("c1", "web", "die", {"exitCode": 1})
        assert strategy.sent == []
        assert not e1.alert_sent and not e2.alert_sent

        e3 = sentinel.handle_container_event("c1", "web", "die", {"exitCode": 137})
        assert e3.alert_sent is True
        assert strategy.sent == ["🔁 RESTART STORM · web · 3 exits in 10 min · last exit code 137"]

        # Fourth exit inside the cooldown: no second alert.
        e4 = sentinel.handle_container_event("c1", "web", "die", {"exitCode": 1})
        assert e4.alert_sent is False
        assert e4.alert_error == "restart storm alert suppressed by cooldown"
        assert len(strategy.sent) == 1

        # A different container is not affected by web's cooldown.
        for _ in range(3):
            last = sentinel.handle_container_event("c2", "db", "oom", {})
        assert last.alert_sent is True
        assert len(strategy.sent) == 2
        assert "db" in strategy.sent[1]


def test_restart_storm_ignores_events_outside_window(app, container):
    with app.app_context():
        strategy = _RecordingStrategy()
        sentinel = _sentinel(container, strategy)
        settings = Settings.singleton()
        settings.restart_alert_count = 2
        settings.restart_alert_window_minutes = 5
        db.session.commit()

        old = AnalysisEvent(
            container_id="c1",
            container_name="web",
            status="container_event",
            classification="critical",
            matched_keywords="die",
            created_at=utcnow_naive() - timedelta(minutes=30),
        )
        db.session.add(old)
        db.session.commit()

        event = sentinel.handle_container_event("c1", "web", "die", {"exitCode": 1})
        assert event.alert_sent is False
        assert strategy.sent == []


def test_restart_storm_respects_global_rate_limit(app, container):
    with app.app_context():
        strategy = _RecordingStrategy()
        sentinel = _sentinel(container, strategy)
        settings = Settings.singleton()
        settings.restart_alert_count = 1
        settings.alert_rate_limit_count = 1
        settings.alert_rate_limit_window_seconds = 300
        db.session.commit()
        db.session.add(
            AnalysisEvent(container_id="x", container_name="x", status="analyzed", alert_sent=True)
        )
        db.session.commit()

        event = sentinel.handle_container_event("c1", "web", "die", {"exitCode": 1})
        assert event.alert_sent is False
        assert event.alert_error == "global rate limit exceeded"
        assert strategy.sent == []


def test_restart_settings_exposed_and_validated(app, client):
    with app.app_context():
        assert Settings.singleton().restart_alert_count == 3
        assert Settings.singleton().restart_alert_window_minutes == 10
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["restart_alert_count"] == 3
    assert body["restart_alert_window_minutes"] == 10

    resp = client.put("/api/settings", json={"restart_alert_count": 5, "restart_alert_window_minutes": 15})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    with app.app_context():
        assert Settings.singleton().restart_alert_count == 5
        assert Settings.singleton().restart_alert_window_minutes == 15

    resp = client.put("/api/settings", json={"restart_alert_count": 0})
    assert resp.status_code == 400


# --- watcher dispatch -------------------------------------------------------


class _FakeEventsClient:
    def __init__(self, events):
        self._events = events

    def events(self, decode=True):
        yield from self._events

    def close(self):
        pass


def test_watcher_dispatches_container_events(monkeypatch):
    seen = []
    watcher = DockerWatcher(
        lambda *a: None,
        lambda n: False,
        container_event_callback=lambda cid, name, status, attrs: seen.append((cid, name, status, attrs)),
    )
    monkeypatch.setattr(watcher, "_attach_container", lambda cid: None)
    monkeypatch.setattr(watcher, "_detach_container", lambda cid, name: None)
    watcher._client = _FakeEventsClient(
        [
            {"Type": "image", "status": "pull", "id": "img"},
            {"Type": "container", "status": "die", "id": "c1", "Actor": {"Attributes": {"name": "web", "exitCode": "137"}}},
            {"Type": "container", "status": "oom", "id": "c1", "Actor": {"Attributes": {"name": "web"}}},
            {"Type": "container", "status": "health_status: unhealthy", "id": "c2", "Actor": {"Attributes": {"name": "api"}}},
            {"Type": "container", "status": "attach", "id": "c2", "Actor": {"Attributes": {"name": "api"}}},
            {"Type": "container", "status": "start", "id": "c3", "Actor": {"Attributes": {}}},
            {"Type": "container", "status": "stop", "id": "c3", "Actor": {"Attributes": {"name": "w"}}},
            {"Type": "container", "status": "die", "Actor": {"Attributes": {"name": "no-id"}}},
        ]
    )
    watcher._watch_events()

    assert [(s[0], s[1], s[2]) for s in seen] == [
        ("c1", "web", "die"),
        ("c1", "web", "oom"),
        ("c2", "api", "health_status: unhealthy"),
        ("c3", "c3", "start"),
        ("c3", "w", "stop"),
    ]
    assert seen[0][3]["exitCode"] == 137  # coerced to int


def test_watcher_callback_exception_does_not_kill_event_stream(monkeypatch):
    seen = []

    def cb(cid, name, status, attrs):
        if cid == "bad":
            raise RuntimeError("db locked")
        seen.append(cid)

    watcher = DockerWatcher(lambda *a: None, lambda n: False, container_event_callback=cb)
    monkeypatch.setattr(watcher, "_attach_container", lambda cid: None)
    monkeypatch.setattr(watcher, "_detach_container", lambda cid, name: None)
    watcher._client = _FakeEventsClient(
        [
            {"Type": "container", "status": "die", "id": "bad", "Actor": {"Attributes": {"name": "a"}}},
            {"Type": "container", "status": "die", "id": "ok", "Actor": {"Attributes": {"name": "b"}}},
        ]
    )
    watcher._watch_events()
    assert seen == ["ok"]


def test_watcher_without_callback_ignores_events(monkeypatch):
    watcher = DockerWatcher(lambda *a: None, lambda n: False)
    detached = []
    monkeypatch.setattr(watcher, "_attach_container", lambda cid: None)
    monkeypatch.setattr(watcher, "_detach_container", lambda cid, name: detached.append(cid))
    watcher._client = _FakeEventsClient(
        [{"Type": "container", "status": "die", "id": "c1", "Actor": {"Attributes": {"name": "web"}}}]
    )
    watcher._watch_events()
    assert detached == ["c1"]


# --- briefing ---------------------------------------------------------------


class _DummyLLM:
    def __init__(self):
        self.messages = None

    def chat_completion(self, **kwargs):
        from app.services.llm_client import LLMResult

        self.messages = kwargs.get("messages")
        return LLMResult(content="## Container Restarts\n- web: 2", model="demo", latency_ms=1, usage={})


class _FailingLLM:
    def chat_completion(self, **kwargs):
        raise RuntimeError("down")


def _seed_restart_events():
    now = utcnow_naive()
    for name, status, code in [("web", "die", 137), ("web", "die", 1), ("db", "oom", None), ("web", "start", None)]:
        db.session.add(
            AnalysisEvent(
                container_id=name,
                container_name=name,
                status="container_event",
                classification="critical",
                matched_keywords=status,
                summary=f"{name} {status} {code}",
                created_at=now,
            )
        )
    db.session.add(
        AnalysisEvent(container_id="web", container_name="web", status="analyzed", classification="warning", summary="slow")
    )
    db.session.commit()


def test_briefing_evidence_counts_container_events(app, container):
    with app.app_context():
        _seed_restart_events()
        briefing = container.briefing
        llm = _DummyLLM()
        briefing.llm_call_service._client = llm
        briefing.generate_report()

        user_msg = llm.messages[-1]["content"]
        assert "Container Restarts" in user_msg
        assert "- web: 2 exit(s)" in user_msg
        assert "- db: 1 exit(s)" in user_msg
        assert "container=web classification=warning alert_sent=False summary=slow" in user_msg
        # lifecycle rows are not fed into the generic Events list
        assert "summary=web die 137" not in user_msg


def test_briefing_fallback_lists_restarts(app, container):
    with app.app_context():
        _seed_restart_events()
        briefing = container.briefing
        briefing.llm_call_service._client = _FailingLLM()
        report = briefing.generate_report()

        assert report.status == "llm_error"
        assert "- web: 2 exit(s)" in report.markdown_content
        assert "- db: 1 exit(s)" in report.markdown_content
        assert "inferred" not in report.markdown_content
        assert "Total analyzed events: 1" in report.markdown_content


def test_watcher_handles_docker29_events_without_legacy_fields():
    """Docker 29 / API 1.52 events have only Action + Actor.ID (no top-level status/id)."""
    from app.services.docker_watcher import DockerWatcher, _event_fields

    ev = {"Type": "container", "Action": "die", "Actor": {"ID": "abc123", "Attributes": {"name": "web", "exitCode": "137"}}}
    assert _event_fields(ev) == ("die", "abc123", {"name": "web", "exitCode": "137"})
    legacy = {"Type": "container", "status": "start", "id": "zzz", "Action": "start", "Actor": {"ID": "zzz", "Attributes": {"name": "w"}}}
    assert _event_fields(legacy)[:2] == ("start", "zzz")

    seen = []
    detached = []

    class _Client:
        def events(self, decode=True):
            yield ev
        def close(self):
            pass

    w = DockerWatcher(lambda *a: None, lambda n: False, container_event_callback=lambda cid, name, status, attrs: seen.append((cid, name, status, attrs.get("exitCode"))))
    w._client = _Client()
    w._detach_container = lambda cid, name: detached.append(cid)
    w._watch_events()
    assert seen == [("abc123", "web", "die", 137)]
    assert detached == ["abc123"]
