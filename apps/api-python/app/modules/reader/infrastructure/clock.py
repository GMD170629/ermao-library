"""System clock adapter for Reader application use cases."""

from __future__ import annotations

from datetime import UTC, datetime


class SystemReaderClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


__all__ = ["SystemReaderClock"]
