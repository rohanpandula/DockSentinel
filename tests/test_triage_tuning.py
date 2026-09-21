"""Triage tuning: analysis cooldown, persistent-warning escalation, confidence gate, settings."""
from __future__ import annotations

import pathlib
from datetime import timedelta

from app.extensions import db
from app.models import AnalysisEvent, Settings
from app.models.local_issue import LocalIssue
from app.services.llm_client import LLMResult
from app.services.sentinel import chunk_similarity, chunk_similarity_tokens
from app.time_utils import utcnow_naive


class _LLM:
    """Scriptable LLM: pops verdicts from ``queue`` (last one repeats); counts calls."""

    def __init__(self, classification="warning", confidence=0.9):
        self.calls = 0
        self.classification = classification
        self.confidence = confidence

    def chat_completion(self, **kwargs):
        self.calls += 1
        return LLMResult(
            content=(
                f'{{"classification":"{self.classification}","summary":"s","root_cause_hypothesis":"r",'
                f'"fix_suggestion":"f","confidence":{self.confidence}}}'
            ),
            model="demo",
            latency_ms=1,
            usage={},
        )


class _Strategy:
    def __init__(self):
        self.sent = []
        self.markups = []

    def send(self, message, config, reply_markup=None):
        self.sent.append(message)
        self.markups.append(reply_markup)
        return True, None, 7


def _prep(container, classification="warning", confidence=0.9, **settings_overrides):
    sentinel = container.sentinel
    llm = _LLM(classification, confidence)
    sentinel.llm_call_service._client = llm
    strategy = _Strategy()
    sentinel.alert_service.strategy = strategy
    sentinel.set_enabled(True)
    settings = Settings.singleton()
    settings.dedup_window_seconds = 0
    settings.chunk_coalesce_window_seconds = 0
    for key, value in settings_overrides.items():
        setattr(settings, key, value)
    db.session.commit()
    return sentinel, llm, strategy


# --- similarity helper ------------------------------------------------------------------


def test_similarity_strips_timestamps_but_keeps_levels():
    tokens = chunk_similarity_tokens(
        "2026-08-15T10:00:00.123Z [WARN] slow query took 3s\n[2026-08-15 10:00:01] retrying\n12:00:01 done"
    )
    assert tokens == {"[WARN]", "slow", "query", "took", "3s", "retrying", "done"}
    a = "2026-08-15T10:00:00Z error: disk 91% full\n2026-08-15T10:00:01Z retrying"
    b = "2026-08-15T10:07:00Z error: disk 91% full\n2026-08-15T10:07:01Z retrying"
    assert chunk_similarity(a, b) == 1.0
    assert chunk_similarity("error a b c d", "error x y z w") < 0.6
    assert chunk_similarity("", "") == 1.0


# --- analysis cooldown --------------------------------------------------------------------


def test_analysis_cooldown_skips_llm_for_similar_warning(app, container):
    with app.app_context():
        sentinel, llm, _ = _prep(container, "warning", analysis_cooldown_minutes=15)
        chunk = "2026-08-15T10:00:00Z error: disk 91% full\n2026-08-15T10:00:01Z retrying"
        first = sentinel.process_chunk(container_id="c1", container_name="api", chunk_text=chunk)
        assert first.status == "analyzed" and first.classification == "warning"

        again = "2026-08-15T10:05:00Z error: disk 91% full\n2026-08-15T10:05:01Z retrying"
        second = sentinel.process_chunk(container_id="c1", container_name="api", chunk_text=again)
        assert second.status == "analysis_cooldown"
        assert second.classification == "warning"
        assert second.summary == f"same as event #{first.id} (cooldown)"
        assert llm.calls == 1

        # A different error for the same container is analyzed normally.
        third = sentinel.process_chunk(container_id="c1", container_name="api", chunk_text="fatal: segfault in worker pid 9")
        assert third.status == "analyzed"
        assert llm.calls == 2

        # Another container is never matched against api's history.
        other = sentinel.process_chunk(container_id="c2", container_name="db", chunk_text=again)
        assert other.status == "analyzed"
        assert llm.calls == 3


