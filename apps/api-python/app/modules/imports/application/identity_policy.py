"""Pure identity normalization shared by import decisions."""

from __future__ import annotations

import re
import unicodedata

UNKNOWN_AUTHOR = "未知作者"


def split_standalone_numeric_volume(value: str) -> tuple[str, float] | None:
    """Split a standalone numeric volume from a publication title.

    This is a low-priority fallback for names that omit an explicit volume
    marker, such as ``Title (1)``, ``Title [02]``, ``Title_003``, or
    ``004 Title``. Digits attached directly to title text are intentionally not
    treated as volumes.
    """

    cleaned = value.strip()
    patterns = (
        (r"^(.*?)\s*[\(（\[【]\s*(\d+(?:\.\d+)?)\s*[\)）\]】]\s*$", 1, 2),
        (r"^[\(（\[【]\s*(\d+(?:\.\d+)?)\s*[\)）\]】]\s*(.*?)$", 2, 1),
        (r"^(.*?)[\s._-]+(\d+(?:\.\d+)?)\s*$", 1, 2),
        (r"^(\d+(?:\.\d+)?)[\s._-]+(.*?)$", 2, 1),
    )
    for pattern, title_group, volume_group in patterns:
        match = re.match(pattern, cleaned)
        if not match or not match.group(title_group).strip():
            continue
        volume_index = float(match.group(volume_group))
        if volume_index > 0:
            return match.group(title_group).strip(), volume_index
    return None


def normalize_identity_part(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(
        r"[\s_\-.[\]()（）【】《》:：,，!！?？\"'“”‘’·・、/\\]+",
        "",
        normalized,
    ).strip()


def identity_merge_key(title: str, author: str | None) -> str:
    return (
        f"{normalize_identity_part(title)}:"
        f"{normalize_identity_part(author or UNKNOWN_AUTHOR)}"
    )


def parse_bracketed_series_identity(
    folder_name: str, filename: str | None = None
) -> tuple[str, str] | None:
    raw_parts = re.findall(r"\[([^\]]+)\]", folder_name)
    if len(raw_parts) < 2 or not re.fullmatch(
        r"\s*(?:\[[^\]]+\]\s*)+", folder_name
    ):
        return None
    parts = [_clean_title(part) for part in raw_parts]
    if not parts[0] or not parts[1]:
        return None

    filename_title = _filename_series_title(filename) if filename else ""
    filename_key = normalize_identity_part(filename_title)
    first_keys = [
        normalize_identity_part(parts[0]),
        normalize_identity_part(parts[1]),
    ]
    if filename_key:
        for title_index, part_key in enumerate(first_keys):
            if filename_key == part_key:
                author = _clean_author(parts[1 - title_index]) or UNKNOWN_AUTHOR
                return parts[title_index], author

    volume_range_indexes = [
        index
        for index, part in enumerate(raw_parts)
        if index >= 2 and _looks_like_volume_range(part)
    ]
    if (
        len(parts) >= 4
        and volume_range_indexes
        and volume_range_indexes[0] == 3
        and _looks_like_latin_alias(parts[0])
        and not _looks_like_latin_alias(parts[1])
        and not _looks_like_latin_alias(parts[2])
    ):
        return parts[1], _clean_author(parts[2]) or UNKNOWN_AUTHOR

    if len(parts) == 2 or (
        len(raw_parts) > 2 and _looks_like_volume_range(raw_parts[2])
    ):
        return parts[0], _clean_author(parts[1]) or UNKNOWN_AUTHOR
    return None


def _looks_like_latin_alias(value: str) -> bool:
    cleaned = unicodedata.normalize("NFKC", value).strip()
    return bool(
        re.fullmatch(r"[A-Z][A-Z0-9 ._'’&:+-]*", cleaned, re.I)
        and re.search(r"[A-Z]", cleaned, re.I)
    )


def _filename_series_title(filename: str) -> str:
    stem = _clean_title(filename)
    without_volume, _volume = _strip_volume_suffix(stem)
    title = re.split(r"\s+\[", without_volume, maxsplit=1)[0]
    return _clean_title(title)


def _looks_like_volume_range(value: str) -> bool:
    return bool(
        re.search(
            r"(?:vol(?:ume)?\.?|v|第)?\s*\d+(?:\.\d+)?\s*[-~至到]\s*"
            r"(?:vol(?:ume)?\.?|v|第)?\s*\d+(?:\.\d+)?",
            value,
            re.I,
        )
    )


def _strip_volume_suffix(value: str) -> tuple[str, float | None]:
    cleaned = value.strip()
    for pattern in (
        r"^(.*?)\s*(?:vol(?:ume)?\.?|v)\s*(\d+(?:\.\d+)?)$",
        r"^(.*?)\s*第\s*(\d+(?:\.\d+)?)\s*(?:卷|冊|册|集)$",
        r"^(.*?)\s+(\d+(?:\.\d+)?)$",
    ):
        match = re.match(pattern, cleaned, re.I)
        if match and match.group(1).strip():
            return _clean_title(match.group(1)), float(match.group(2))
    numeric_fallback = split_standalone_numeric_volume(cleaned)
    if numeric_fallback is not None:
        title, volume_index = numeric_fallback
        return _clean_title(title), volume_index
    return cleaned, None


def _clean_title(value: str) -> str:
    cleaned = re.sub(
        r"\.(?:epub|cbz|zip|pdf|m4b|m4a|mp3)$", "", value, flags=re.I
    )
    return re.sub(r"\s+", " ", cleaned.replace("_", " ")).strip(" ._-")


def _clean_author(value: str) -> str:
    cleaned = _clean_title(value)
    cleaned = re.sub(r"^[\(（][^)）]+[\)）]\s*", "", cleaned)
    return cleaned.strip()
