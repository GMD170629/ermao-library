"""Deterministic natural ordering for user-provided filenames."""

from __future__ import annotations

import re


def natural_sort_key(value: str) -> tuple[tuple[int, int | str], ...]:
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", value)
        if part
    )


__all__ = ["natural_sort_key"]
