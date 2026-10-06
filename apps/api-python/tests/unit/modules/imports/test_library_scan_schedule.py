from datetime import UTC, datetime, timedelta

import pytest

from app.modules.imports.domain.library_scan_schedule import (
    LibraryScanIntervalOutOfRange,
    LibraryScanSettings,
    next_periodic_scan_at,
)


def test_library_scan_defaults_to_watcher_on_and_twenty_four_hours() -> None:
    settings = LibraryScanSettings()
    assert settings.watch_enabled is True
    assert settings.interval_minutes == 1440


@pytest.mark.parametrize("minutes", [-1, 1, 4, 5, 30, 60, 1439, 1441, False])
def test_library_scan_rejects_interval_outside_public_bounds(minutes: int) -> None:
    with pytest.raises(LibraryScanIntervalOutOfRange):
        LibraryScanSettings(interval_minutes=minutes)


def test_next_periodic_scan_is_calculated_from_change_time() -> None:
    changed_at = datetime(2026, 8, 24, 12, tzinfo=UTC)
    assert next_periodic_scan_at(changed_at, 1440) == changed_at + timedelta(hours=24)


def test_zero_interval_disables_periodic_scans_without_disabling_watcher() -> None:
    settings = LibraryScanSettings(interval_minutes=0)
    assert settings.watch_enabled is True
    assert next_periodic_scan_at(datetime(2026, 8, 24, tzinfo=UTC), 0) is None
