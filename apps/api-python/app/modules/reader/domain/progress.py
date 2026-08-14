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


def _unit_reading_order_position(unit: dict[str, Any]) -> int | None:
    metadata = _parse_json(unit.get("metadataJson"), {})
    if not isinstance(metadata, dict):
        return None
    position = number_or_none(metadata.get("readingOrderPosition"))
    return position if position is not None and position >= 1 else None


def reader_unit_index_at_position(
    current_position: Any,
    units: list[dict[str, Any]],
) -> int | None:
    """Resolve the TOC range containing an exact Publication position.

    A position identifies a reading-order resource, not an anchor inside that
    resource. When multiple TOC entries start at the same position, selecting
    any one of them would be a guess, so the chapter remains unresolved.
    """

    position = number_or_none(current_position)
    if position is None or position < 1:
        return None
    candidates = [
        (index, unit_position)
        for index, unit in enumerate(units)
        if (unit_position := _unit_reading_order_position(unit)) is not None
        and unit_position <= position
    ]
    if not candidates:
        return None
    nearest_position = max(unit_position for _, unit_position in candidates)
    nearest_indexes = [
        index
        for index, unit_position in candidates
        if unit_position == nearest_position
    ]
    return nearest_indexes[0] if len(nearest_indexes) == 1 else None


def progress_location(progress: dict[str, Any] | None) -> dict[str, Any]:
    if not progress:
        return {}
    parsed = _parse_json(progress.get("locationJson"), {})
    return parsed if isinstance(parsed, dict) else {}


def _current_page_number(location: dict[str, Any]) -> int | None:
    if location.get("kind") in {"comic", "pdf"}:
        page_index = number_or_none(location.get("pageIndex"))
        return page_index + 1 if page_index is not None else None
    if location.get("type") == "comic":
        return number_or_none(location.get("pageIndex"))
    if location.get("type") == "pdf":
        return number_or_none(location.get("pageNumber"))
    return None


def progress_navigation(
    progress: dict[str, Any] | None,
    units: list[dict[str, Any]],
) -> dict[str, Any]:
    location = progress_location(progress)
    engine_locator = location.get("engineLocator")
    engine_locator = (
        engine_locator
        if isinstance(engine_locator, dict)
        else location
        if location.get("engine") == "readium"
        else {}
    )
    payload = (
        engine_locator.get("payload")
        if engine_locator.get("engine") == "readium"
        else None
    )
    payload = payload if isinstance(payload, dict) else {}
    current_href = payload.get("href")
    locations = payload.get("locations")
    locations = locations if isinstance(locations, dict) else {}
    fragments = locations.get("fragments")
    if (
        isinstance(current_href, str)
        and "#" not in current_href
        and isinstance(fragments, list)
        and len(fragments) == 1
        and isinstance(fragments[0], str)
        and fragments[0]
    ):
        current_href = f"{current_href}#{fragments[0].lstrip('#')}"
    unit_index = reader_unit_index(current_href, units)
    if unit_index is None:
        unit_index = reader_unit_index_at_position(locations.get("position"), units)
    unit = units[unit_index] if unit_index is not None else None
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
        "currentSectionIndex": None,
        "currentChapterIndex": unit_index,
        "currentChapterTitle": unit.get("title") if unit else None,
        "currentChapterSortOrder": number_or_none(unit.get("sortOrder"))
        if unit
        else None,
        "currentPageNumber": _current_page_number(location),
        "progressEstimated": False,
    }


def progress_percent_with_navigation(
    progress: dict[str, Any] | None,
    units: list[dict[str, Any]],
) -> int:
    return raw_progress_percent(progress)
