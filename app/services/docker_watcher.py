from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

import docker


LOGGER = logging.getLogger(__name__)

LineCallback = Callable[[str, str, str, bool], None]
ExcludeCallback = Callable[[str], bool]


class DockerWatcher:
    def __init__(
        self,
        line_callback: LineCallback,
        is_excluded_callback: ExcludeCallback,
        reconcile_interval_seconds: int = 60,
    ) -> None:
        self.line_callback = line_callback
        self.is_excluded_callback = is_excluded_callback
        self.reconcile_interval_seconds = reconcile_interval_seconds

        self._client: docker.DockerClient | None = None
        self._workers: dict[str, tuple[str, threading.Thread, threading.Event]] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._reconcile_now = threading.Event()

        self._event_thread: threading.Thread | None = None
        self._reconcile_thread: threading.Thread | None = None

    def start(self) -> None:
        self._client = docker.from_env()
        self._stop_event.clear()

        self._event_thread = threading.Thread(target=self._watch_events, name="docker-events", daemon=True)
        self._reconcile_thread = threading.Thread(target=self._reconcile_loop, name="docker-reconcile", daemon=True)
        self._event_thread.start()
        self._reconcile_thread.start()
        self.reconcile()

    def stop(self) -> None:
        self._stop_event.set()

        with self._lock:
            for container_id, (_, thread, stop_flag) in list(self._workers.items()):
                stop_flag.set()
                thread.join(timeout=1)
                self._workers.pop(container_id, None)

        if self._client is not None:
            self._client.close()
            self._client = None

    def active_container_ids(self) -> list[str]:
        with self._lock:
            return list(self._workers.keys())

    def force_reconcile(self) -> None:
        self._reconcile_now.set()

    def _watch_events(self) -> None:
        if self._client is None:
            return
        try:
            for event in self._client.events(decode=True):
                if self._stop_event.is_set():
                    break
                if event.get("Type") != "container":
                    continue
                status = event.get("status")
                actor = event.get("Actor", {}).get("Attributes", {})
                container_id = event.get("id")
                container_name = actor.get("name")
                if not container_id:
                    continue
                if status in {"start", "restart"}:
                    self._attach_container(container_id)
                # `stop` is handled in addition to die/destroy to detach workers sooner.
                elif status in {"die", "destroy", "stop"}:
                    self._detach_container(container_id, container_name)
        except Exception:
            # Reconciliation loop keeps state accurate even if event stream fails.
            LOGGER.exception("docker event stream ended with error; relying on periodic reconcile")
            return

    def _reconcile_loop(self) -> None:
        while not self._stop_event.is_set():
            triggered = self._reconcile_now.wait(timeout=self.reconcile_interval_seconds)
            if self._stop_event.is_set():
                break
            if triggered:
                self._reconcile_now.clear()
            self.reconcile()

    def reconcile(self) -> None:
        if self._client is None:
            return

        running = self._client.containers.list()
        desired_set: dict[str, str] = {}
        for container in running:
            if self.is_excluded_callback(container.name):
                continue
            desired_set[container.id] = container.name

        with self._lock:
            active_set = set(self._workers.keys())

        desired_ids = set(desired_set.keys())

        for container_id in desired_ids - active_set:
            self._attach_container(container_id)

        for container_id in active_set - desired_ids:
            self._detach_container(container_id, None)

    def _attach_container(self, container_id: str) -> None:
        if self._client is None:
            return

        with self._lock:
            if container_id in self._workers:
                return

        try:
            container = self._client.containers.get(container_id)
        except Exception:
            return

        if self.is_excluded_callback(container.name):
            return

        stop_flag = threading.Event()
        thread = threading.Thread(
            target=self._tail_container,
            args=(container.id, container.name, stop_flag),
            name=f"log-tail-{container.name}",
            daemon=True,
        )

        with self._lock:
            if container.id in self._workers:
                return
            self._workers[container.id] = (container.name, thread, stop_flag)

        thread.start()

    def _detach_container(self, container_id: str, container_name: str | None) -> None:
        with self._lock:
            worker = self._workers.pop(container_id, None)

        if not worker:
            return

        name, thread, stop_flag = worker
        stop_flag.set()
        thread.join(timeout=1)
        self.line_callback(container_id, container_name or name, "", True)

    def _tail_container(self, container_id: str, container_name: str, stop_flag: threading.Event) -> None:
        """Follow one container's log stream until it stops or the watcher stops.

        Any failure of the stream itself is logged and the worker entry is
        removed so the next reconcile re-attaches (previously the dead worker
        stayed registered and the container went silently unmonitored).
        Failures inside the line callback (DB busy, LLM error) are logged and
        skipped rather than allowed to kill the stream.
        """
        if self._client is None:
            return
        try:
            since = int(time.time())
            backoff = 1.0
            while not (self._stop_event.is_set() or stop_flag.is_set()):
                container = self._client.containers.get(container_id)
                if container.status not in {"running", "restarting"}:
                    break
                try:
                    stream = container.logs(stream=True, follow=True, stdout=True, stderr=True, since=since)
                    for payload in stream:
                        if self._stop_event.is_set() or stop_flag.is_set():
                            break
                        since = int(time.time())
                        backoff = 1.0
                        line = payload.decode("utf-8", errors="replace").rstrip("\n")
                        if not line:
                            continue
                        try:
                            self.line_callback(container_id, container_name, line, False)
                        except Exception:
                            LOGGER.exception("log line handler failed for container %s", container_name)
                    # Stream closed cleanly (container stopped) or we were told to stop.
                    break
                except Exception:
                    # Typical cause: docker-py's per-read timeout on a quiet container.
                    # Reconnect from where we left off instead of dropping the container.
                    LOGGER.debug("log stream for %s dropped; reconnecting in %.0fs", container_name, backoff, exc_info=True)
                    if stop_flag.wait(backoff):
                        break
                    backoff = min(backoff * 2, 30.0)
        except Exception:
            LOGGER.exception("log stream for container %s ended with error", container_name)
        finally:
            with self._lock:
                worker = self._workers.get(container_id)
                if worker is not None and worker[2] is stop_flag:
                    self._workers.pop(container_id, None)
            try:
                self.line_callback(container_id, container_name, "", True)
            except Exception:
                LOGGER.exception("final flush failed for container %s", container_name)
            if not self._stop_event.is_set() and not stop_flag.is_set():
                # Stream ended on its own (daemon hiccup, read timeout): ask the
                # reconcile loop to re-attach promptly instead of waiting a full interval.
                self._reconcile_now.set()