def test_analysis_cooldown_never_reuses_critical_and_respects_window_force_and_zero(app, container):
    with app.app_context():
        sentinel, llm, _ = _prep(container, "critical", analysis_cooldown_minutes=15)
        chunk = "error: connection refused to db:5432"
        sentinel.process_chunk(container_id="c1", container_name="api", chunk_text=chunk)
        second = sentinel.process_chunk(container_id="c1", container_name="api", chunk_text=chunk + " again")
        assert second.status == "analyzed"  # critical verdicts always get a fresh look
        assert llm.calls == 2

        # Warning verdict, then: expired window -> re-analysed.
        llm.classification = "warning"
        w1 = sentinel.process_chunk(container_id="c1", container_name="api", chunk_text="error: slow disk io")
        assert w1.status == "analyzed" and w1.classification == "warning"
        w1.created_at = utcnow_naive() - timedelta(minutes=30)
        db.session.commit()
        w2 = sentinel.process_chunk(container_id="c1", container_name="api", chunk_text="error: slow disk io")
        assert w2.status == "analyzed"

        # force=True (Analyze now) is never short-circuited.
        forced = sentinel.process_chunk(
            container_id="c1", container_name="api", chunk_text="error: slow disk io", coalesce=False, force=True
        )
        assert forced.status == "analyzed"

        # analysis_cooldown_minutes=0 disables the feature.
        Settings.singleton().analysis_cooldown_minutes = 0
        db.session.commit()
        w3 = sentinel.process_chunk(container_id="c1", container_name="api", chunk_text="error: slow disk io")
        assert w3.status == "analyzed"


def test_analysis_cooldown_status_is_skipped_for_dashboard_and_prunable(app, container, client):
    from app.web.routes import EVENT_STATUSES

    assert "analysis_cooldown" in EVENT_STATUSES
    with app.app_context():
        repo = container.event_repo
        assert "analysis_cooldown" in repo.PRUNABLE_STATUSES
        db.session.add(
            AnalysisEvent(
                container_id="c1",
                container_name="api",
                status="analysis_cooldown",
                classification="warning",
                created_at=utcnow_naive() - timedelta(days=30),
            )
        )
        db.session.add(AnalysisEvent(container_id="c1", container_name="api", status="analysis_cooldown", classification="warning"))
        db.session.commit()
        assert repo.prune(utcnow_naive() - timedelta(days=14)) == 1
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    resp = client.get("/insights?status=analysis_cooldown")
    assert resp.status_code == 200


# --- persistent warning escalation ----------------------------------------------------


def test_persistent_warnings_escalate_once_with_header_and_keyboard(app, container):
    with app.app_context():
        sentinel, llm, strategy = _prep(
            container,
            "warning",
            persistent_warning_count=3,
            persistent_warning_window_minutes=60,
            alert_cooldown_minutes=10,
            analysis_cooldown_minutes=15,
        )
        e1 = sentinel.process_chunk(container_id="c1", container_name="api", chunk_text="error: slow disk io on /data")
        e2 = sentinel.process_chunk(container_id="c1", container_name="api", chunk_text="error: retry budget exhausted")
        assert e1.status == "analyzed" and e2.status == "analyzed"
        assert strategy.sent == []
        assert not e1.alert_sent and not e2.alert_sent

        # Third warning arrives as an analysis_cooldown repeat of e2 -> still counts.
        e3 = sentinel.process_chunk(container_id="c1", container_name="api", chunk_text="error: retry budget exhausted")
        assert e3.status == "analysis_cooldown" and e3.classification == "warning"
        assert e3.alert_sent is True
        assert len(strategy.sent) == 1
        msg = strategy.sent[0]
        assert msg.startswith("⚠️ PERSISTENT WARNING · api · 3 in 60 min\n")
        assert "🚨 WARNING · api" in msg
        assert f"Event ID: {e3.id}" in msg
        assert strategy.markups[0]["inline_keyboard"][0][0]["callback_data"] == f"reject:{e3.id}"

        # Fourth warning inside the alert cooldown: suppressed.
        e4 = sentinel.process_chunk(container_id="c1", container_name="api", chunk_text="error: queue depth 900")
        assert e4.status == "analyzed"
        assert e4.alert_sent is not True
        assert e4.alert_error == "persistent warning alert suppressed by cooldown"
        assert len(strategy.sent) == 1

        # Another container's warnings are counted separately.
        for text in ("error: a b", "error: c d"):
            other = sentinel.process_chunk(container_id="c2", container_name="db", chunk_text=text)
        assert other.alert_sent is not True
        assert len(strategy.sent) == 1


def test_persistent_warning_disabled_and_window_and_rejected(app, container):
    with app.app_context():
        sentinel, llm, strategy = _prep(container, "warning", persistent_warning_count=0)
        for text in ("error: a b", "error: c d", "error: e f", "error: g h"):
            sentinel.process_chunk(container_id="c1", container_name="api", chunk_text=text)
        assert strategy.sent == []

        settings = Settings.singleton()
        settings.persistent_warning_count = 2
        settings.persistent_warning_window_minutes = 30
        db.session.commit()
        # Age everything past the window: the next warning counts as 1 -> no alert.
        for e in AnalysisEvent.query.all():
            e.created_at = utcnow_naive() - timedelta(minutes=45)
        db.session.commit()
        e = sentinel.process_chunk(container_id="c1", container_name="api", chunk_text="error: i j")
        assert e.alert_sent is not True and strategy.sent == []

        # Now at threshold, but a recently rejected issue suppresses the escalation.
        db.session.add(LocalIssue(container_name="api", title="t", body="b", status="rejected", action="reject"))
        db.session.commit()
        e = sentinel.process_chunk(container_id="c1", container_name="api", chunk_text="error: k l")
        assert e.alert_sent is False
        assert e.alert_error == "suppressed: recently rejected"
        assert strategy.sent == []


