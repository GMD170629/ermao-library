"""Shared helpers used across media-specific import commands.

Pure parsing/naming utilities plus small store/queries-bound helpers that are
not specific to one media format (EPUB/PDF/Comic/Audio/Text).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree

from app.core.time import now_timestamp_ms
from app.modules.imports.application.dto import (
    ImportOptions,
    ImportResult,
    SeriesVolumeInfo,
)
from app.modules.imports.application.identity_policy import (
    UNKNOWN_AUTHOR,
    normalize_identity_part,
    parse_bracketed_series_identity,
)
from app.modules.imports.application.import_policy import REFLOWABLE_SOURCE_EXTS
from app.modules.imports.application.ports import (
    ImportLibraryQueries,
    ImportOrchestrationServices,
    LibraryImportStore,
)
from app.modules.imports.application.release_titles import parse_release_title
from app.modules.imports.application.work_resolution import resolve_work_identity
from app.modules.imports.domain.content_classification import ContentClassification

SUPPORTED_EXTS = {
    ".epub",
    ".cbr",
    ".cbz",
    ".rar",
    ".zip",
    ".pdf",
    *REFLOWABLE_SOURCE_EXTS,
}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_EPUB_SIZE_BYTES = 512 * 1024 * 1024
MAX_TEXT_EBOOK_SIZE_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_SIZE_BYTES = 2 * 1024 * 1024 * 1024


def import_file_size_limit_bytes_for_ext(ext: str) -> int | None:
    normalized = ext if ext.startswith(".") else f".{ext}"
    normalized = normalized.lower()
    if normalized == ".epub":
        return MAX_EPUB_SIZE_BYTES
    if normalized in REFLOWABLE_SOURCE_EXTS:
        return MAX_TEXT_EBOOK_SIZE_BYTES
    if normalized in {".cbr", ".cbz", ".rar", ".zip"}:
        return MAX_ARCHIVE_SIZE_BYTES
    return None


def _id() -> str:
    return f"py_{time.time_ns()}"


def _now() -> int:
    return now_timestamp_ms()


def _content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_key(value: Any) -> str:
    return normalize_identity_part(value)


def _work_merge_key(title: str) -> str:
    return resolve_work_identity(title=title).merge_key


def _usable_merge_identifier(identifier: str | None) -> bool:
    if not identifier:
        return False
    value = str(identifier).strip().lower()
    return not (
        value.startswith("urn:uuid:")
        or re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value
        )
    )


def _source_group_key(options: ImportOptions, _fallback_title: str) -> str:
    source_directory = str(
        (options.original_source_file_path or options.source_file_path).resolve().parent
    )
    return f"{options.origin.lower()}:{_hash_text(source_directory)[:24]}"


def _source_filename_title(options: ImportOptions) -> str:
    """Return the user-visible source filename without its final extension."""

    original_name = str(options.original_name or "").replace("\\", "/")
    filename = original_name.rsplit("/", 1)[-1] or options.source_file_path.name
    return Path(filename).stem.strip() or options.source_file_path.stem


def _file_resource_key(fmt: str, path: Path) -> str:
    return f"{fmt}:{_hash_text(str(path.resolve()))[:24]}"


def _classification_columns(
    classification: ContentClassification,
) -> dict[str, object]:
    return {
        "classificationSource": classification.source.value,
        "classificationReason": classification.reason,
        "suggestedMediaKind": classification.suggested_media_kind,
    }


def _classification_result_type(classification: ContentClassification) -> str:
    return {
        "COMIC": "comic",
        "AUDIOBOOK": "audiobook",
    }.get(classification.media_kind, "ebook")


def _extract_isbn(ids: list[str]) -> str | None:
    for value in ids:
        if "isbn" not in str(value).lower():
            continue
        candidates = re.findall(
            r"(?:97[89][-\s]?)?[0-9][0-9Xx\-\s]{8,16}[0-9Xx]", value
        )
        for candidate in candidates:
            normalized = re.sub(r"[^0-9Xx]", "", candidate).upper()
            if _valid_isbn(normalized):
                return normalized
    return None


def _preferred_identifier(ids: list[str]) -> str | None:
    for value in ids:
        if "isbn" in str(value).lower():
            continue
        cleaned = str(value or "").strip()
        if cleaned and _usable_merge_identifier(cleaned):
            return cleaned
    return None


def _valid_isbn(value: str) -> bool:
    if len(value) == 13 and value.isdigit():
        total = sum(
            (1 if index % 2 == 0 else 3) * int(char)
            for index, char in enumerate(value[:12])
        )
        return (10 - total % 10) % 10 == int(value[-1])
    if len(value) == 10 and re.fullmatch(r"[0-9]{9}[0-9X]", value):
        total = sum(
            (10 - index) * (10 if char == "X" else int(char))
            for index, char in enumerate(value)
        )
        return total % 11 == 0
    return False


def _sanitize_description(value: str | None) -> str | None:
    return (
        re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", value)).strip() if value else None
    )


def _title_from_file(path: Path) -> str:
    return re.sub(r"[_-]+", " ", Path(path).stem).strip() or Path(path).name


def _safe_entry_name(name: str) -> bool:
    normalized = str(PurePosixPath(name.replace("\\", "/")))
    return bool(
        name
        and not name.startswith("/")
        and not re.match(r"^[a-zA-Z]:", name)
        and not normalized.startswith("../")
        and "/../" not in normalized
    )


def _ignored_entry(name: str) -> bool:
    parts = name.split("/")
    last = parts[-1]
    return (
        "__MACOSX" in parts
        or last in {".DS_Store", "Thumbs.db"}
        or last.startswith("._")
        or any(part.startswith(".") for part in parts)
    )


def _natural_key(value: str) -> list[Any]:
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", value)
    ]


def _split_tags(value: str | None) -> list[str]:
    return [tag.strip() for tag in re.split(r"[,，;]", value or "") if tag.strip()]


def _clean_title_part(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("_", " ").replace("-", " ")).strip()


def _bracketed_folder_metadata(value: str) -> dict[str, str] | None:
    parts = [
        _clean_title_part(match.group(1))
        for match in re.finditer(r"\[([^\]]+)\]", value)
    ]
    if len(parts) == 2 and "".join(parts) and _is_exact_bracket_sequence(value, 2):
        return {"title": parts[0], "author": parts[1]}
    return None


def _series_folder_metadata(
    value: str, filename: str | None = None
) -> dict[str, str] | None:
    inferred = parse_bracketed_series_identity(value, filename)
    if inferred:
        return {"title": inferred[0], "author": inferred[1]}
    raw_parts = [match.group(1) for match in re.finditer(r"\[([^\]]+)\]", value)]
    parts = [_clean_title_part(part) for part in raw_parts]
    if (
        len(parts) >= 3
        and parts[0]
        and parts[1]
        and _volume_range_part(raw_parts[2])
        and _is_exact_bracket_sequence(value)
    ):
        return {"title": parts[0], "author": parts[1]}
    if len(parts) == 2 and "".join(parts) and _is_exact_bracket_sequence(value, 2):
        return {"title": parts[0], "author": parts[1]}
    return None


def _is_exact_bracket_sequence(value: str, count: int | None = None) -> bool:
    repeat = f"{{{count}}}" if count is not None else "+"
    return bool(re.fullmatch(rf"\s*(?:\[[^\]]+\]\s*){repeat}", value))


def _volume_range_part(value: str) -> bool:
    return bool(
        re.search(
            r"(?:vol\.?|volume|v|第)?\s*\d+(?:\.\d+)?\s*[-~至到]\s*(?:vol\.?|volume|v|第)?\s*\d+(?:\.\d+)?",
            value,
            re.IGNORECASE,
        )
    )


def _volume_index_from_suffix(value: str) -> float | None:
    suffix = _clean_title_part(value).strip()
    suffix = re.sub(r"^[\s._\-~～]+", "", suffix)
    if not suffix:
        return None
    for pattern in [
        r"(?:^|\s)(?:vol\.?|volume|v)\s*(\d+(?:\.\d+)?)$",
        r"(?:^|\s)(?:第\s*)?(\d+(?:\.\d+)?)\s*(?:卷|冊|册|集)$",
        r"(?:^|\s)(\d+(?:\.\d+)?)$",
    ]:
        match = re.search(pattern, suffix, re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def parse_series_volume_info(
    path: Path,
    original_name: str | None = None,
    origin: str = "WATCH",
) -> SeriesVolumeInfo | None:
    source = original_name or path.name
    base = _clean_title_part(Path(source).stem)
    folder = (
        _series_folder_metadata(path.parent.name, source) if origin == "WATCH" else None
    )
    folder_title = (folder or {}).get("title")
    author = (folder or {}).get("author")
    if folder_title:
        suffix = base
        title_key = _normalize_key(folder_title)
        base_key = _normalize_key(base)
        if base_key.startswith(title_key):
            suffix = base[len(folder_title) :].strip()
        volume_index = _volume_index_from_suffix(suffix)
        if volume_index is not None:
            return SeriesVolumeInfo(
                series_name=folder_title,
                series_index=volume_index,
                title=f"第 {volume_index:g} 卷",
                author=author,
            )
    parsed_release = parse_release_title(base)
    if parsed_release is not None:
        return SeriesVolumeInfo(
            series_name=parsed_release.series_name,
            series_index=parsed_release.volume_index,
            title=f"第 {parsed_release.volume_index:g} 卷",
            author=author,
        )
    return None


def _first_text(xml: str, tag: str) -> str | None:
    values = _texts(xml, tag)
    return values[0] if values else None


def _texts(xml: str, tag: str) -> list[str]:
    values = []
    for match in re.finditer(
        rf"<(?:[\w]+:)?{re.escape(tag)}\b[^>]*>([\s\S]*?)</(?:[\w]+:)?{re.escape(tag)}>",
        xml,
        re.IGNORECASE,
    ):
        text_value = _decode_xml_text(match.group(1))
        if text_value:
            values.append(text_value)
    return values


def _decode_xml_text(value: str) -> str:
    value = re.sub(r"<!\[CDATA\[([\s\S]*?)\]\]>", r"\1", value)
    value = re.sub(r"<[^>]+>", " ", value)
    try:
        value = ElementTree.fromstring(f"<x>{value}</x>").text or value
    except ElementTree.ParseError:
        pass
    return re.sub(r"\s+", " ", value).strip()


def _attrs(xml: str, name: str) -> list[dict[str, str]]:
    output = []
    for match in re.finditer(rf"<{name}\b([^>]*)/?>(?:</{name}>)?", xml, re.IGNORECASE):
        output.append(
            {
                item.group(1): item.group(2) or item.group(3) or ""
                for item in re.finditer(
                    r"""([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""", match.group(1)
                )
            }
        )
    return output


def _ensure_work(
    store: LibraryImportStore,
    queries: ImportLibraryQueries,
    data: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    merge_key = str(data["mergeKey"])
    existing = queries.get_work_by_merge_key(
        merge_key
    ) or queries.get_work_by_normalized_title(_normalize_key(data["title"]))
    if existing:
        incoming_author = str(data.get("author") or "").strip()
        current_author = str(existing.get("author") or "").strip()
        columns: dict[str, object] = {
            "hidden": False,
            "mergeKey": merge_key,
            "updatedAt": _now(),
        }
        if _author_is_missing(current_author) and not _author_is_missing(
            incoming_author
        ):
            columns.update(
                author=incoming_author,
                normalizedAuthor=_normalize_key(incoming_author),
            )
        store.update_library_work(existing["id"], columns=columns)
        return queries.get_work_by_id(str(existing["id"])) or existing, False
    row = store.insert_library_work(
        columns={
            "id": _id(),
            "monitorFolderId": data.get("monitorFolderId"),
            "origin": data["origin"],
            "title": data["title"],
            "normalizedTitle": _normalize_key(data["title"]),
            "author": data["author"],
            "normalizedAuthor": _normalize_key(data["author"]),
            "description": data.get("description"),
            "status": "UNREAD",
            "publicationStatus": "UNKNOWN",
            "trackingStatus": "NOT_TRACKING",
            "tags": json.dumps(data["tags"], ensure_ascii=False),
            "metadataQuality": 0,
            "organizeStatus": "UNASSESSED",
            "coverStatus": "PENDING",
            "hidden": False,
            "organized": False,
            "mergeKey": data["mergeKey"],
            "createdAt": _now(),
            "updatedAt": _now(),
        }
    )
    return row, True


def _author_is_missing(value: object) -> bool:
    normalized = _normalize_key(value)
    return normalized in {
        "",
        _normalize_key(UNKNOWN_AUTHOR),
        _normalize_key("Unknown author"),
    }


def _preferred_work_cover_path(
    queries: ImportLibraryQueries,
    work_id: str,
    media_version_id: str | None,
    services: ImportOrchestrationServices,
) -> str | None:
    if media_version_id:
        volumes = queries.list_volume_cover_paths_for_media_version(
            str(media_version_id)
        )
        volume = next(
            (
                item
                for item in volumes
                if not services.is_default_cover_path(item.get("coverPath"))
            ),
            volumes[0] if volumes else None,
        )
        if volume and volume.get("coverPath"):
            return str(volume["coverPath"])
        media_version = queries.get_media_version_cover_path(str(media_version_id))
        if media_version and media_version.get("coverPath"):
            return str(media_version["coverPath"])
    media_version = queries.find_work_cover_media_version(work_id)
    return (
        str(media_version["coverPath"])
        if media_version and media_version.get("coverPath")
        else None
    )


def _is_generated_work_cover_path(
    queries: ImportLibraryQueries, work_id: str, cover_path: str
) -> bool:
    return bool(queries.has_generated_cover_path(work_id, cover_path))


def _finalize_work_cover(
    store: LibraryImportStore,
    queries: ImportLibraryQueries,
    services: ImportOrchestrationServices,
    work_id: str,
    media_version_id: str,
    cover_path: str | None,
) -> None:
    work = queries.get_work_by_id(work_id)
    if not work:
        return
    preferred_cover_path = (
        _preferred_work_cover_path(queries, work_id, media_version_id, services)
        or cover_path
        or services.ensure_default_cover()
    )
    current_cover_path = work.get("coverPath")
    should_update_cover = not current_cover_path or _is_generated_work_cover_path(
        queries, work_id, str(current_cover_path)
    )
    store.update_library_work(
        work_id,
        columns={
            "coverPath": preferred_cover_path
            if should_update_cover
            else current_cover_path,
            "coverStatus": services.cover_status(
                preferred_cover_path if should_update_cover else current_cover_path,
            ),
            "updatedAt": _now(),
        },
    )


def _select_volume_media_version(
    queries: ImportLibraryQueries,
    work_id: str,
    fmt: str,
    source_key: str,
) -> dict[str, Any] | None:
    media_versions = queries.list_visible_media_versions_for_work_and_format(
        work_id, fmt
    )
    for media_version in media_versions:
        if media_version.get("sourceGroupKey") == source_key:
            return media_version
    return None


def _insert_identity_metadata(
    store: LibraryImportStore, volume_id: str, identity: Any
) -> None:
    store.insert_library_metadata(
        columns={
            "id": _id(),
            "volumeId": volume_id,
            "source": f"identity_{identity.source}",
            "rawJson": json.dumps(identity.raw_metadata(), ensure_ascii=False),
            "createdAt": _now(),
            "updatedAt": _now(),
        }
    )


def _log_import(
    store: LibraryImportStore, task_id: str | None, level: str, message: str
) -> None:
    if task_id:
        store.insert_import_log(
            columns={
                "id": _id(),
                "importTaskId": task_id,
                "level": level,
                "message": message,
                "createdAt": _now(),
            }
        )


def _ensure_import_task(
    store: LibraryImportStore,
    queries: ImportLibraryQueries,
    options: ImportOptions,
) -> str:
    existing = queries.get_pending_import_task_for_source(str(options.source_file_path))
    if existing:
        return str(existing["id"])
    row = store.insert_import_task(
        columns={
            "id": _id(),
            "monitorFolderId": options.monitor_folder_id,
            "origin": options.origin,
            "status": "PENDING",
            "originalName": options.original_name or options.source_file_path.name,
            "requestedTitle": options.requested_title,
            "requestedAuthor": options.requested_author,
            "sourcePath": str(options.source_file_path),
            "progress": 0,
            "duplicate": False,
            "duration": 0,
            "message": "等待导入",
            "createdAt": _now(),
            "updatedAt": _now(),
        }
    )
    return str(row["id"])


def _existing_file_result(
    queries: ImportLibraryQueries, path: Path
) -> ImportResult | None:
    existing = queries.existing_file_import_snapshot(path)
    if not existing:
        return None
    file_format = str(existing.get("format") or "").lower()
    total_units = int(existing.get("pageCount") or existing.get("chapterCount") or 0)
    result_type = (
        "comic"
        if file_format == "comic"
        else "audiobook"
        if file_format == "audio"
        else "ebook"
    )
    return ImportResult(
        str(existing["workId"]),
        str(existing["workId"]),
        str(existing["mediaVersionId"]),
        str(existing["volumeId"]) if existing.get("volumeId") else None,
        str(existing.get("title") or "未命名作品"),
        result_type,
        file_format,
        total_units,
        "completed",
        True,
        True,
        "duplicate-file-path",
    )


def _existing_audio_bundle_result(
    queries: ImportLibraryQueries, paths: list[Path]
) -> ImportResult | None:
    if not paths:
        return None
    rows = queries.list_file_volumes_by_paths([str(path.resolve()) for path in paths])
    if len(rows) != len(paths) or len({row.get("volumeId") for row in rows}) != 1:
        return None
    return _existing_file_result(queries, paths[0])
