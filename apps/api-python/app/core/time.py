from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import BigInteger
from sqlalchemy.types import TypeDecorator

TIMESTAMP_MILLISECONDS_MIN = 100_000_000_000


def now_timestamp_ms() -> int:
    """Return the current Unix timestamp in milliseconds."""

    return time.time_ns() // 1_000_000


def to_timestamp_ms(value: Any, *, naive_timezone=None) -> int | None:
    """Normalize legacy datetime values and Unix seconds/milliseconds."""

    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = int(value)
        return numeric if abs(numeric) >= TIMESTAMP_MILLISECONDS_MIN else numeric * 1000
    text_value = str(value).strip()
    if re.fullmatch(r"-?\d+(?:\.\d+)?", text_value):
        numeric = int(float(text_value))
        return numeric if abs(numeric) >= TIMESTAMP_MILLISECONDS_MIN else numeric * 1000
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(text_value)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=naive_timezone or UTC)
    return int(parsed.timestamp() * 1000)


def timestamp_ms_to_datetime(value: Any) -> datetime | None:
    timestamp = to_timestamp_ms(value)
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp / 1000, UTC)


def timestamp_ms_to_iso(value: Any) -> str | None:
    parsed = timestamp_ms_to_datetime(value)
    return parsed.isoformat().replace("+00:00", "Z") if parsed else None


class TimestampMilliseconds(TypeDecorator[datetime]):
    """Persist Unix milliseconds while preserving datetime model APIs."""

    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value: Any, _dialect) -> int | None:
        return to_timestamp_ms(value)

    def process_result_value(self, value: Any, _dialect) -> datetime | None:
        return timestamp_ms_to_datetime(value)


class ExactTimestampMilliseconds(TypeDecorator[datetime]):
    """Persist epoch milliseconds without legacy unit guessing.

    ``TimestampMilliseconds`` accepts old second-based values for the
    pre-v5 schema. Reader v5's wire contract is unambiguously epoch
    milliseconds, including small test/future values, so its isolated tables
    use this exact adapter instead.
    """

    impl = BigInteger
    cache_ok = True

    def process_bind_param(self, value: Any, _dialect) -> int | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
            return int(aware.timestamp() * 1000)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError("exact epoch milliseconds require a datetime or number")
        return int(value)

    def process_result_value(self, value: Any, _dialect) -> datetime | None:
        if value is None:
            return None
        return datetime.fromtimestamp(int(value) / 1000, UTC)
