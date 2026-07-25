from __future__ import annotations

from dataclasses import dataclass


class InvalidRange(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ByteRange:
    start: int | None
    end: int | None


def parse_range_header(value: str | None) -> ByteRange | None:
    if value is None:
        return None
    unit, separator, raw_range = value.partition("=")
    if separator != "=" or unit.strip().casefold() != "bytes":
        raise InvalidRange("only byte ranges are supported")
    if "," in raw_range:
        raise InvalidRange("multiple byte ranges are not supported")
    raw_start, separator, raw_end = raw_range.strip().partition("-")
    if separator != "-" or (not raw_start and not raw_end):
        raise InvalidRange("invalid byte range")
    try:
        start = int(raw_start) if raw_start else None
        end = int(raw_end) if raw_end else None
    except ValueError as error:
        raise InvalidRange("invalid byte range") from error
    if start is not None and start < 0:
        raise InvalidRange("range start cannot be negative")
    if end is not None and end < 0:
        raise InvalidRange("range end cannot be negative")
    if start is not None and end is not None and start > end:
        raise InvalidRange("range start exceeds range end")
    return ByteRange(start=start, end=end)
