from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime

try:
    import tiktoken
except Exception:  # pragma: no cover - optional dependency runtime fallback
    tiktoken = None

from app.time_utils import utcnow_naive


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class BufferChunk:
    container_id: str
    text: str
    input_chars: int
    estimated_tokens: int


@dataclass(slots=True)
class _BufferState:
    lines: list[str] = field(default_factory=list)
    chars: int = 0
    last_activity: datetime = field(default_factory=utcnow_naive)


class LogBuffer:
    def __init__(
        self,
        max_input_chars: int,
        max_input_tokens: int,
        reserved_output_tokens: int,
        token_strategy: str = "chars",
        model_name: str | None = None,
        flush_window_seconds: int = 15,
    ) -> None:
        self.max_input_chars = max_input_chars
        self.max_input_tokens = max_input_tokens
        self.reserved_output_tokens = reserved_output_tokens
        self.token_strategy = token_strategy
        self.model_name = model_name
        self.flush_window_seconds = flush_window_seconds
        self._buffers: dict[str, _BufferState] = {}
        self._warned_tiktoken_missing = False
        self._warned_model_unknown = False

    def _estimate_tokens_chars(self, text: str) -> int:
        return max(1, math.ceil(len(text) / 4))

    def _estimate_tokens_tiktoken(self, text: str) -> int:
        if tiktoken is None:
            if not self._warned_tiktoken_missing:
                LOGGER.warning("tiktoken strategy requested but dependency is unavailable; using char heuristic")
                self._warned_tiktoken_missing = True
            return self._estimate_tokens_chars(text)

        if not self.model_name:
            if not self._warned_model_unknown:
                LOGGER.warning("tiktoken strategy requested but no model is configured; using char heuristic")
                self._warned_model_unknown = True
            return self._estimate_tokens_chars(text)
        try:
            encoding = tiktoken.encoding_for_model(self.model_name)
        except Exception:
            if not self._warned_model_unknown:
                LOGGER.warning(
                    "tiktoken does not recognize model '%s'; using char heuristic",
                    self.model_name,
                )
                self._warned_model_unknown = True
            return self._estimate_tokens_chars(text)
        return len(encoding.encode(text))

    def estimate_tokens(self, text: str) -> int:
        if self.token_strategy == "tiktoken":
            return self._estimate_tokens_tiktoken(text)
        return self._estimate_tokens_chars(text)

    def _flush(self, container_id: str) -> BufferChunk | None:
        state = self._buffers.get(container_id)
        if state is None or state.chars == 0:
            return None

        text = "".join(state.lines)
        chunk = BufferChunk(
            container_id=container_id,
            text=text,
            input_chars=len(text),
            estimated_tokens=self.estimate_tokens(text),
        )
        self._buffers[container_id] = _BufferState()
        return chunk

    def add_line(self, container_id: str, line: str, keyword_hit: bool) -> list[BufferChunk]:
        now = utcnow_naive()
        state = self._buffers.setdefault(container_id, _BufferState())
        chunks: list[BufferChunk] = []

        elapsed = (now - state.last_activity).total_seconds()
        if state.chars > 0 and elapsed >= self.flush_window_seconds:
            maybe_chunk = self._flush(container_id)
            if maybe_chunk:
                chunks.append(maybe_chunk)
            state = self._buffers.setdefault(container_id, _BufferState())

        payload = f"{line.rstrip()}\n"
        state.lines.append(payload)
        state.chars += len(payload)
        state.last_activity = now

        estimated_tokens = self.estimate_tokens("".join(state.lines))
        if keyword_hit or state.chars >= self.max_input_chars or estimated_tokens >= self.max_input_tokens:
            maybe_chunk = self._flush(container_id)
            if maybe_chunk:
                chunks.append(maybe_chunk)

        return chunks

    def flush_container(self, container_id: str) -> BufferChunk | None:
        return self._flush(container_id)

    def set_limits(
        self,
        max_input_chars: int,
        max_input_tokens: int,
        reserved_output_tokens: int,
        token_strategy: str,
        model_name: str | None,
    ) -> None:
        self.max_input_chars = max_input_chars
        self.max_input_tokens = max_input_tokens
        self.reserved_output_tokens = reserved_output_tokens
        self.token_strategy = token_strategy
        self.model_name = model_name
