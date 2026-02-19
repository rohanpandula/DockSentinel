from __future__ import annotations

from flask import Flask

from app.services.coordinator import RuntimeCoordinator


class _DummySentinel:
    def handle_log_line(self, container_id, container_name, line, flush_only=False):
        return None

    def is_excluded_container(self, container_name):
        return False


class _DummyBriefing:
    def generate_report(self):
        return None


class _FakeThread:
    def __init__(self, alive: bool):
        self.alive = alive

    def is_alive(self) -> bool:
        return self.alive


class _FakeWatcher:
    def __init__(self):
        self.stop_calls = 0
        self.start_calls = 0
        self.reconcile_calls = 0
        self._event_thread = _FakeThread(alive=False)
        self._reconcile_thread = _FakeThread(alive=True)

    def stop(self):
        self.stop_calls += 1

    def start(self):
        self.start_calls += 1
        self._event_thread = _FakeThread(alive=True)
        self._reconcile_thread = _FakeThread(alive=True)

    def force_reconcile(self):
        self.reconcile_calls += 1


def test_runtime_lock_single_owner(tmp_path):
    app = Flask(__name__)
    app.config["TESTING"] = False
    app.config["RUNTIME_LOCK_PATH"] = str(tmp_path / "runtime.lock")
    app.debug = False

    c1 = RuntimeCoordinator(app, _DummySentinel(), _DummyBriefing())
    c2 = RuntimeCoordinator(app, _DummySentinel(), _DummyBriefing())

    assert c1._acquire_lock() is True
    assert c2._acquire_lock() is False

    c1._release_lock()
    assert c2._acquire_lock() is True
    c2._release_lock()


def test_runtime_health_check_restarts_dead_watcher_thread(tmp_path):
    app = Flask(__name__)
    app.config["TESTING"] = False
    app.config["RUNTIME_LOCK_PATH"] = str(tmp_path / "runtime.lock")
    app.debug = False

    coordinator = RuntimeCoordinator(app, _DummySentinel(), _DummyBriefing())
    fake_watcher = _FakeWatcher()
    coordinator._watcher = fake_watcher

    restarted = coordinator._check_watcher_health_once()

    assert restarted is True
    assert fake_watcher.stop_calls == 1
    assert fake_watcher.start_calls == 1
    assert fake_watcher.reconcile_calls == 1
    assert fake_watcher._event_thread.is_alive() is True
