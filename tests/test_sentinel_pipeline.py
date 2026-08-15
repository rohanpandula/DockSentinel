from __future__ import annotations

import hashlib

from app import create_app
from app.extensions import db
from app.models import AnalysisEvent, ExclusionRule, Settings
from app.services.llm_client import LLMResult
from app.time_utils import utcnow_naive


class DummyLLM:
    def chat_completion(self, **kwargs):
        return LLMResult(
            content='{"classification":"critical","summary":"db down","root_cause_hypothesis":"connection refused","fix_suggestion":"restart db","confidence":0.93}',
            model="demo",
            latency_ms=12,
            usage={},
        )


class DummyTelegram:
    def send_message(self, token, chat_id, text, reply_markup=None, reply_to_message_id=None, parse_mode=None):
        return True, None, 42


class _FakeAlertStrategy:
    def send(self, message, config, reply_markup=None):
        return True, None, 42



def _build_app(tmp_path, monkeypatch):
    monkeypatch.setenv("TESTING", "true")
    monkeypatch.setenv("START_COORDINATOR", "false")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'sentinel.db'}")
    monkeypatch.setenv("RUNTIME_LOCK_PATH", str(tmp_path / "runtime.lock"))
    return create_app()


def test_sentinel_critical_pipeline(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)

    with app.app_context():
        sentinel = app.extensions["services"].sentinel
        sentinel.llm_call_service._client = DummyLLM()
        sentinel.alert_service.strategy = _FakeAlertStrategy()
        sentinel.set_enabled(True)

        event = sentinel.process_chunk(
            container_id="abc123",
            container_name="postgres",
            chunk_text="fatal error: connection refused",
        )

        assert event.status == "analyzed"
        assert event.classification == "critical"
        assert event.alert_sent is True

        persisted = db.session.get(AnalysisEvent, event.id)
        assert persisted is not None
        assert persisted.summary == "db down"


def test_sentinel_rate_limit_suppresses_alert(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)

    with app.app_context():
        sentinel = app.extensions["services"].sentinel
        sentinel.llm_call_service._client = DummyLLM()
        sentinel.alert_service.strategy = _FakeAlertStrategy()
        sentinel.set_enabled(True)

        settings = Settings.singleton()
        settings.alert_rate_limit_count = 1
        settings.alert_rate_limit_window_seconds = 300
        db.session.commit()

        db.session.add(
            AnalysisEvent(
                container_id="old",
                container_name="worker",
                status="analyzed",
                classification="critical",
                chunk_hash=hashlib.sha256(b"other-chunk").hexdigest(),
                alert_sent=True,
                created_at=utcnow_naive(),
            )
        )
        db.session.commit()

        event = sentinel.process_chunk(
            container_id="new",
            container_name="postgres",
            chunk_text="fatal error: connection refused",
        )

        assert event.classification == "critical"
        assert event.alert_sent is False
        assert event.alert_error == "global rate limit exceeded"


def test_sentinel_records_excluded_events_with_rate_limit(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)

    with app.app_context():
        sentinel = app.extensions["services"].sentinel
        sentinel.set_enabled(True)

        db.session.add(ExclusionRule(container_pattern="excluded-service", enabled=True))
        db.session.commit()

        sentinel.handle_log_line(container_id="ex1", container_name="excluded-service", line="error happened")
        sentinel.handle_log_line(container_id="ex1", container_name="excluded-service", line="another error")

        excluded_events = (
            AnalysisEvent.query.filter(
                AnalysisEvent.container_id == "ex1",
                AnalysisEvent.status == "excluded",
            )
            .order_by(AnalysisEvent.created_at.asc())
            .all()
        )

        assert len(excluded_events) == 1
        assert excluded_events[0].classification is None


def test_sentinel_cooldown_suppresses_duplicate_alert(tmp_path, monkeypatch):
    app = _build_app(tmp_path, monkeypatch)

    with app.app_context():
        sentinel = app.extensions["services"].sentinel
        sentinel.llm_call_service._client = DummyLLM()
        sentinel.alert_service.strategy = _FakeAlertStrategy()
        sentinel.set_enabled(True)

        # Disable chunk dedup so both calls reach the LLM and test alert cooldown.
        settings = Settings.singleton()
        settings.dedup_window_seconds = 0
        db.session.commit()

        first = sentinel.process_chunk(
            container_id="abc123",
            container_name="postgres",
            chunk_text="fatal error: connection refused",
        )
        second = sentinel.process_chunk(
            container_id="abc123",
            container_name="postgres",
            chunk_text="fatal error: connection refused",
        )

        assert first.alert_sent is True
        assert second.alert_sent is False
        assert second.alert_error == "duplicate alert suppressed by cooldown"


def test_sentinel_dedup_skips_duplicate_chunk(tmp_path, monkeypatch):
    """Same chunk_hash within dedup window should be skipped."""
    app = _build_app(tmp_path, monkeypatch)

    with app.app_context():
        sentinel = app.extensions["services"].sentinel
        sentinel.llm_call_service._client = DummyLLM()
        sentinel.alert_service.strategy = _FakeAlertStrategy()
        sentinel.set_enabled(True)

        settings = Settings.singleton()
        settings.dedup_window_seconds = 300
        db.session.commit()

        first = sentinel.process_chunk(
            container_id="abc123",
            container_name="postgres",
            chunk_text="fatal error: connection refused",
        )
        assert first.status == "analyzed"

        second = sentinel.process_chunk(
            container_id="abc123",
            container_name="postgres",
            chunk_text="fatal error: connection refused",
        )
        assert second.status == "dedup_skipped"


def test_sentinel_per_container_rate_limit(tmp_path, monkeypatch):
    """Per-container rate limit should cap LLM calls."""
    app = _build_app(tmp_path, monkeypatch)

    with app.app_context():
        sentinel = app.extensions["services"].sentinel
        sentinel.llm_call_service._client = DummyLLM()
        sentinel.alert_service.strategy = _FakeAlertStrategy()
        sentinel.set_enabled(True)

        settings = Settings.singleton()
        settings.container_rate_limit_count = 1
        settings.container_rate_limit_window_seconds = 3600
        settings.dedup_window_seconds = 0  # Disable dedup to test rate limit alone
        db.session.commit()

        first = sentinel.process_chunk(
            container_id="abc123",
            container_name="postgres",
            chunk_text="fatal error: connection refused",
        )
        assert first.status == "analyzed"

        second = sentinel.process_chunk(
            container_id="abc123",
            container_name="postgres",
            chunk_text="fatal error: a different error entirely",
        )
        assert second.status == "rate_limited"


def test_coalescer_flushes_by_max_age_even_under_constant_arrivals(app):
    """A container logging a matching line more often than the window must still be analysed."""
    import time
    from app.services.chunk_coalescer import ChunkCoalescer

    flushed = []
    c = ChunkCoalescer(app, lambda cid, name, chunks: flushed.append((cid, list(chunks))))
    for i in range(6):
        c.enqueue(container_id="c", container_name="c", chunk_text=f"error {i}", window_seconds=1)
        time.sleep(0.25)  # arrivals every 250ms < 1s window: old debounce never fired
    time.sleep(0.6)
    assert flushed and flushed[0][0] == "c"
    assert len(flushed[0][1]) >= 4  # first batch carries the chunks that arrived during the window
