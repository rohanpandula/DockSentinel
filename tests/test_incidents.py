"""Incident layer: signature normalisation, one-message-per-problem dedupe,
severity escalation, reminders, auto-resolve, and legacy passthrough."""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.config_objects import AlertConfig
from app.extensions import db
from app.models import AnalysisEvent, Incident, Settings
from app.repositories.incidents import IncidentRepository
from app.services.alerts import AlertService
from app.services.incidents import (
    IncidentService,
    format_duration,
    incident_signature,
    normalize_summary,
)
from app.time_utils import utcnow_naive


# ── fakes ──────────────────────────────────────────────────────


class _Notifier:
    """Captures edit_message_text calls."""

    def __init__(self):
        self.edits: list[dict] = []

    def edit_message_text(self, token, chat_id, message_id, text):
        self.edits.append(
            {"token": token, "chat_id": chat_id, "message_id": message_id, "text": text}
        )


class _Strategy:
    """Captures sends and hands back an incrementing telegram message id."""

    def __init__(self, notifier=None):
        self.sent: list[tuple[str, object]] = []
        self.notifier = notifier or _Notifier()
        self._next_id = 100

    def send(self, message, config, reply_markup=None):
        self._next_id += 1
        self.sent.append((message, reply_markup))
        return True, None, self._next_id

    @property
    def edits(self):
        return self.notifier.edits


class _EventRepo:
    """All alert-worthiness gates open — the incident layer is what's under test."""

    def find_recent_alert_for_container(self, *a, **k):
        return None

    def count_recent_alerts(self, *a, **k):
        return 0


def _cfg():
    return AlertConfig(
        telegram_token="tok",
        telegram_chat_id="chat-1",
        cooldown_minutes=0,
        rate_limit_count=100,
        rate_limit_window_seconds=60,
    )


def _event(summary="db connection refused", classification="critical", name="api", eid=1):
    return AnalysisEvent(
        id=eid,
        container_id="c1",
        container_name=name,
        status="analyzed",
        classification=classification,
        summary=summary,
        confidence=0.9,
    )


@pytest.fixture
def svc(app):
    """IncidentService + its fake transport, inside an app context."""
    with app.app_context():
        notifier = _Notifier()
        strategy = _Strategy(notifier)
        service = IncidentService(repo=IncidentRepository(), notifier=notifier, strategy=strategy)
        yield SimpleNamespace(service=service, strategy=strategy, notifier=notifier)


# ── signature normalisation ────────────────────────────────────


def test_signature_ignores_numbers_ids_and_timestamps():
    """The same failure reported with different numbers, ports, pids, hex ids
    and timestamps is ONE problem."""
    base = incident_signature("api", "critical", "connection refused to 10.0.0.5:5432 after 3 retries")
    assert base == incident_signature(
        "api", "critical", "connection refused to 10.0.0.9:5433 after 17 retries"
    )
    # timestamps, in either ISO or clock form
    assert incident_signature("api", "critical", "2026-08-15T10:00:00Z disk full on /var") == (
        incident_signature("api", "critical", "2026-08-16T23:59:59Z disk full on /var")
    )
    assert incident_signature("api", "critical", "12:00:01 disk full on /var") == (
        incident_signature("api", "critical", "23:14:59 disk full on /var")
    )
    # container ids / sha digests / uuids
    assert incident_signature("api", "critical", "worker 4f3a9b2c1d8e died") == (
        incident_signature("api", "critical", "worker 9e8d7c6b5a41 died")
    )
    assert incident_signature(
        "api", "critical", "job 550e8400-e29b-41d4-a716-446655440000 failed"
    ) == incident_signature(
        "api", "critical", "job 6ba7b810-9dad-41d1-80b4-00c04fd430c8 failed"
    )
    # case and whitespace are not identity
    assert base == incident_signature(
        "api", "critical", "CONNECTION   REFUSED to 10.0.0.5:5432   after 3 retries"
    )


