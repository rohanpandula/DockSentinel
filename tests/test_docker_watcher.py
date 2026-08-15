"""DockerWatcher: a tail thread whose stream dies must deregister itself so
reconcile re-attaches, and a failing line callback must not kill the stream."""
from __future__ import annotations

import threading
import time

from app.services.docker_watcher import DockerWatcher


class _FakeContainer:
    def __init__(self, cid: str, name: str, payloads, fail_after: int | None = None, status: str = "running"):
        self.id = cid
        self.name = name
        self.status = status
        self._payloads = payloads
        self._fail_after = fail_after
        self.log_calls = 0

    def logs(self, **kwargs):
        self.log_calls += 1
        fail_after = self._fail_after
        payloads = self._payloads

        def _gen():
            for i, p in enumerate(payloads):
                if fail_after is not None and i >= fail_after:
                    raise ConnectionError("read timed out")
                yield p

        return _gen()


class _Containers:
    def __init__(self, container):
        self._c = container

    def get(self, cid):
        return self._c

    def list(self):
        return [self._c]


class _Client:
    def __init__(self, container):
        self.containers = _Containers(container)

    def close(self):
        pass


def _run_tail(watcher: DockerWatcher, container: _FakeContainer) -> None:
    stop_flag = threading.Event()
    thread = threading.Thread(target=watcher._tail_container, args=(container.id, container.name, stop_flag))
    with watcher._lock:
        watcher._workers[container.id] = (container.name, thread, stop_flag)
    thread.start()
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_dropped_stream_reconnects_then_deregisters_when_container_exits():
    lines = []
    container = _FakeContainer("c1", "web", [b"a\n", b"b\n"], fail_after=1)
    # Make the container "stop" after the first reconnect so the loop exits.
    calls = {"n": 0}
    orig_logs = container.logs

    def logs(**kw):
        calls["n"] += 1
        if calls["n"] >= 2:
            container.status = "exited"
        return orig_logs(**kw)

    container.logs = logs

    watcher = DockerWatcher(lambda cid, name, line, flush: lines.append((line, flush)), lambda n: False)
    watcher._client = _Client(container)
    _run_tail(watcher, container)

    assert "c1" not in watcher.active_container_ids()
    assert calls["n"] == 2  # reconnected once after the drop
    assert ("a", False) in lines
    assert lines[-1] == ("", True)  # final flush


def test_unexpected_exception_deregisters_and_requests_reconcile():
    watcher = DockerWatcher(lambda *a: None, lambda n: False)

    class _C:
        def get(self, cid):
            raise RuntimeError("daemon gone")

    client = _Client(_FakeContainer("c9", "x", []))
    client.containers = _C()
    watcher._client = client
    stop_flag = threading.Event()
    with watcher._lock:
        watcher._workers["c9"] = ("x", threading.current_thread(), stop_flag)
    watcher._tail_container("c9", "x", stop_flag)
    assert "c9" not in watcher.active_container_ids()
    assert watcher._reconcile_now.is_set()


def test_line_callback_exception_does_not_kill_stream():
    seen = []

    def cb(cid, name, line, flush):
        if line == "boom":
            raise RuntimeError("db locked")
        seen.append(line)

    container = _FakeContainer("c2", "api", [b"one\n", b"boom\n", b"two\n"])
    watcher = DockerWatcher(cb, lambda n: False)
    watcher._client = _Client(container)
    _run_tail(watcher, container)

    assert seen[:2] == ["one", "two"]  # 'boom' skipped, stream continued
    assert container.log_calls == 1


def test_stop_flag_ends_tail_promptly():
    container = _FakeContainer("c3", "db", [b"x\n"] * 1000)
    watcher = DockerWatcher(lambda *a: time.sleep(0.001), lambda n: False)
    watcher._client = _Client(container)
    stop_flag = threading.Event()
    thread = threading.Thread(target=watcher._tail_container, args=("c3", "db", stop_flag))
    thread.start()
    time.sleep(0.05)
    stop_flag.set()
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert not watcher._reconcile_now.is_set()  # deliberate stop → no re-attach request


def test_stop_joins_threads_and_start_uses_fresh_events(monkeypatch):
    import app.services.docker_watcher as dw

    container = _FakeContainer("c4", "svc", [], status="exited")

    class _EventClient(_Client):
        def __init__(self, c):
            super().__init__(c)
            self.closed = False

        def events(self, decode=True):
            # Block until the watcher is stopped, like a real event stream.
            while not watcher._stop_event.is_set():
                time.sleep(0.01)
            return iter(())

        def close(self):
            self.closed = True

    clients = []

    def _from_env():
        c = _EventClient(container)
        clients.append(c)
        return c

    monkeypatch.setattr(dw.docker, "from_env", _from_env)

    watcher = DockerWatcher(lambda *a: None, lambda n: False, reconcile_interval_seconds=3600)
    watcher.start()
    gen1_stop, gen1_now = watcher._stop_event, watcher._reconcile_now
    gen1_event, gen1_reconcile = watcher._event_thread, watcher._reconcile_thread
    assert gen1_event.is_alive() and gen1_reconcile.is_alive()

    watcher.stop()
    assert not gen1_event.is_alive()
    assert not gen1_reconcile.is_alive()  # joined, not leaked
    assert clients[0].closed
    assert watcher._event_thread is None and watcher._reconcile_thread is None

    watcher.start()
    assert watcher._stop_event is not gen1_stop
    assert watcher._reconcile_now is not gen1_now
    assert not watcher._stop_event.is_set()
    assert gen1_stop.is_set()  # old generation stays stopped
    assert watcher._reconcile_thread.is_alive()
    watcher.stop()
    assert not any(t.is_alive() for t in threading.enumerate() if t.name in {"docker-events", "docker-reconcile"})
