from datetime import timedelta, timezone

from app.core.time import timestamp_ms_to_iso, to_timestamp_ms


def test_naive_datetime_text_defaults_to_utc():
    assert timestamp_ms_to_iso("2026-07-08T04:00:00") == "2026-07-08T04:00:00Z"


def test_legacy_local_timezone_can_be_supplied_explicitly():
    china_standard_time = timezone(timedelta(hours=8))

    assert to_timestamp_ms(
        "2026-07-08T04:00:00",
        naive_timezone=china_standard_time,
    ) == to_timestamp_ms("2026-07-07T20:00:00Z")