def test_signature_separates_different_problems_containers_and_severities():
    refused = incident_signature("api", "critical", "connection refused to postgres")
    assert refused != incident_signature("api", "critical", "out of memory killing worker")
    # different container, same error
    assert refused != incident_signature("db", "critical", "connection refused to postgres")
    # different severity, same error
    assert refused != incident_signature("api", "warning", "connection refused to postgres")


def test_signature_shape_and_normalisation_details():
    sig = incident_signature("api", "critical", "boom")
    assert len(sig) == 32 and all(c in "0123456789abcdef" for c in sig)
    # empty / None summaries are stable, not crashes
    assert incident_signature("api", "critical", None) == incident_signature("api", "critical", "")
    # only the first 120 chars of the normalised summary count
    long_a = "x" * 130 + " alpha"
    long_b = "x" * 130 + " beta"
    assert incident_signature("api", "critical", long_a) == incident_signature("api", "critical", long_b)
    # English words that happen to be hex-ish are left alone
    assert "facade" in normalize_summary("Facade misconfigured")
    assert normalize_summary("error 4f3a9b2c1d8e here") == "error # here"


def test_format_duration_units():
    assert format_duration(timedelta(seconds=30)) == "30s"
    assert format_duration(timedelta(minutes=45)) == "45m"
    assert format_duration(timedelta(hours=2, minutes=15)) == "2h 15m"
    assert format_duration(timedelta(days=3, hours=4)) == "3d 4h"
    assert format_duration(timedelta(seconds=-5)) == "0s"


# ── first occurrence sends, recurrences edit ───────────────────


def test_first_occurrence_sends_and_opens_an_incident(svc):
    sent, error, message_id = svc.service.notify(_event(), _cfg(), "🚨 CRITICAL · api\nbody")
    db.session.commit()

    assert (sent, error) == (True, None)
    assert message_id == 101
    assert len(svc.strategy.sent) == 1
    assert svc.strategy.edits == []

    incident = Incident.query.one()
    assert incident.status == "open"
    assert incident.occurrence_count == 1
    assert incident.notify_count == 1
    assert incident.telegram_message_id == 101
    assert incident.telegram_chat_id == "chat-1"
    assert incident.last_notified_at is not None
    # every body carries the marker the surface layer keys off
    assert svc.strategy.sent[0][0].endswith(f"incident #{incident.id}")


def test_recurrences_edit_in_place_exactly_once_each(svc):
    """Five occurrences of one problem = ONE send and four edits."""
    for _ in range(5):
        result = svc.service.notify(_event(), _cfg(), "🚨 CRITICAL · api\nbody")
    db.session.commit()

    assert len(svc.strategy.sent) == 1, "a persistent problem must not re-ping"
    assert len(svc.strategy.edits) == 4

    incident = Incident.query.one()
    assert incident.occurrence_count == 5
    assert incident.notify_count == 1

    # the last call reports why it stayed quiet
    sent, error, message_id = result
    assert sent is False
    assert message_id is None
    assert error == f"incident #{incident.id} updated (×5)"

    # the edits count up, target the stored message, and stamp "last seen"
    assert [e["message_id"] for e in svc.strategy.edits] == [101, 101, 101, 101]
    for n, edit in enumerate(svc.strategy.edits, start=2):
        first_line, *_rest = edit["text"].splitlines()
        assert first_line == f"🚨 CRITICAL · api ×{n}"
        assert edit["text"].splitlines()[-1].startswith("last seen ")
        assert edit["text"].endswith(f"UTC · incident #{incident.id}")
        assert edit["chat_id"] == "chat-1"
        assert edit["token"] == "tok"


def test_distinct_problems_get_distinct_incidents_and_messages(svc):
    svc.service.notify(_event(summary="db connection refused"), _cfg(), "a")
    svc.service.notify(_event(summary="out of memory"), _cfg(), "b")
    svc.service.notify(_event(summary="db connection refused", name="db"), _cfg(), "c")
    db.session.commit()

    assert len(svc.strategy.sent) == 3
    assert svc.strategy.edits == []
    assert Incident.query.count() == 3


