"""Shared full-scan runtime policies with no adapter dependencies."""

from datetime import datetime, timedelta

from app.modules.catalog.domain.library import LibraryControlState

SCANNABLE_LIBRARY_STATES = frozenset(
    {
        LibraryControlState.ACTIVATING,
        LibraryControlState.ACTIVE,
    }
)


def scan_lease_deadline(now: datetime, lease_seconds: int) -> datetime:
    if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int):
        raise TypeError("lease_seconds must be an integer")
    if not 1 <= lease_seconds <= 3_600:
        raise ValueError("lease_seconds must be between 1 and 3600")
    return now + timedelta(seconds=lease_seconds)


__all__ = ["SCANNABLE_LIBRARY_STATES", "scan_lease_deadline"]
