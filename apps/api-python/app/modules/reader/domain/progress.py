"""Pure progress navigation and percent projection rules."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import unquote


def _parse_json(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def number_or_none(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def raw_progress_percent(progress: dict[str, Any] | None) -> int:
    return max(0, min(100, round(float(progress.get("percent", 0) if progress else 0))))


def normalize_reader_href(value: Any, include_fragment: bool = True) -> str:
    if not isinstance(value, str) or not value:
        return ""
    raw_path, separator, raw_fragment = value.strip().replace("\\", "/").partition("#")
    path = unquote(raw_path).lstrip("./").lower()
    fragment = unquote(raw_fragment)
    return f"{path}#{fragment}" if include_fragment and separator else path


def reader_unit_index(current_href: Any, units: list[dict[str, Any]]) -> int | None:
    full_href = normalize_reader_href(current_href)
    if not full_href:
        return None
    exact_matches = [
        index
        for index, unit in enumerate(units)
        if normalize_reader_href(unit.get("href")) == full_href
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if "#" in full_href:
        return None
    resource_href = normalize_reader_href(current_href, include_fragment=False)
    resource_matches = [
        index
        for index, unit in enumerate(units)
        if normalize_reader_href(unit.get("href"), include_fragment=False)
        == resource_href
    ]
    return resource_matches[0] if len(resource_matches) == 1 else None


def _unit_navigation_key(unit: dict[str, Any]) -> str | None:
    direct = unit.get("navigationKey")
    if isinstance(direct, str) and direct:
        return direct
    metadata = _parse_json(unit.get("metadataJson"), {})
    if not isinstance(metadata, dict) or metadata.get("exactNavigation") is not True:
        return None
    candidate = metadata.get("navigationKey")
    return candidate if isinstance(candidate, str) and candidate else None


def progress_location(progress: dict[str, Any] | None) -> dict[str, Any]:
    if not progress:
        return {}
    parsed = _parse_json(progress.get("locationJson"), {})
    return parsed if isinstance(parsed, dict) else {}


def progress_navigation(
    progress: dict[str, Any] | None,
    units: list[dict[str, Any]],
) -> dict[str, Any]:
    location = progress_location(progress)
    foliate = location.get("foliate")
    foliate = foliate if isinstance(foliate, dict) else {}
    toc = foliate.get("toc")
    toc = toc if isinstance(toc, dict) else {}
    section = foliate.get("section")
    section = section if isinstance(section, dict) else {}
    current_href = toc.get("href") or location.get("href")
    navigation_key = toc.get("navigationKey")
    section_index = number_or_none(section.get("current"))
    chapter_index = number_or_none(toc.get("index"))
    unit = None
    if isinstance(navigation_key, str) and navigation_key:
        unit = next(
            (item for item in units if _unit_navigation_key(item) == navigation_key),
            None,
        )
    if unit is None:
        unit_index = reader_unit_index(current_href, units)
        if unit_index is not None:
            unit = units[unit_index]
    resolved_href = (
        unit.get("href")
        if unit and isinstance(unit.get("href"), str) and unit.get("href")
        else current_href
        if isinstance(current_href, str)
        else None
    )
    return {
        "progressExtra": {},
        "currentHref": resolved_href,
        "currentSectionIndex": section_index,
        "currentChapterIndex": chapter_index,
        "currentChapterTitle": (unit.get("title") if unit else None)
        or (toc.get("title") if isinstance(toc.get("title"), str) else None),
        "currentChapterSortOrder": number_or_none(unit.get("sortOrder"))
        if unit
        else None,
        "currentPageNumber": number_or_none(
            location.get("pageIndex")
            if location.get("type") == "comic"
            else location.get("pageNumber")
            if location.get("type") == "pdf"
            else None
        ),
        "progressEstimated": False,
    }


def progress_percent_with_navigation(
    progress: dict[str, Any] | None,
    units: list[dict[str, Any]],
) -> int:
    return raw_progress_percent(progress)