def test_resolved_incident_does_not_capture_new_occurrences(svc):
    svc.service.notify(_event(), _cfg(), "a")
    db.session.commit()
    incident = Incident.query.one()
    incident.status = "resolved"
    db.session.commit()

    svc.service.notify(_event(), _cfg(), "a")
    db.session.commit()
    assert len(svc.strategy.sent) == 2
    assert Incident.query.count() == 2


# ── severity escalation ────────────────────────────────────────


def test_severity_escalation_sends_a_new_message(svc):
    svc.service.notify(_event(classification="warning"), _cfg(), "⚠️ WARNING · api\nbody")
    svc.service.notify(_event(classification="warning"), _cfg(), "⚠️ WARNING · api\nbody")
    assert len(svc.strategy.sent) == 1 and len(svc.strategy.edits) == 1

    sent, error, message_id = svc.service.notify(
        _event(classification="critical"), _cfg(), "🚨 CRITICAL · api\nbody"
    )
    db.session.commit()

    assert (sent, error) == (True, None), "getting worse must ping, not edit silently"
    assert message_id == 102
    assert len(svc.strategy.sent) == 2
    assert len(svc.strategy.edits) == 1, "escalation sends instead of editing"

    incident = Incident.query.one()
    assert incident.classification == "critical"
    assert incident.telegram_message_id == 102
    assert incident.notify_count == 2
    assert incident.occurrence_count == 3


def test_severity_drop_stays_quiet(svc):
    """A critical incident that recurs as a warning is the same problem getting
    no worse — fold it in silently and keep the incident at its high-water mark."""
    svc.service.notify(_event(classification="critical"), _cfg(), "🚨 CRITICAL · api\nbody")
    sent, error, _ = svc.service.notify(
        _event(classification="warning"), _cfg(), "⚠️ WARNING · api\nbody"
    )
    db.session.commit()

    assert sent is False
    assert error.endswith("(×2)")
    incident = Incident.query.one()
    assert incident.classification == "critical"
    assert len(svc.strategy.sent) == 1 and len(svc.strategy.edits) == 1


def test_escalation_rekeys_so_later_criticals_match_directly(svc):
    svc.service.notify(_event(classification="warning"), _cfg(), "⚠️ WARNING · api\nbody")
    svc.service.notify(_event(classification="critical"), _cfg(), "🚨 CRITICAL · api\nbody")
    db.session.commit()
    incident = Incident.query.one()
    assert incident.signature == incident_signature("api", "critical", "db connection refused")

    svc.service.notify(_event(classification="critical"), _cfg(), "🚨 CRITICAL · api\nbody")
    db.session.commit()
    assert Incident.query.one().occurrence_count == 3
    assert len(svc.strategy.sent) == 2


# ── reminder window ────────────────────────────────────────────


def test_reminder_window_off_by_default_never_repings(svc):
    assert Settings.singleton().incident_reminder_hours == 0
    svc.service.notify(_event(), _cfg(), "a")
    db.session.commit()
    Incident.query.one().last_notified_at = utcnow_naive() - timedelta(days=30)
    db.session.commit()

    svc.service.notify(_event(), _cfg(), "a")
    assert len(svc.strategy.sent) == 1


