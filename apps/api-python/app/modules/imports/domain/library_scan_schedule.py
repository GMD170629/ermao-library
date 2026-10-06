"""Policies for library watcher and periodic reconciliation settings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

LIBRARY_SCAN_WATCH_ENABLED_KEY = "libraryScan.watchEnabled"
LIBRARY_SCAN_INTERVAL_MINUTES_KEY = "libraryScan.intervalMinutes"
DEFAULT_LIBRARY_SCAN_INTERVAL_MINUTES = 1440


class LibraryScanIntervalOutOfRange(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LibraryScanSettings:
    watch_enabled: bool = True
    interval_minutes: int = DEFAULT_LIBRARY_SCAN_INTERVAL_MINUTES

    def __post_init__(self) -> None:
        if type(self.interval_minutes) is not int or self.interval_minutes not in (
            0, DEFAULT_LIBRARY_SCAN_INTERVAL_MINUTES
        ):
            raise LibraryScanIntervalOutOfRange(self.interval_minutes)


def next_periodic_scan_at(
    changed_at: datetime, interval_minutes: int
) -> datetime | None:
    LibraryScanSettings(interval_minutes=interval_minutes)
    if interval_minutes == 0:
        return None
    return changed_at + timedelta(minutes=interval_minutes)


__all__ = [
    "DEFAULT_LIBRARY_SCAN_INTERVAL_MINUTES",
    "LIBRARY_SCAN_INTERVAL_MINUTES_KEY",
    "LIBRARY_SCAN_WATCH_ENABLED_KEY",
    "LibraryScanIntervalOutOfRange",
    "LibraryScanSettings",
    "next_periodic_scan_at",
]
