"""Deterministic natural ordering for user-provided filenames."""

from __future__ import annotations

import re
import unicodedata


def natural_sort_key(value: str) -> tuple[tuple[int, int | str], ...]:
    normalized = unicodedata.normalize("NFC", value).casefold()
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in re.split(r"(\d+)", normalized)
        if part
    )


__all__ = ["natural_sort_key"]