def test_escalation_respects_global_rate_limit(app, container):
    with app.app_context():
        sentinel, llm, strategy = _prep(
            container, "warning", persistent_warning_count=1, alert_rate_limit_count=1, alert_rate_limit_window_seconds=300
        )
        db.session.add(AnalysisEvent(container_id="x", container_name="x", status="analyzed", alert_sent=True))
        db.session.commit()
        e = sentinel.process_chunk(container_id="c1", container_name="api", chunk_text="error: k l")
        assert e.alert_sent is False
        assert e.alert_error == "global rate limit exceeded"
        assert strategy.sent == []


def test_repo_count_warnings_and_last_analyzed(app, container):
    with app.app_context():
        repo = container.event_repo
        now = utcnow_naive()
        rows = [
            AnalysisEvent(container_id="c1", container_name="api", status="analyzed", classification="warning"),
            AnalysisEvent(container_id="c1", container_name="api", status="analysis_cooldown", classification="warning"),
            AnalysisEvent(container_id="c1", container_name="api", status="analyzed", classification="critical"),
            AnalysisEvent(container_id="c1", container_name="api", status="skipped", classification="warning"),
            AnalysisEvent(container_id="c9", container_name="db", status="analyzed", classification="warning"),
            AnalysisEvent(
                container_id="c1", container_name="api", status="analyzed", classification="warning",
                created_at=now - timedelta(hours=3),
            ),
        ]
        db.session.add_all(rows)
        db.session.commit()
        since = now - timedelta(hours=1)
        assert repo.count_warnings("api", since) == 2
        assert repo.count_warnings("db", since) == 1
        last = repo.find_last_analyzed("c1", since)
        assert last is not None and last.classification == "critical"
        assert repo.find_last_analyzed("nope", since) is None
        assert repo.find_recent_alert_for_name("api", since) is None
        rows[0].alert_sent = True
        db.session.commit()
        assert repo.find_recent_alert_for_name("api", since) is rows[0]


# --- confidence gate ------------------------------------------------------------------------


def test_low_confidence_suppresses_alert(app, container):
    with app.app_context():
        sentinel, llm, strategy = _prep(container, "critical", confidence=0.42, alert_min_confidence=0.6)
        e = sentinel.process_chunk(container_id="c1", container_name="api", chunk_text="fatal: down")
        assert e.status == "analyzed" and e.classification == "critical"
        assert e.alert_sent is False
        assert e.alert_error == "suppressed: confidence 0.42 < 0.60"
        assert strategy.sent == []

        llm.confidence = 0.75
        e2 = sentinel.process_chunk(container_id="c1", container_name="api", chunk_text="fatal: down again now")
        assert e2.alert_sent is True
        assert len(strategy.sent) == 1


def test_confidence_gate_off_by_default_and_gates_escalation(app, container):
    with app.app_context():
        assert Settings.singleton().alert_min_confidence == 0.0
        sentinel, llm, strategy = _prep(container, "critical", confidence=0.05)
        e = sentinel.process_chunk(container_id="c1", container_name="api", chunk_text="fatal: down")
        assert e.alert_sent is True

        # Escalation path honours the same floor.
        settings = Settings.singleton()
        settings.alert_min_confidence = 0.5
        settings.persistent_warning_count = 1
        settings.alert_cooldown_minutes = 0
        db.session.commit()
        llm.classification = "warning"
        llm.confidence = 0.3
        w = sentinel.process_chunk(container_id="c1", container_name="api", chunk_text="error: slow thing")
        assert w.classification == "warning"
        assert w.alert_sent is False
        assert w.alert_error == "suppressed: confidence 0.30 < 0.50"
        assert len(strategy.sent) == 1


# --- settings plumbing / migration ---------------------------------------------------------


