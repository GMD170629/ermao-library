"""Pure progress navigation and percent projection rules."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import unquote

from app.core.time import to_timestamp_ms

_VOLUME_AWARE_READER_FORMATS = {
    "EPUB",
    "MOBI",
    "AZW",
    "AZW3",
    "PRC",
    "FB2",
    "TXT",
    "COMIC",
    "AUDIO",
}


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


def progress_for_volume(
    progresses: list[dict[str, Any]],
    volume_id: str | None,
) -> dict[str, Any] | None:
    if volume_id:
        specific = next((item for item in progresses if item.get("volumeId") == volume_id), None)
        if specific:
            return specific
    return next((item for item in progresses if not item.get("volumeId")), None)


def display_progress_percent(
    edition: dict[str, Any] | None,
    progress: dict[str, Any] | None,
    volumes: list[dict[str, Any]],
    progresses: list[dict[str, Any]] | None = None,
) -> int:
    if edition and str(edition.get("format") or "").upper() == "AUDIO" and len(volumes) > 1:
        progress_rows = progresses or ([progress] if progress else [])
        weighted_total = 0.0
        duration_total = 0.0
        for volume in volumes:
            duration = max(1.0, float(volume.get("durationMs") or 0))
            volume_progress = progress_for_volume(progress_rows, str(volume["id"]))
            weighted_total += duration * raw_progress_percent(volume_progress)
            duration_total += duration
        return max(0, min(100, round(weighted_total / duration_total))) if duration_total else 0
    return raw_progress_percent(progress)


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
        if normalize_reader_href(unit.get("href"), include_fragment=False) == resource_href
    ]
    return resource_matches[0] if len(resource_matches) == 1 else None


def progress_extra(progress: dict[str, Any] | None) -> dict[str, Any]:
    if not progress:
        return {}
    parsed = _parse_json(progress.get("extra"), {})
    return parsed if isinstance(parsed, dict) else {}


def progress_navigation(
    progress: dict[str, Any] | None,
    units: list[dict[str, Any]],
) -> dict[str, Any]:
    extra = progress_extra(progress)
    current_href = extra.get("chapterHref") or extra.get("currentHref")
    section_index = number_or_none(
        extra.get("chapterSectionIndex")
        if extra.get("chapterSectionIndex") is not None
        else extra.get("sectionIndex")
        if extra.get("sectionIndex") is not None
        else extra.get("chapterIndex")
    )
    sort_order = number_or_none(extra.get("chapterSortOrder"))
    unit = None
    unit_index = reader_unit_index(current_href, units)
    if unit_index is not None:
        unit = units[unit_index]
    if unit is None and sort_order is not None:
        unit = next(
            (item for item in units if number_or_none(item.get("sortOrder")) == sort_order),
            None,
        )
    if unit is None and not current_href and section_index is not None and 0 <= section_index < len(units):
        unit = units[section_index]
    return {
        "progressExtra": extra,
        "currentHref": unit.get("href") if unit else (current_href if isinstance(current_href, str) else None),
        "currentSectionIndex": section_index,
        "currentChapterTitle": (unit.get("title") if unit else None)
        or (extra.get("chapterTitle") if isinstance(extra.get("chapterTitle"), str) else None),
        "currentChapterSortOrder": number_or_none(unit.get("sortOrder")) if unit else sort_order,
    }


def progress_percent_with_navigation(
    progress: dict[str, Any] | None,
    units: list[dict[str, Any]],
) -> int:
    raw_percent = raw_progress_percent(progress)
    if raw_percent > 0 or not progress or not units:
        return raw_percent
    extra = progress_extra(progress)
    current_href = extra.get("chapterHref") or extra.get("currentHref")
    sort_order = number_or_none(extra.get("chapterSortOrder"))
    section_index = number_or_none(
        extra.get("chapterSectionIndex")
        if extra.get("chapterSectionIndex") is not None
        else extra.get("sectionIndex")
        if extra.get("sectionIndex") is not None
        else extra.get("chapterIndex")
    )
    unit_index = reader_unit_index(current_href, units)
    if unit_index is None and sort_order is not None:
        unit_index = next(
            (
                index
                for index, unit in enumerate(units)
                if number_or_none(unit.get("sortOrder")) == sort_order
            ),
            None,
        )
    if unit_index is None and not current_href and section_index is not None and 0 <= section_index < len(units):
        unit_index = section_index
    if unit_index is None:
        return raw_percent
    section_page = number_or_none(extra.get("sectionPage"))
    section_total = number_or_none(extra.get("sectionTotalPages"))
    section_offset = (
        (max(0, min(section_total - 1, section_page - 1)) / section_total)
        if section_page and section_total and section_total > 1
        else 0
    )
    return max(0, min(100, round(((unit_index + section_offset) / len(units)) * 100)))


def _progress_updated_at_ms(progress: dict[str, Any]) -> int:
    return to_timestamp_ms(progress.get("updatedAt")) or 0


def latest_progress(progresses: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next(
        iter(sorted(progresses, key=_progress_updated_at_ms, reverse=True)),
        None,
    )


def choose_continue_volume(
    volumes: list[dict[str, Any]],
    progresses: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not volumes:
        return None
    progress_by_volume = {
        volume["id"]: raw_progress_percent(progress_for_volume(progresses, volume["id"]))
        for volume in volumes
    }
    for volume in volumes:
        percent = progress_by_volume.get(volume["id"], 0)
        if 0 < percent < 100:
            return volume
    if not any(percent > 0 for percent in progress_by_volume.values()):
        latest_volume_progress = next(
            (
                item
                for item in sorted(progresses, key=_progress_updated_at_ms, reverse=True)
                if item.get("volumeId")
            ),
            None,
        )
        if latest_volume_progress:
            latest_volume = next(
                (
                    volume
                    for volume in volumes
                    if volume.get("id") == latest_volume_progress.get("volumeId")
                ),
                None,
            )
            if latest_volume:
                return latest_volume
    for volume in volumes:
        if progress_by_volume.get(volume["id"], 0) <= 0:
            return volume
    return volumes[-1]


def empty_progress_for_volume(
    edition: dict[str, Any] | None,
    volume: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not edition or not volume:
        return None
    return {
        "editionId": edition.get("id"),
        "workId": edition.get("workId"),
        "volumeId": volume.get("id"),
        "position": "0",
        "page": None,
        "percent": 0,
        "extra": "{}",
        "updatedAt": None,
    }


def continue_progress_for_edition(
    edition: dict[str, Any] | None,
    progresses: list[dict[str, Any]],
    volumes: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if edition and edition.get("format") in _VOLUME_AWARE_READER_FORMATS and len(volumes) > 1:
        volume = choose_continue_volume(volumes, progresses)
        volume_progress = progress_for_volume(progresses, volume.get("id") if volume else None)
        return volume_progress or empty_progress_for_volume(edition, volume)
    return latest_progress(progresses)


def progress_chapter_label(
    progress: dict[str, Any] | None,
    volumes: list[dict[str, Any]],
    units: list[dict[str, Any]] | None = None,
) -> str:
    if not progress or not progress.get("page"):
        return "未开始"
    navigation = progress_navigation(progress, units or [])
    volume_id = progress.get("volumeId")
    volume = (
        next((item for item in volumes if item.get("id") == volume_id), None)
        if volume_id
        else None
    )
    prefix = f"{volume.get('title') or '未命名卷'} · " if volume and len(volumes) > 1 else ""
    if navigation.get("currentChapterTitle"):
        return f"{prefix}{navigation['currentChapterTitle']} · 第 {progress.get('page')} 页"
    return f"{prefix}第 {progress.get('page')} 页"
