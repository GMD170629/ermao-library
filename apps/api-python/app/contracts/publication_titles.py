"""Stable publication-title rules shared by import and metadata writeback."""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass

_VOLUME_SUFFIX = re.compile(
    r"(?:Vol[._\s-]*|[\s_.-]*\u7b2c\s*)(?P<index>\d+(?:\.\d+)?)"
    r"(?:\s*[\u5377\u518c])?\s*$",
    flags=re.IGNORECASE,
)
_CHINESE_VOLUME_SUFFIX = re.compile(
    r"(?:[\s_.-]*\u7b2c\s*)?(?P<index>[\u96f6\u3007\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341]+)"
    r"\s*[\u5377\u518c]\s*$"
)
_RANGE_SUFFIX = re.compile(
    r"[\s_.-]*(?:\u7b2c\s*)?(?P<start>\d+(?:\.\d+)?)\s*[-~\uff5e\u2014]\s*"
    r"\d+(?:\.\d+)?\s*[\u8bdd\u7ae0\u5377\u518c\u96c6]\s*$"
)


@dataclass(frozen=True, slots=True)
class PublicationTitles:
    work_title: str | None
    volume_title: str | None
    volume_index: float | None


def titles_from_local_source(
    raw_title: str | None,
    *,
    series_name: str | None = None,
    volume_index: float | None = None,
) -> PublicationTitles:
    """Map one source into independent work, volume-title, and volume-index fields."""

    cleaned_title = _clean(raw_title)
    cleaned_series = _clean(series_name)
    parsed_work_title, parsed_index = split_publication_volume_title(cleaned_title)
    if parsed_index is not None and parsed_work_title == cleaned_title:
        parsed_work_title = None
    resolved_index = volume_index if _valid_volume_index(volume_index) else parsed_index

    if cleaned_series is not None:
        return PublicationTitles(
            work_title=cleaned_series,
            volume_title=(
                cleaned_title
                if cleaned_title is not None
                and _normalized_title(cleaned_title)
                != _normalized_title(cleaned_series)
                else None
            ),
            volume_index=resolved_index,
        )
    return PublicationTitles(
        work_title=parsed_work_title,
        volume_title=cleaned_title if parsed_index is not None else None,
        volume_index=resolved_index,
    )


def finalize_volume_title(
    work_title: str | None,
    volume_title: str | None,
    volume_index: float | None,
) -> str | None:
    """Apply only final fallback rules after all three fields were merged."""

    cleaned_work_title = _clean(work_title)
    cleaned_volume_title = _clean(volume_title)
    if cleaned_volume_title is None:
        cleaned_volume_title = cleaned_work_title
    if (
        cleaned_work_title is not None
        and cleaned_volume_title is not None
        and _normalized_title(cleaned_volume_title)
        == _normalized_title(cleaned_work_title)
        and _valid_volume_index(volume_index)
    ):
        return publication_title_for_volume(cleaned_work_title, volume_index)
    return cleaned_volume_title


def split_publication_volume_title(
    title: str | None,
) -> tuple[str | None, float | None]:
    """Split a trailing ``Vol.x`` suffix from a publication title."""

    if title is None:
        return None, None
    match = _VOLUME_SUFFIX.search(title)
    if match is not None:
        base_title = title[: match.start()].rstrip(" \t\r\n._-–—")
        return (base_title or title), float(match.group("index"))
    range_match = _RANGE_SUFFIX.search(title)
    if range_match is not None:
        base_title = title[: range_match.start()].rstrip(" \t\r\n._-–—")
        return (base_title or title), float(range_match.group("start"))
    chinese_match = _CHINESE_VOLUME_SUFFIX.search(title)
    if chinese_match is None:
        return title, None
    chinese_index = _parse_small_chinese_number(chinese_match.group("index"))
    if chinese_index is None:
        return title, None
    base_title = title[: chinese_match.start()].rstrip(" \t\r\n._-–—")
    return (base_title or title), chinese_index


def _parse_small_chinese_number(value: str) -> float | None:
    digits = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if value in digits:
        return float(digits[value])
    if value == "十":
        return 10.0
    if "十" not in value:
        return None
    left, right = value.split("十", 1)
    if left and left not in digits:
        return None
    if right and right not in digits:
        return None
    return float((digits.get(left, 1) * 10) + digits.get(right, 0))


def publication_title_for_volume(title: str, volume_index: float | None) -> str:
    """Return a stable file-metadata title for one explicitly numbered volume."""

    if volume_index is None or not math.isfinite(volume_index) or volume_index < 0:
        return title
    formatted_index = f"{volume_index:g}"
    suffix = f"Vol.{formatted_index}"
    base_title, existing_index = split_publication_volume_title(title)
    if existing_index == volume_index:
        return title
    if existing_index is not None:
        return f"{base_title} {suffix}"
    return f"{title.rstrip()} {suffix}"


def _clean(value: str | None) -> str | None:
    cleaned = str(value or "").strip()
    return cleaned or None


def _normalized_title(value: str) -> str:
    return "".join(
        character.casefold()
        for character in unicodedata.normalize("NFKC", value)
        if character.isalnum()
    )


def _valid_volume_index(value: float | None) -> bool:
    return value is not None and math.isfinite(value) and value >= 0
