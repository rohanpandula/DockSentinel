"""Idle flush: an error followed by silence must reach process_chunk without
waiting for the next log line (REVIEW item 12)."""
from __future__ import annotations

from datetime import timedelta

from app.extensions import db
from app.models import SentinelState, Settings
from app.services.coordinator import RuntimeCoordinator
from app.time_utils import utcnow_naive


def test_flush_idle_buffers_processes_stale_primed_chunk(app, container, monkeypatch):
    with app.app_context():
        state = SentinelState.singleton()
        state.enabled = True
        s = Settings.singleton()
        s.keyword_list = "error"
        s.keyword_flush_delay_lines = 5
        db.session.commit()

        sentinel = container.sentinel
        processed = []
        monkeypatch.setattr(
            sentinel,
            "process_chunk",
            lambda **kw: processed.append(kw) or None,
        )

        sentinel.handle_log_line("cid-1", "web", "an error happened")
        assert processed == []  # waiting for 5 more lines
        buf_state = sentinel.log_buffer._buffers["cid-1"]
        assert buf_state.container_name == "web"

        assert sentinel.flush_idle_buffers() == 0  # not idle yet
        buf_state.last_activity = utcnow_naive() - timedelta(seconds=sentinel.log_buffer.flush_window_seconds + 1)
        assert sentinel.flush_idle_buffers() == 1
        assert processed[0]["container_id"] == "cid-1"
        assert processed[0]["container_name"] == "web"
        assert "an error happened" in processed[0]["chunk_text"]
        assert "cid-1" not in sentinel.log_buffer._buffers


def test_flush_idle_buffers_noop_when_disabled(app, container):
    with app.app_context():
        state = SentinelState.singleton()
        state.enabled = False
        db.session.commit()
        container.sentinel.log_buffer.add_line("x", "an error", keyword_hit=True, container_name="w")
        assert container.sentinel.flush_idle_buffers() == 0


def test_coordinator_health_tick_calls_idle_flush(app):
    calls = []

    class _Sentinel:
        def flush_idle_buffers(self):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("db locked")  # must be swallowed + logged
            return 0

    coord = RuntimeCoordinator(app, _Sentinel(), briefing_service=None)
    coord._flush_idle_buffers_once()
    coord._flush_idle_buffers_once()
    assert calls == [1, 1]
