from __future__ import annotations

from datetime import UTC, datetime


def utcnow_naive() -> datetime:
    """Return UTC timestamp as naive datetime for SQLite DateTime columns."""
    return datetime.now(UTC).replace(tzinfo=None)

