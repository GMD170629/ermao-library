"""Pure identity normalization shared by import decisions."""

from __future__ import annotations

import re
import unicodedata

UNKNOWN_AUTHOR = "未知作者"

_CJK_VOLUME_MARKER = (
    "(?:"
    + "|".join(chr(codepoint) for codepoint in (0x5377, 0x518A, 0x518C, 0x96C6, 0x5DFB))
    + ")"
)
_CJK_ORDINAL_PREFIX = chr(0x7B2C)
_VOLUME_NUMBER = r"\d+(?:\.\d+)?"
_SHORT_VOLUME_NUMBER = r"\d{1,3}(?:\.\d{1,2})?"
_EXPLICIT_VOLUME_PATTERN = re.compile(
    rf"(?:vol(?:ume)?\.?|v)[\s._-]*(?P<latin_number>{_VOLUME_NUMBER})"
    rf"\s*{_CJK_VOLUME_MARKER}?"
    rf"|(?:{_CJK_ORDINAL_PREFIX}\s*)?(?P<suffixed_number>{_VOLUME_NUMBER})\s*{_CJK_VOLUME_MARKER}"
    rf"|{_CJK_VOLUME_MARKER}\s*(?:{_CJK_ORDINAL_PREFIX}\s*)?(?P<prefixed_number>{_VOLUME_NUMBER})",
    re.IGNORECASE,
)
_VOLUME_RANGE_SEPARATOR = rf"[-~{chr(0x81F3)}{chr(0x5230)}]"
_VOLUME_RANGE_ENDPOINT = (
    rf"(?:(?:vol(?:ume)?\.?|v|{_CJK_VOLUME_MARKER})\s*(?:{_CJK_ORDINAL_PREFIX}\s*)?{_VOLUME_NUMBER}"
    rf"|(?:{_CJK_ORDINAL_PREFIX}\s*)?{_VOLUME_NUMBER}\s*{_CJK_VOLUME_MARKER}?"
    rf"|{_VOLUME_NUMBER})"
)
_EXPLICIT_VOLUME_RANGE_PATTERN = re.compile(
    rf"{_VOLUME_RANGE_ENDPOINT}\s*{_VOLUME_RANGE_SEPARATOR}\s*"
    rf"{_VOLUME_RANGE_ENDPOINT}",
    re.IGNORECASE,
)
_RANGE_VOLUME_UNIT = (
    "(?:"
    + "|".join(
        chr(codepoint)
        for codepoint in (0x5377, 0x518A, 0x518C, 0x96C6, 0x8BDD, 0x7AE0, 0x56DE)
    )
    + ")"
)
_VOLUME_RANGE_START_PATTERN = re.compile(
    rf"(?P<prefix>vol(?:ume)?\.?|v|{_CJK_ORDINAL_PREFIX}|{_RANGE_VOLUME_UNIT})?\s*"
    rf"(?P<start>{_VOLUME_NUMBER})\s*(?P<start_unit>{_RANGE_VOLUME_UNIT})?\s*"
    rf"{_VOLUME_RANGE_SEPARATOR}\s*"
    rf"(?P<end_prefix>vol(?:ume)?\.?|v|{_CJK_ORDINAL_PREFIX}|{_RANGE_VOLUME_UNIT})?\s*"
    rf"(?P<end>{_VOLUME_NUMBER})\s*(?P<end_unit>{_RANGE_VOLUME_UNIT})?",
    re.IGNORECASE,
)


def contains_explicit_volume_range(value: str) -> bool:
    """Return whether a title describes a range rather than one volume."""

    return _EXPLICIT_VOLUME_RANGE_PATTERN.search(value) is not None


def explicit_volume_range_start(value: str) -> float | None:
    """Return the first number of an explicitly marked publication range.

    A range must contain an ordinal, volume, chapter, episode, or Latin volume
    marker. This avoids treating ordinary year ranges as publication order.
    Callers should apply this to a source filename, not a collection folder:
    an explicitly marked episode range starts at volume 1, while an unmarked
    numeric range remains a work title.
    """

    for match in _VOLUME_RANGE_START_PATTERN.finditer(value):
        if not any(
            match.group(group)
            for group in ("prefix", "start_unit", "end_prefix", "end_unit")
        ):
            continue
        start = float(match.group("start"))
        end = float(match.group("end"))
        if start > 0 and end >= start:
            return start
    return None


def split_explicit_volume(value: str) -> tuple[str, float] | None:
    """Remove and return an explicit volume marker wherever it appears.

    Explicit numeric markers are unambiguous enough to occur before, inside,
    or after a publication title.
    A marker that belongs to a volume range describes a collection rather than
    one publication and is therefore ignored.
    """

    if contains_explicit_volume_range(value):
        return None
    for match in _EXPLICIT_VOLUME_PATTERN.finditer(value):
        if _explicit_marker_belongs_to_range(value, match.start(), match.end()):
            continue
        number = (
            match.group("latin_number")
            or match.group("suffixed_number")
            or match.group("prefixed_number")
        )
        volume_index = float(number)
        if volume_index <= 0:
            continue
        title = _title_without_marker(value, match.start(), match.end())
        if title:
            return title, volume_index
    return None