def test_reminder_window_repings_a_still_open_incident(svc):
    settings = Settings.singleton()
    settings.incident_reminder_hours = 6
    db.session.commit()

    svc.service.notify(_event(), _cfg(), "🚨 CRITICAL · api\nbody")
    db.session.commit()
    incident = Incident.query.one()

    # inside the window: still silent
    incident.last_notified_at = utcnow_naive() - timedelta(hours=5)
    db.session.commit()
    sent, _, _ = svc.service.notify(_event(), _cfg(), "🚨 CRITICAL · api\nbody")
    assert sent is False
    assert len(svc.strategy.sent) == 1

    # past the window: ping again on the next occurrence
    incident.last_notified_at = utcnow_naive() - timedelta(hours=7)
    db.session.commit()
    sent, error, message_id = svc.service.notify(_event(), _cfg(), "🚨 CRITICAL · api\nbody")
    db.session.commit()

    assert (sent, error) == (True, None)
    assert len(svc.strategy.sent) == 2
    incident = Incident.query.one()
    assert incident.notify_count == 2
    assert incident.telegram_message_id == message_id
    assert incident.occurrence_count == 3


# ── auto-resolve ───────────────────────────────────────────────


def _open_incident(svc, minutes_quiet: int, occurrences: int = 3):
    svc.service.notify(_event(), _cfg(), "🚨 CRITICAL · api\nbody")
    db.session.commit()
    incident = Incident.query.one()
    incident.occurrence_count = occurrences
    incident.first_seen_at = utcnow_naive() - timedelta(hours=2)
    incident.last_seen_at = utcnow_naive() - timedelta(minutes=minutes_quiet)
    db.session.commit()
    svc.strategy.sent.clear()
    svc.notifier.edits.clear()
    return incident


def test_resolve_stale_closes_edits_and_announces(svc):
    incident = _open_incident(svc, minutes_quiet=45)
    assert Settings.singleton().incident_resolve_after_minutes == 30

    resolved = svc.service.resolve_stale()

    assert [i.id for i in resolved] == [incident.id]
    incident = Incident.query.one()
    assert incident.status == "resolved"
    assert incident.resolved_at is not None

    # the message already in the chat is rewritten in place
    assert len(svc.strategy.edits) == 1
    text = svc.strategy.edits[0]["text"]
    assert text.splitlines()[0].startswith("✅ RESOLVED · ")
    assert "🚨 CRITICAL · api" in text.splitlines()[0]
    assert text.splitlines()[1] == f"resolved after 2h 0m, ×3 · incident #{incident.id}"

    # and a short resolve notice goes out
    assert len(svc.strategy.sent) == 1
    notice = svc.strategy.sent[0][0]
    assert notice == f"✅ RESOLVED · api · was open 2h 0m · ×3 · incident #{incident.id}"


def test_resolve_stale_respects_notify_on_resolve_off(svc):
    settings = Settings.singleton()
    settings.incident_notify_on_resolve = False
    db.session.commit()
    _open_incident(svc, minutes_quiet=45)

    svc.service.resolve_stale()

    assert Incident.query.one().status == "resolved"
    assert len(svc.strategy.edits) == 1, "the in-place edit always happens"
    assert svc.strategy.sent == [], "but no new notice when the setting is off"


def test_resolve_stale_leaves_recent_incidents_open(svc):
    _open_incident(svc, minutes_quiet=5)
    assert svc.service.resolve_stale() == []
    assert Incident.query.one().status == "open"
    assert svc.strategy.sent == [] and svc.strategy.edits == []


def test_resolve_after_setting_controls_the_window(svc):
    settings = Settings.singleton()
    settings.incident_resolve_after_minutes = 120
    db.session.commit()
    _open_incident(svc, minutes_quiet=45)

    assert svc.service.resolve_stale() == []
    assert Incident.query.one().status == "open"


def test_a_resolved_problem_that_returns_opens_a_fresh_incident(svc):
    first = _open_incident(svc, minutes_quiet=45)
    svc.service.resolve_stale()
    svc.strategy.sent.clear()

    sent, error, _ = svc.service.notify(_event(), _cfg(), "🚨 CRITICAL · api\nbody")
    db.session.commit()

    assert (sent, error) == (True, None)
    assert Incident.query.count() == 2
    reopened = Incident.query.filter(Incident.id != first.id).one()
    assert reopened.status == "open" and reopened.occurrence_count == 1


# ── AlertService integration ───────────────────────────────────


