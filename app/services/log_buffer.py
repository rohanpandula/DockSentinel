from __future__ import annotations

import logging
import math
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime

try:
    import tiktoken
except Exception:  # pragma: no cover - optional dependency runtime fallback
    tiktoken = None

from app.time_utils import utcnow_naive


LOGGER = logging.getLogger(__name__)

# A "continuation" line belongs to the previous log record (stack frames,
# traceback bodies, wrapped output). They never count toward the keyword
# flush delay so a multi-line trace is not cut in the middle.
_CONTINUATION_RE = re.compile(
    r"^(?:\s+|at\s|Traceback\b|File\s+\"|Caused by\b|\.\.\.)"
)


def is_continuation_line(line: str) -> bool:
    return bool(line) and _CONTINUATION_RE.match(line) is not None


@dataclass(slots=True)
class BufferChunk:
    container_id: str
    text: str
    input_chars: int
    estimated_tokens: int
    container_name: str | None = None


@dataclass(slots=True)
class _BufferState:
    lines: list[str] = field(default_factory=list)
    chars: int = 0
    tokens: int = 0  # running estimate; recomputed exactly at flush
    last_activity: datetime = field(default_factory=utcnow_naive)
    keyword_primed: bool = False
    lines_since_keyword: int = 0
    container_name: str | None = None


