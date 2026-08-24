from datetime import UTC, datetime, timedelta

import pytest

from app.modules.imports.domain.library_scan_schedule import (
    LibraryScanIntervalOutOfRange,
    LibraryScanSettings,
    legacy_interval_minutes,
    next_periodic_scan_at,
)


def test_library_scan_defaults_to_watcher_on_and_thirty_minutes() -> None:
    settings = LibraryScanSettings()
    assert settings.watch_enabled is True
    assert settings.interval_minutes == 30


@pytest.mark.parametrize("minutes", [4, 1441])
def test_library_scan_rejects_interval_outside_public_bounds(minutes: int) -> None:
    with pytest.raises(LibraryScanIntervalOutOfRange):
        LibraryScanSettings(interval_minutes=minutes)


def test_legacy_milliseconds_are_only_a_bounded_fallback() -> None:
    assert legacy_interval_minutes(None) == 30
    assert legacy_interval_minutes(30_000) == 5
    assert legacy_interval_minutes(3_600_000) == 60


def test_next_periodic_scan_is_calculated_from_change_time() -> None:
    changed_at = datetime(2026, 8, 24, 12, tzinfo=UTC)
    assert next_periodic_scan_at(changed_at, 30) == changed_at + timedelta(minutes=30)
