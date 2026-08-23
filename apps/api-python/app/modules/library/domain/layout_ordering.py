"""Deterministic natural ordering for library layout names."""

from __future__ import annotations

import re
import unicodedata

_DIGIT_GROUPS = re.compile(r"(\d+)")


def natural_sort_key(value: str) -> tuple[tuple[int, int | str], ...]:
    """Return a locale-independent key that orders embedded integers numerically."""

    normalized = unicodedata.normalize("NFC", value)
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in _DIGIT_GROUPS.split(normalized)
        if part
    )
