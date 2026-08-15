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


def test_dead_stream_deregisters_worker_and_requests_reconcile():
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
    assert watcher._reconcile_now.is_set()
    assert ("a", False) in lines
    assert lines[-1] == ("", True)  # final flush


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
