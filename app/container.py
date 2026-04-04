from __future__ import annotations

from dataclasses import dataclass
from typing import Any

_KEY_MAP: dict[str, str] = {
    "telegram": "telegram_notifier",
}


@dataclass
class ServiceContainer:
    llm_client: Any
    llm_call: Any
    verdict_parser: Any
    telegram_notifier: Any
    sentinel: Any
    briefing: Any
    coordinator: Any

    def __getitem__(self, key: str) -> Any:
        """Backwards-compatibility shim for string-key access during migration."""
        mapped = _KEY_MAP.get(key, key)
        return getattr(self, mapped)

    def __setitem__(self, key: str, value: Any) -> None:
        """Backwards-compatibility shim for test injection during migration."""
        mapped = _KEY_MAP.get(key, key)
        setattr(self, mapped, value)