class LogBuffer:
    def __init__(
        self,
        max_input_chars: int,
        max_input_tokens: int,
        reserved_output_tokens: int,
        token_strategy: str = "chars",
        model_name: str | None = None,
        flush_window_seconds: int = 15,
        keyword_flush_delay_lines: int = 0,
    ) -> None:
        self.max_input_chars = max_input_chars
        self.max_input_tokens = max_input_tokens
        self.reserved_output_tokens = reserved_output_tokens
        self.token_strategy = token_strategy
        self.model_name = model_name
        self.flush_window_seconds = flush_window_seconds
        self.keyword_flush_delay_lines = keyword_flush_delay_lines
        self._buffers: dict[str, _BufferState] = {}
        self._lock = threading.Lock()
        self._warned_tiktoken_missing = False
        self._warned_model_unknown = False
        self._encoding_model: str | None = None
        self._encoding = None

    # ------------------------------------------------------------------ tokens
    def _estimate_tokens_chars(self, text: str) -> int:
        return max(1, math.ceil(len(text) / 4))

    def _tiktoken_encoding(self):
        """Return a cached tiktoken encoding for the configured model, or None."""
        if tiktoken is None:
            if not self._warned_tiktoken_missing:
                LOGGER.warning("tiktoken strategy requested but dependency is unavailable; using char heuristic")
                self._warned_tiktoken_missing = True
            return None

        if not self.model_name:
            if not self._warned_model_unknown:
                LOGGER.warning("tiktoken strategy requested but no model is configured; using char heuristic")
                self._warned_model_unknown = True
            return None

        if self._encoding is not None and self._encoding_model == self.model_name:
            return self._encoding
        try:
            encoding = tiktoken.encoding_for_model(self.model_name)
        except Exception:
            if not self._warned_model_unknown:
                LOGGER.warning(
                    "tiktoken does not recognize model '%s'; using char heuristic",
                    self.model_name,
                )
                self._warned_model_unknown = True
            return None
        self._encoding = encoding
        self._encoding_model = self.model_name
        return encoding

    def _estimate_tokens_tiktoken(self, text: str) -> int:
        encoding = self._tiktoken_encoding()
        if encoding is None:
            return self._estimate_tokens_chars(text)
        return len(encoding.encode(text))

    def estimate_tokens(self, text: str) -> int:
        if self.token_strategy == "tiktoken":
            return self._estimate_tokens_tiktoken(text)
        return self._estimate_tokens_chars(text)

    def _running_tokens(self, state: _BufferState, payload: str) -> int:
        """Incremental estimate after appending ``payload`` (O(len(payload)))."""
        if self.token_strategy == "tiktoken":
            encoding = self._tiktoken_encoding()
            if encoding is not None:
                return state.tokens + len(encoding.encode(payload))
        return max(1, math.ceil(state.chars / 4))

    # ------------------------------------------------------------------ flush
    def _flush(self, container_id: str) -> BufferChunk | None:
        """Pop and return the container's pending chunk. Caller holds the lock."""
        state = self._buffers.get(container_id)
        if state is None or state.chars == 0:
            # Drop empty state so idle containers don't accumulate.
            self._buffers.pop(container_id, None)
            return None

        self._buffers.pop(container_id, None)
        text = "".join(state.lines)
        return BufferChunk(
            container_id=container_id,
            text=text,
            input_chars=len(text),
            estimated_tokens=self.estimate_tokens(text),
            container_name=state.container_name,
        )

    def add_line(
        self,
        container_id: str,
        line: str,
        keyword_hit: bool,
        container_name: str | None = None,
    ) -> list[BufferChunk]:
        now = utcnow_naive()
        chunks: list[BufferChunk] = []
        with self._lock:
            state = self._buffers.get(container_id)
            if state is not None and state.chars > 0:
                elapsed = (now - state.last_activity).total_seconds()
                if elapsed >= self.flush_window_seconds:
                    maybe_chunk = self._flush(container_id)
                    if maybe_chunk:
                        chunks.append(maybe_chunk)
                    state = None
            if state is None:
                state = _BufferState()
                self._buffers[container_id] = state
            if container_name:
                state.container_name = container_name

            payload = f"{line.rstrip()}\n"
            continuation = is_continuation_line(line)
            state.lines.append(payload)
            state.chars += len(payload)
            state.tokens = self._running_tokens(state, payload)
            state.last_activity = now

            # Track keyword priming for delayed flush. Continuation lines
            # (stack frames etc.) do not count toward the delay.
            if keyword_hit:
                state.keyword_primed = True
                state.lines_since_keyword = 0
            elif state.keyword_primed and not continuation:
                state.lines_since_keyword += 1

            # Flush conditions:
            # 1. Size limit exceeded (chars or tokens) — always flush immediately.
            # 2. Keyword primed AND delay lines met (or delay == 0 for legacy
            #    immediate), and the current line is not a continuation — a
            #    trace in progress is kept intact until a normal line arrives.
            size_exceeded = state.chars >= self.max_input_chars or state.tokens >= self.max_input_tokens
            keyword_ready = (
                state.keyword_primed
                and not continuation
                and (
                    self.keyword_flush_delay_lines == 0
                    or state.lines_since_keyword >= self.keyword_flush_delay_lines
                )
            )

            if size_exceeded or keyword_ready:
                maybe_chunk = self._flush(container_id)
                if maybe_chunk:
                    chunks.append(maybe_chunk)

        return chunks

    def flush_container(self, container_id: str) -> BufferChunk | None:
        with self._lock:
            return self._flush(container_id)

    def drop_container(self, container_id: str) -> None:
        """Discard any buffered lines for a container without emitting a chunk."""
        with self._lock:
            self._buffers.pop(container_id, None)

    def flush_idle(self, now: datetime | None = None) -> list[BufferChunk]:
        """Flush containers that have gone quiet.

        A keyword-primed buffer is flushed once it has been idle for
        ``flush_window_seconds`` (an error followed by silence must not wait
        for the next log line). Any non-empty buffer is flushed after
        ``2 * flush_window_seconds`` of silence.
        """
        now = now or utcnow_naive()
        window = max(0, self.flush_window_seconds)
        chunks: list[BufferChunk] = []
        with self._lock:
            for container_id, state in list(self._buffers.items()):
                if state.chars == 0:
                    self._buffers.pop(container_id, None)
                    continue
                idle = (now - state.last_activity).total_seconds()
                if (state.keyword_primed and idle >= window) or idle >= 2 * window:
                    maybe_chunk = self._flush(container_id)
                    if maybe_chunk:
                        chunks.append(maybe_chunk)
        return chunks

    def set_limits(
        self,
        max_input_chars: int,
        max_input_tokens: int,
        reserved_output_tokens: int,
        token_strategy: str,
        model_name: str | None,
        keyword_flush_delay_lines: int = 0,
    ) -> None:
        with self._lock:
            self.max_input_chars = max_input_chars
            self.max_input_tokens = max_input_tokens
            self.reserved_output_tokens = reserved_output_tokens
            self.token_strategy = token_strategy
            self.model_name = model_name
            self.keyword_flush_delay_lines = keyword_flush_delay_lines