def _alert_service(app, with_incidents: bool):
    notifier = _Notifier()
    strategy = _Strategy(notifier)
    service = None
    if with_incidents:
        service = IncidentService(repo=IncidentRepository(), notifier=notifier, strategy=strategy)
    return (
        AlertService(strategy=strategy, event_repo=_EventRepo(), incident_service=service),
        strategy,
    )


def test_alert_service_without_incident_service_keeps_legacy_behaviour(app):
    """incident_service=None must behave exactly as before: one message per
    alert-worthy event, no incident rows, no edits."""
    with app.app_context():
        alerts, strategy = _alert_service(app, with_incidents=False)
        for _ in range(3):
            sent, error, message_id = alerts.maybe_send(_event(), _cfg())
            assert (sent, error) == (True, None)
            assert message_id is not None
        assert len(strategy.sent) == 3
        assert strategy.edits == []
        assert Incident.query.count() == 0
        # ...and no "incident #" marker leaks into the body
        assert "incident #" not in strategy.sent[0][0]


def test_alert_service_maybe_send_routes_through_incidents(app):
    with app.app_context():
        alerts, strategy = _alert_service(app, with_incidents=True)
        for _ in range(3):
            alerts.maybe_send(_event(), _cfg())
        db.session.commit()

        assert len(strategy.sent) == 1
        assert len(strategy.edits) == 2
        assert Incident.query.one().occurrence_count == 3
        assert "incident #" in strategy.sent[0][0]


def test_alert_service_escalation_routes_through_incidents(app):
    with app.app_context():
        alerts, strategy = _alert_service(app, with_incidents=True)
        alerts.maybe_send_escalation(_event(classification="warning"), _cfg(), 3, 60)
        alerts.maybe_send_escalation(_event(classification="warning"), _cfg(), 4, 60)
        db.session.commit()

        assert len(strategy.sent) == 1
        assert len(strategy.edits) == 1
        assert strategy.sent[0][0].startswith("⚠️ PERSISTENT WARNING · api")
        assert Incident.query.one().occurrence_count == 2


def test_alert_service_send_plain_dedupes_restart_storms(app):
    with app.app_context():
        alerts, strategy = _alert_service(app, with_incidents=True)
        text = "🔁 RESTART STORM · api · 3 exits in 10 min · last exit code 137"
        sent, _, _ = alerts.send_plain(text, _cfg(), container_name="api")
        assert sent is True
        sent, error, _ = alerts.send_plain(text, _cfg(), container_name="api")
        db.session.commit()

        assert sent is False
        assert error.startswith("incident #")
        assert len(strategy.sent) == 1
        assert len(strategy.edits) == 1

        incident = Incident.query.one()
        assert incident.container_name == "api"
        assert incident.classification == "critical"
        # the storm signature is container-scoped and text-independent
        assert incident.signature == incident_signature("api", "critical", "restart storm")

        # a storm on another container is its own incident
        alerts.send_plain(text.replace("api", "db"), _cfg(), container_name="db")
        db.session.commit()
        assert Incident.query.count() == 2


def test_alert_service_send_plain_without_container_skips_the_layer(app):
    with app.app_context():
        alerts, strategy = _alert_service(app, with_incidents=True)
        assert alerts.send_plain("hello", _cfg())[0] is True
        assert alerts.send_plain("hello", _cfg())[0] is True
        assert len(strategy.sent) == 2
        assert Incident.query.count() == 0


# ── repository + coordinator wiring ────────────────────────────