def _explicit_marker_belongs_to_range(value: str, start: int, end: int) -> bool:
    marker_before_range = re.match(
        rf"^\s*{_VOLUME_RANGE_SEPARATOR}\s*"
        rf"(?:(?:vol(?:ume)?\.?|v|{_CJK_VOLUME_MARKER})\s*|(?:{_CJK_ORDINAL_PREFIX}\s*)?)?\d",
        value[end:],
        re.IGNORECASE,
    )
    marker_after_range = re.search(
        rf"(?:{_VOLUME_NUMBER}\s*{_CJK_VOLUME_MARKER}?|"
        rf"(?:vol(?:ume)?\.?|v|{_CJK_VOLUME_MARKER})\s*{_VOLUME_NUMBER})"
        rf"\s*{_VOLUME_RANGE_SEPARATOR}\s*$",
        value[:start],
        re.IGNORECASE,
    )
    return marker_before_range is not None or marker_after_range is not None


def _title_without_marker(value: str, start: int, end: int) -> str:
    raw_left = value[:start]
    raw_right = value[end:]
    had_separator = bool(
        re.search(r"[\s._-]$", raw_left) or re.match(r"^[\s._-]", raw_right)
    )
    left = raw_left.rstrip(" \t._-")
    right = raw_right.lstrip(" \t._-")
    separator = " " if left and right and had_separator else ""
    return re.sub(r"\s+", " ", f"{left}{separator}{right}").strip()


def split_numeric_volume_fallback(value: str) -> tuple[str, float] | None:
    """Split a short numeric volume from anywhere in a publication title.

    This is a low-priority fallback for names that omit an explicit volume
    marker, such as ``Title (1)``, ``Title [02]``, ``Title_003``, or
    ``Series10Subtitle``. Integer parts are limited to three digits so years and
    long identifiers are not treated as volume numbers.
    """

    cleaned = value.strip()
    patterns = (
        (
            rf"^(.*?)\s*[\(（\[【]\s*({_SHORT_VOLUME_NUMBER})\s*[\)）\]】]\s*$",
            1,
            2,
        ),
        (
            rf"^[\(（\[【]\s*({_SHORT_VOLUME_NUMBER})\s*[\)）\]】]\s*(.*?)$",
            2,
            1,
        ),
        (rf"^(.*?)[\s._-]+({_SHORT_VOLUME_NUMBER})\s*$", 1, 2),
        (rf"^({_SHORT_VOLUME_NUMBER})[\s._-]+(.*?)$", 2, 1),
    )
    for pattern, title_group, volume_group in patterns:
        match = re.match(pattern, cleaned)
        if not match or not match.group(title_group).strip():
            continue
        volume_index = float(match.group(volume_group))
        if volume_index > 0:
            return match.group(title_group).strip(), volume_index
    source_suffix_start = _download_source_suffix_start(cleaned)
    for match in re.finditer(rf"(?<!\d)({_SHORT_VOLUME_NUMBER})(?!\d)", cleaned):
        if source_suffix_start is not None and match.start() >= source_suffix_start:
            continue
        volume_index = float(match.group(1))
        title = _title_without_marker(cleaned, match.start(), match.end())
        if volume_index > 0 and title:
            return title, volume_index
    return None


def _download_source_suffix_start(value: str) -> int | None:
    suffix = re.search(r"[\(（]([^()（）]*)[\)）]\s*$", value)
    if suffix is None:
        return None
    if re.search(r"[a-z0-9-]+\.[a-z0-9-]+", suffix.group(1), re.IGNORECASE):
        return suffix.start()
    return None


def normalize_identity_part(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(
        r"[\s_\-.[\]()（）【】《》:：,，!！?？\"'“”‘’·・、/\\]+",
        "",
        normalized,
    ).strip()


def parse_bracketed_series_identity(
    folder_name: str, filename: str | None = None
) -> tuple[str, str] | None:
    raw_parts = re.findall(r"\[([^\]]+)\]", folder_name)
    if len(raw_parts) < 2 or not re.fullmatch(r"\s*(?:\[[^\]]+\]\s*)+", folder_name):
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
        re.fullmatch(r"[A-Z][A-Z0-9 ._'’&:+-]*", cleaned, re.IGNORECASE)
        and re.search(r"[A-Z]", cleaned, re.IGNORECASE)
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
            re.IGNORECASE,
        )
    )


def _strip_volume_suffix(value: str) -> tuple[str, float | None]:
    cleaned = value.strip()
    for pattern in (
        r"^(.*?)\s*(?:vol(?:ume)?\.?|v)\s*(\d+(?:\.\d+)?)$",
        r"^(.*?)\s*第\s*(\d+(?:\.\d+)?)\s*(?:卷|冊|册|集)$",
        r"^(.*?)\s+(\d+(?:\.\d+)?)$",
    ):
        match = re.match(pattern, cleaned, re.IGNORECASE)
        if match and match.group(1).strip():
            return _clean_title(match.group(1)), float(match.group(2))
    numeric_fallback = split_numeric_volume_fallback(cleaned)
    if numeric_fallback is not None:
        title, volume_index = numeric_fallback
        return _clean_title(title), volume_index
    return cleaned, None


def _clean_title(value: str) -> str:
    cleaned = re.sub(
        r"\.(?:epub|cbz|zip|pdf|m4b|m4a|mp3)$",
        "",
        value,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", cleaned.replace("_", " ")).strip(" ._-")


def _clean_author(value: str) -> str:
    cleaned = _clean_title(value)
    cleaned = re.sub(r"^[\(（][^)）]+[\)）]\s*", "", cleaned)
    return cleaned.strip()
