from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

from flask import Flask

logger = logging.getLogger(__name__)


@dataclass
class _Pending:
    container_id: str
    container_name: str
    chunks: list[str] = field(default_factory=list)
    timer: Optional[threading.Timer] = None


FlushCallback = Callable[[str, str, list[str]], None]


class ChunkCoalescer:
    """Holds keyword-matched chunks per container in a sliding window.

    Each new chunk for a container resets the window timer. When the timer
    fires without new arrivals, all accumulated chunks are flushed to the
    callback in a single batch. The callback runs inside a Flask app context.
    """

    def __init__(self, app: Flask, on_flush: FlushCallback) -> None:
        self._app = app
        self._on_flush = on_flush
        self._lock = threading.Lock()
        self._pending: dict[str, _Pending] = {}

    def enqueue(
        self,
        *,
        container_id: str,
        container_name: str,
        chunk_text: str,
        window_seconds: int,
    ) -> None:
        if window_seconds <= 0:
            return
        with self._lock:
            entry = self._pending.get(container_id)
            if entry is None:
                entry = _Pending(container_id=container_id, container_name=container_name)
                self._pending[container_id] = entry
            else:
                entry.container_name = container_name
            entry.chunks.append(chunk_text)
            if entry.timer is not None:
                entry.timer.cancel()
            entry.timer = threading.Timer(window_seconds, self._fire, args=(container_id,))
            entry.timer.daemon = True
            entry.timer.start()

    def _fire(self, container_id: str) -> None:
        with self._lock:
            entry = self._pending.pop(container_id, None)
        if entry is None or not entry.chunks:
            return
        try:
            with self._app.app_context():
                self._on_flush(entry.container_id, entry.container_name, entry.chunks)
        except Exception:
            logger.exception("coalescer flush failed for container %s", entry.container_name)

    def flush_all(self) -> None:
        """Flush every pending entry synchronously. Intended for shutdown."""
        with self._lock:
            entries = list(self._pending.values())
            self._pending.clear()
        for entry in entries:
            if entry.timer is not None:
                entry.timer.cancel()
            if not entry.chunks:
                continue
            try:
                with self._app.app_context():
                    self._on_flush(entry.container_id, entry.container_name, entry.chunks)
            except Exception:
                logger.exception("coalescer shutdown flush failed for %s", entry.container_name)

    def pending_count(self) -> int:
        with self._lock:
            return sum(len(p.chunks) for p in self._pending.values())