def test_repository_open_lookup_and_stale_listing(app):
    with app.app_context():
        repo = IncidentRepository()
        now = utcnow_naive()
        old = Incident(
            signature="s1", container_name="api", classification="critical",
            status="open", first_seen_at=now, last_seen_at=now - timedelta(hours=1),
        )
        fresh = Incident(
            signature="s2", container_name="db", classification="critical",
            status="open", first_seen_at=now, last_seen_at=now,
        )
        closed = Incident(
            signature="s3", container_name="db", classification="critical",
            status="resolved", first_seen_at=now, last_seen_at=now - timedelta(hours=5),
        )
        for row in (old, fresh, closed):
            repo.add(row)
        db.session.commit()

        assert repo.find_open_by_signature("s1").id == old.id
        assert repo.find_open_by_signature("s3") is None, "resolved incidents are not reused"
        assert repo.find_open_by_signature("") is None
        assert repo.get(old.id).id == old.id
        assert {i.id for i in repo.list_open()} == {old.id, fresh.id}
        assert [i.id for i in repo.list_stale_open(now - timedelta(minutes=30))] == [old.id]
        assert [i.id for i in repo.list_for_container("db")] == [fresh.id, closed.id]


def test_container_wires_the_incident_layer(container):
    assert container.incident_service is not None
    assert container.incident_repo is not None
    assert container.alert_service.incident_service is container.incident_service
    assert container.coordinator.incident_service is container.incident_service


def test_coordinator_resolve_job_is_best_effort(app, container):
    """The scheduled job runs in an app context and swallows failures."""
    coordinator = container.coordinator

    class _Boom:
        def resolve_stale(self, now=None):
            raise RuntimeError("telegram exploded")

    coordinator.incident_service = _Boom()
    coordinator._run_resolve_incidents_job()  # must not raise

    coordinator.incident_service = None
    coordinator._run_resolve_incidents_job()  # no-op without a service


def test_incident_settings_defaults_and_api_round_trip(app, client):
    with app.app_context():
        settings = Settings.singleton()
        assert settings.incident_resolve_after_minutes == 30
        assert settings.incident_reminder_hours == 0
        assert settings.incident_notify_on_resolve is True
        assert settings.as_dict()["incident_resolve_after_minutes"] == 30

    body = client.get("/api/settings").get_json()
    assert body["incident_reminder_hours"] == 0
    assert body["incident_notify_on_resolve"] is True

    updated = client.put(
        "/api/settings",
        json={
            "incident_resolve_after_minutes": 90,
            "incident_reminder_hours": 12,
            "incident_notify_on_resolve": False,
        },
    )
    assert updated.status_code == 200
    assert updated.get_json()["incident_resolve_after_minutes"] == 90
    with app.app_context():
        assert Settings.singleton().incident_reminder_hours == 12
        assert Settings.singleton().incident_notify_on_resolve is False

    # bounds are enforced
    assert client.put("/api/settings", json={"incident_resolve_after_minutes": 0}).status_code == 400
    assert client.put("/api/settings", json={"incident_reminder_hours": -1}).status_code == 400


def test_new_incident_message_carries_a_resolve_button(app, container):
    """The operator can close an incident from the notification itself."""
    from app.models import Settings
    from app.extensions import db
    from app.services.incidents import IncidentService
    from app.config_objects import AlertConfig

    class _Strategy:
        def __init__(self):
            self.markups = []

        def send(self, message, config, reply_markup=None):
            self.markups.append(reply_markup)
            return True, None, 42

    with app.app_context():
        strategy = _Strategy()
        svc = IncidentService(repo=container.incident_repo, strategy=strategy)
        cfg = AlertConfig.from_settings(Settings.singleton())
        svc.notify_for(
            "web",
            "critical",
            "upstream refused",
            cfg,
            "🚨 CRITICAL · web",
            reply_markup={"inline_keyboard": [[{"text": "✓ Approve", "callback_data": "approve:1"}]]},
        )
        db.session.commit()

        rows = strategy.markups[0]["inline_keyboard"]
        assert rows[0][0]["callback_data"] == "approve:1"  # existing buttons preserved
        resolve = rows[-1][0]
        assert resolve["text"] == "✅ Resolve"
        incident_id = int(resolve["callback_data"].split(":")[1])
        assert container.incident_repo.get(incident_id) is not None