def test_triage_settings_defaults_api_and_validation(app, client):
    with app.app_context():
        s = Settings.singleton()
        assert (s.analysis_cooldown_minutes, s.persistent_warning_count, s.persistent_warning_window_minutes) == (15, 3, 60)
        assert s.alert_min_confidence == 0.0
        d = s.as_dict()
        for key in ("analysis_cooldown_minutes", "persistent_warning_count", "persistent_warning_window_minutes", "alert_min_confidence"):
            assert key in d
    body = client.get("/api/settings").get_json()
    assert body["analysis_cooldown_minutes"] == 15
    assert body["persistent_warning_count"] == 3
    assert body["persistent_warning_window_minutes"] == 60
    assert body["alert_min_confidence"] == 0.0

    resp = client.put(
        "/api/settings",
        json={
            "analysis_cooldown_minutes": 0,
            "persistent_warning_count": 0,
            "persistent_warning_window_minutes": 5,
            "alert_min_confidence": 0.65,
        },
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    with app.app_context():
        s = Settings.singleton()
        assert (s.analysis_cooldown_minutes, s.persistent_warning_count, s.persistent_warning_window_minutes) == (0, 0, 5)
        assert abs(s.alert_min_confidence - 0.65) < 1e-9

    for bad in (
        {"analysis_cooldown_minutes": -1},
        {"persistent_warning_count": -1},
        {"persistent_warning_window_minutes": 0},
        {"alert_min_confidence": 1.5},
        {"alert_min_confidence": -0.1},
    ):
        assert client.put("/api/settings", json=bad).status_code == 400, bad


def test_migration_0010_ids():
    path = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "versions" / "0010_triage_tuning.py"
    text = path.read_text()
    assert "revision: str = 'e5f6a7b8c9d0'" in text
    assert "down_revision: str = 'd4e5f6a7b8c9'" in text
    assert 'batch_alter_table("settings")' in text
    for col in ("analysis_cooldown_minutes", "persistent_warning_count", "persistent_warning_window_minutes", "alert_min_confidence"):
        assert col in text


def _warning_event(container_name, created_at, alert_sent=False, status="analyzed"):
    from app.models import AnalysisEvent

    return AnalysisEvent(
        container_id="c1",
        container_name=container_name,
        status=status,
        classification="warning",
        summary="still failing",
        confidence=0.7,
        alert_sent=alert_sent,
        created_at=created_at,
    )


def test_escalation_is_edge_triggered_not_repeating(app, container):
    """A container that stays broken must produce ONE escalation, not one per cooldown.

    Regression: escalation only checked alert_cooldown_minutes, so a
    permanently-true condition re-alerted every cooldown interval forever
    (observed live: 5 identical alerts for one container in 47 minutes).
    """
    from datetime import timedelta

    from app.extensions import db
    from app.models import Settings
    from app.time_utils import utcnow_naive

    sent = []

    class _Strategy:
        def send(self, message, config, reply_markup=None):
            sent.append(message)
            return True, None, 1

    with app.app_context():
        s = Settings.singleton()
        s.persistent_warning_count = 3
        s.persistent_warning_window_minutes = 60
        s.alert_cooldown_minutes = 10
        db.session.commit()

        svc = container.sentinel
        svc.alert_service.strategy = _Strategy()
        now = utcnow_naive()

        # An escalation alert 30 minutes ago: the 10-minute cooldown has long
        # lapsed, but warnings never stopped, so this is still one incident.
        db.session.add(_warning_event("ddns", now - timedelta(minutes=30), alert_sent=True))
        for minutes_ago in (25, 20, 15, 5):
            db.session.add(_warning_event("ddns", now - timedelta(minutes=minutes_ago)))
        db.session.commit()

        ev = _warning_event("ddns", now)
        db.session.add(ev)
        db.session.flush()
        svc._maybe_escalate_warning(ev, s)
        db.session.commit()

        assert ev.alert_sent is not True
        assert ev.alert_error == "persistent warning: same episode as the last alert"
        assert sent == []


def test_escalation_rearms_after_a_quiet_window(app, container):
    """Once the container goes quiet for a full window, a new episode may alert again."""
    from datetime import timedelta

    from app.extensions import db
    from app.models import Settings
    from app.time_utils import utcnow_naive

    sent = []

    class _Strategy:
        def send(self, message, config, reply_markup=None):
            sent.append(message)
            return True, None, 1

    with app.app_context():
        s = Settings.singleton()
        s.persistent_warning_count = 3
        s.persistent_warning_window_minutes = 60
        s.alert_cooldown_minutes = 10
        db.session.commit()

        svc = container.sentinel
        svc.alert_service.strategy = _Strategy()
        now = utcnow_naive()

        # An alert two hours ago, then nothing until now: the episode ended.
        db.session.add(_warning_event("ddns", now - timedelta(minutes=120), alert_sent=True))
        for minutes_ago in (20, 15, 10):
            db.session.add(_warning_event("ddns", now - timedelta(minutes=minutes_ago)))
        db.session.commit()

        ev = _warning_event("ddns", now)
        db.session.add(ev)
        db.session.flush()
        svc._maybe_escalate_warning(ev, s)
        db.session.commit()
        assert ev.alert_sent is True
        assert len(sent) == 1
