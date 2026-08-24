"""Policies for library watcher and periodic reconciliation settings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

LIBRARY_SCAN_WATCH_ENABLED_KEY = "libraryScan.watchEnabled"
LIBRARY_SCAN_INTERVAL_MINUTES_KEY = "libraryScan.intervalMinutes"
DEFAULT_LIBRARY_SCAN_INTERVAL_MINUTES = 30
MIN_LIBRARY_SCAN_INTERVAL_MINUTES = 5
MAX_LIBRARY_SCAN_INTERVAL_MINUTES = 1440


class LibraryScanIntervalOutOfRange(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LibraryScanSettings:
    watch_enabled: bool = True
    interval_minutes: int = DEFAULT_LIBRARY_SCAN_INTERVAL_MINUTES

    def __post_init__(self) -> None:
        if (
            not MIN_LIBRARY_SCAN_INTERVAL_MINUTES
            <= self.interval_minutes
            <= MAX_LIBRARY_SCAN_INTERVAL_MINUTES
        ):
            raise LibraryScanIntervalOutOfRange(self.interval_minutes)


def legacy_interval_minutes(interval_ms: int | None) -> int:
    if interval_ms is None or interval_ms <= 0:
        return DEFAULT_LIBRARY_SCAN_INTERVAL_MINUTES
    rounded_up = (interval_ms + 59_999) // 60_000
    return min(
        MAX_LIBRARY_SCAN_INTERVAL_MINUTES,
        max(MIN_LIBRARY_SCAN_INTERVAL_MINUTES, rounded_up),
    )


def next_periodic_scan_at(changed_at: datetime, interval_minutes: int) -> datetime:
    LibraryScanSettings(interval_minutes=interval_minutes)
    return changed_at + timedelta(minutes=interval_minutes)


__all__ = [
    "DEFAULT_LIBRARY_SCAN_INTERVAL_MINUTES",
    "LIBRARY_SCAN_INTERVAL_MINUTES_KEY",
    "LIBRARY_SCAN_WATCH_ENABLED_KEY",
    "MAX_LIBRARY_SCAN_INTERVAL_MINUTES",
    "MIN_LIBRARY_SCAN_INTERVAL_MINUTES",
    "LibraryScanIntervalOutOfRange",
    "LibraryScanSettings",
    "legacy_interval_minutes",
    "next_periodic_scan_at",
]
